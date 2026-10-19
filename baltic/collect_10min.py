"""Bounded Baltic passenger-train capture. See MAC_MINI_HANDOFF.md for 24/7 work."""
import argparse, asyncio, base64, csv, gzip, json, math, sys, time, urllib.request
from datetime import datetime, timezone
from pathlib import Path
import websockets
from google.transit import gtfs_realtime_pb2

OUT=Path('data/baltic')
DURATION=600
POLL_INTERVAL=1.0
FIELDS=['country','source','received_at_utc','source_time_utc','timestamp_kind','service_date',
        'train_id','vehicle_id','route_label','latitude','longitude','coordinates_valid',
        'is_gps_active','position_method','animated_latitude','animated_longitude','source_url']
URL_EE='https://jbb.ghsq.de/gtfs/elron/VehiclePositions'
URL_LV='wss://trainmap.pv.lv/ws'

def now():return datetime.now(timezone.utc).isoformat()
def epoch(v):return datetime.fromtimestamp(v,timezone.utc).isoformat() if v else ''
def valid(lat,lon):
    try:return math.isfinite(float(lat)) and math.isfinite(float(lon)) and -90<=float(lat)<=90 and -180<=float(lon)<=180 and (float(lat)!=0 or float(lon)!=0)
    except (ValueError,TypeError):return False

class Capture:
    def __init__(self,country):
        self.country=country;self.base=OUT/country
        self.file=self.base.with_suffix('.csv').open('x',newline='',encoding='utf8')
        self.writer=csv.DictWriter(self.file,FIELDS);self.writer.writeheader()
        self.raw=gzip.open(self.base.with_suffix('.raw.jsonl.gz'),'xt',encoding='utf8')
        self.summary=dict(country=country,state='running',capture_mode='live',started_at_utc=now(),requested_seconds=DURATION,
                          messages=0,rows=0,valid_coordinate_rows=0,gps_flag_true_rows=0,gps_flag_false_rows=0,
                          duplicate_provider_observations_skipped=0,errors=[])
        self.ids=set();self.seen=set();self.checkpoint()
    def checkpoint(self):
        self.summary.update(distinct_service_ids=len(self.ids),updated_at_utc=now())
        tmp=self.base.with_suffix('.tmp');tmp.write_text(json.dumps(self.summary,indent=2),encoding='utf8')
        tmp.replace(self.base.with_suffix('.summary.json'))
    def raw_record(self,data,received):
        self.raw.write(json.dumps(dict(received_at_utc=received,payload=data),ensure_ascii=True)+'\n')
        self.raw.flush();self.summary['messages']+=1
    def row(self,row,key=None):
        if key is not None:
            if key in self.seen:self.summary['duplicate_provider_observations_skipped']+=1;return
            self.seen.add(key)
        row['coordinates_valid']=valid(row['latitude'],row['longitude'])
        self.writer.writerow(row);self.summary['rows']+=1
        self.summary['valid_coordinate_rows']+=int(row['coordinates_valid'])
        if row['is_gps_active'] is True:self.summary['gps_flag_true_rows']+=1
        elif row['is_gps_active'] is False:self.summary['gps_flag_false_rows']+=1
        self.ids.add((row['service_date'],row['train_id']))
    def flush(self):self.file.flush();self.checkpoint()
    def error(self,e):
        self.summary['errors'].append(dict(at_utc=now(),type=type(e).__name__,message=str(e)));self.checkpoint()
    def close(self, completed=False):
        state=('complete' if self.summary['valid_coordinate_rows'] else 'no_valid_positions') if completed else 'interrupted'
        self.file.close();self.raw.close();self.summary.update(state=state,finished_at_utc=now());self.checkpoint()
        print(json.dumps(self.summary),flush=True)

async def latvia(end):
    c=Capture('latvia')
    completed=False
    c.summary['counting']='One row per train in each received map snapshot; repeated positions retained. GPS flag and animated coordinates preserved separately.'
    try:
        while time.monotonic()<end:
            try:
                async with websockets.connect(URL_LV,open_timeout=15,close_timeout=3,max_size=10_000_000) as ws:
                    while time.monotonic()<end:
                        try:msg=await asyncio.wait_for(ws.recv(),max(.1,end-time.monotonic()))
                        except asyncio.TimeoutError:break
                        received=now();c.raw_record({'websocket_text':msg} if isinstance(msg,str) else {'websocket_base64':base64.b64encode(msg).decode()},received);d=json.loads(msg)
                        if d.get('type')=='back-end':
                            for x in d.get('data',[]):
                                p=x.get('returnValue',{});pos=p.get('position') or [None,None];anim=p.get('animatedCoord') or [None,None]
                                flag=p.get('isGpsActive')
                                c.row(dict(country='LV',source='Vivi public map stream',received_at_utc=received,
                                      source_time_utc=p.get('updaterTimeStamp') or d.get('timeStamp',''),timestamp_kind='map_updater_not_verified_GPS_fix',
                                      service_date=(p.get('departureTime') or '')[:10],train_id=str(p.get('id') or p.get('train','')),
                                      vehicle_id='',route_label=str(p.get('train','')),latitude=pos[0],longitude=pos[1],
                                      is_gps_active=flag,position_method='provider_GPS_active' if flag is True else 'estimated_or_GPS_inactive' if flag is False else 'unknown',
                                      animated_latitude=anim[0],animated_longitude=anim[1],source_url=URL_LV))
                            c.flush()
            except Exception as e:
                c.error(e);await asyncio.sleep(max(0,min(5,end-time.monotonic())))
        completed=True
    finally:c.close(completed)
    return c.summary['valid_coordinate_rows']

def fetch_ee():
    with urllib.request.urlopen(urllib.request.Request(URL_EE,headers={'User-Agent':'train-tracker-research'}),timeout=15) as r:return r.read()

async def estonia(end):
    c=Capture('estonia');c.summary['counting']='Distinct trip/date/source timestamp/position reports; repeated polling snapshots excluded.';c.summary['poll_interval_seconds']=POLL_INTERVAL
    completed=False
    try:
        while time.monotonic()<end:
            start=time.monotonic()
            try:
                raw=await asyncio.to_thread(fetch_ee)
                received=now();c.raw_record({'protobuf_base64':base64.b64encode(raw).decode()},received)
                feed=gtfs_realtime_pb2.FeedMessage();feed.ParseFromString(raw)
                for x in feed.entity:
                    if not x.HasField('vehicle') or not x.vehicle.HasField('position'):continue
                    v=x.vehicle;p=v.position
                    if not p.HasField('latitude') or not p.HasField('longitude'):continue
                    key=(v.trip.trip_id,v.trip.start_date,v.timestamp,p.latitude,p.longitude)
                    c.row(dict(country='EE',source='Elron community GTFS-RT',received_at_utc=received,source_time_utc=epoch(v.timestamp),
                          timestamp_kind='vehicle_position_timestamp',service_date=v.trip.start_date,train_id=v.trip.trip_id,
                          vehicle_id=v.vehicle.id,route_label=v.vehicle.label or v.trip.route_id,latitude=p.latitude,longitude=p.longitude,
                          is_gps_active='',position_method='community_relay_provider_position',animated_latitude='',animated_longitude='',source_url=URL_EE),key)
                c.flush()
            except Exception as e:
                c.error(e);await asyncio.sleep(max(0,min(10,end-time.monotonic())))
            await asyncio.sleep(max(0,min(POLL_INTERVAL-(time.monotonic()-start),end-time.monotonic())))
        completed=True
    finally:c.close(completed)
    return c.summary['valid_coordinate_rows']

async def main():
    end=time.monotonic()+DURATION
    counts=await asyncio.gather(latvia(end),estonia(end))
    return 0 if all(counts) else 1

def positive_seconds(value):
    number=float(value)
    if not math.isfinite(number) or number<=0:raise argparse.ArgumentTypeError('must be finite and greater than zero')
    return number

def cli():
    global OUT,DURATION,POLL_INTERVAL
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seconds',type=positive_seconds,default=600,help='capture duration (default: 600)')
    parser.add_argument('--poll-interval',type=positive_seconds,default=1,help='Estonia poll interval in seconds (default: 1)')
    parser.add_argument('--output-dir',type=Path,help='new output directory; default: data/baltic/<UTC run time>')
    args=parser.parse_args()
    DURATION=args.seconds;POLL_INTERVAL=args.poll_interval
    OUT=args.output_dir or Path('data/baltic')/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')
    OUT.mkdir(parents=True,exist_ok=True)
    for country in ('latvia','estonia'):
        for suffix in ('.csv','.raw.jsonl.gz','.summary.json','.tmp'):
            if (OUT/(country+suffix)).exists():parser.error(f'refusing to overwrite {country+suffix}; choose a new output directory')
    print(f'Collecting {DURATION:g} seconds into {OUT.resolve()}',flush=True)
    try:return asyncio.run(main())
    except KeyboardInterrupt:return 130

if __name__=='__main__':sys.exit(cli())
