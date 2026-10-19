"""Build a standalone recorded-data map from one or more Baltic CSV captures."""
import argparse,base64,csv,html,io,json,math,urllib.request
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from PIL import Image
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('csv_files',nargs='+',type=Path)
parser.add_argument('--output',type=Path,required=True)
parser.add_argument('--cache-dir',type=Path,default=Path('data/baltic/tile-cache'))
args=parser.parse_args()
WORK=Path(__file__).parent;CACHE=args.cache_dir;CACHE.mkdir(parents=True,exist_ok=True)

def encode(points):
    prev=[0,0];out=[]
    for p in points:
        for j,val in enumerate(p):
            n=round(val*1e6);d=n-prev[j];prev[j]=n;v=~(d<<1) if d<0 else d<<1
            while v>=32:out.append(chr((32|(v&31))+63));v>>=5
            out.append(chr(v+63))
    return ''.join(out)

groups=defaultdict(list);totals={};coords=[];received=[]
for path in args.csv_files:
    with path.open(newline='',encoding='utf8') as handle:rows=list(csv.DictReader(handle))
    totals[str(path)]=len(rows)
    for r in rows:
        if r['coordinates_valid']!='True':continue
        groups[(r['country'],r['train_id'],r['service_date'])].append(r)
        coords.append([float(r['longitude']),float(r['latitude'])]);received.append(r['received_at_utc'])
if not coords:parser.error('no valid-coordinate observations to map')
trains=[]
for (country,ident,date),rows in sorted(groups.items()):
    rows.sort(key=lambda r:r['received_at_utc'])
    segs=[];seg=[];prev_mode=None;prev_time=None;prev_source=None
    for r in rows:
        mode=0 if country=='EE' else 1 if r['is_gps_active']=='True' else 2 if r['is_gps_active']=='False' else 3
        t=datetime.fromisoformat(r['received_at_utc']).timestamp()
        source_t=datetime.fromisoformat(r['source_time_utc'].replace('Z','+00:00')).timestamp() if r['source_time_utc'] else t
        source_gap=country=='EE' and prev_source is not None and (source_t<prev_source or source_t-prev_source>15)
        if seg and (mode!=prev_mode or t-prev_time>15 or source_gap):
            segs.append(dict(mode=prev_mode,encoded=encode(seg)));seg=[]
        seg.append([float(r['longitude']),float(r['latitude'])]);prev_mode=mode;prev_time=t;prev_source=source_t
    if seg:segs.append(dict(mode=prev_mode,encoded=encode(seg)))
    label='LV · '+(rows[0]['route_label'] or ident) if country=='LV' else 'EE · trip '+ident.split('-')[-1]
    trains.append(dict(id=country+'/'+ident+'/'+date,label=label,country=country,count=len(rows),gps=sum(r['is_gps_active']=='True' for r in rows),
                       first=rows[0]['received_at_utc'][11:19],last=rows[-1]['received_at_utc'][11:19],segments=segs))

z=8;n=2**z
def ty(lat):return math.floor((1-math.asinh(math.tan(math.radians(lat)))/math.pi)/2*n)
xmin=math.floor((min(p[0] for p in coords)+180)/360*n);xmax=math.floor((max(p[0] for p in coords)+180)/360*n)
ymin=ty(max(p[1] for p in coords));ymax=ty(min(p[1] for p in coords))
xmin-=1;xmax+=1;ymin-=1;ymax+=1
def get(task):
    layer,x,y=task;f=CACHE/f'{layer}_{z}_{x}_{y}.png'
    if not f.exists():
        host='https://tile.openstreetmap.org' if layer=='base' else 'https://a.tiles.openrailwaymap.org/standard'
        req=urllib.request.Request(f'{host}/{z}/{x}/{y}.png',headers={'User-Agent':'TrainTrackerLocalPreview/1.0'})
        f.write_bytes(urllib.request.urlopen(req,timeout=25).read())
with ThreadPoolExecutor(max_workers=2) as pool:list(pool.map(get,[(l,x,y) for l in ['base','rail'] for x in range(xmin,xmax+1) for y in range(ymin,ymax+1)]))
images={}
for layer in ['base','rail']:
    im=Image.new('RGBA',((xmax-xmin+1)*256,(ymax-ymin+1)*256))
    for x in range(xmin,xmax+1):
        for y in range(ymin,ymax+1):im.paste(Image.open(CACHE/f'{layer}_{z}_{x}_{y}.png').convert('RGBA'),((x-xmin)*256,(y-ymin)*256))
    b=io.BytesIO();im.save(b,format='WEBP',quality=72);images[layer]='data:image/webp;base64,'+base64.b64encode(b.getvalue()).decode()
def lat(y):return math.degrees(math.atan(math.sinh(math.pi*(1-2*y/n))))
meta=dict(west=xmin/n*360-180,east=(xmax+1)/n*360-180,north=lat(ymin),south=lat(ymax+1))
payload=dict(trains=trains,images=images,meta=meta)
fragment=(WORK/'map_template.html').read_text(encoding='utf8')
sub=f'Received {min(received)} – {max(received)} · {len(trains)} services · {len(coords):,} reports'
note='All valid saved positions included; gaps over 15 seconds disconnected. Latvia GPS flags are provider labels; map timestamps are not verified GPS-fix times.'
for a,b in {'__DATA__':json.dumps(payload,separators=(',',':')).replace('<','\\u003c'),'__SUB__':html.escape(sub),'__NOTE__':html.escape(note)}.items():fragment=fragment.replace(a,b)
target=args.output;target.parent.mkdir(parents=True,exist_ok=True)
prefix='''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>Baltic train paths</title><style>
:root{--viz-series-1:#1565c0;--viz-series-2:#00875a;--viz-series-3:#c45100;--viz-series-4:#777;--background:#fff}
body{font:16px system-ui,sans-serif;max-width:1100px;margin:24px auto;padding:0 18px;color:#1d2939;background:#fff}
.text-small{font-size:14px;margin:10px 0}.viz-controls,.viz-row{display:flex;flex-wrap:wrap;gap:18px;align-items:center}
select{font:inherit;padding:5px;max-width:100%}a{color:#1565c0}.cursor-interaction{cursor:pointer}
</style></head><body>'''
target.write_text(prefix+fragment+'</body></html>',encoding='utf8')
print(json.dumps(dict(map=str(target),bytes=target.stat().st_size,services=len(trains),reports=len(coords),totals=totals)))
