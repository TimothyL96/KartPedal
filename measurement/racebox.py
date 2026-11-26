"""RaceBox extended-header CSV, UTC custom export. Units are an explicit import setting."""
import csv
import math
import statistics
import re
from datetime import datetime
from itertools import islice
from engine import clock_fit, to_source

def records(path, speed_unit):
    factor={'km/h':1.,'mph':1.609344,'m/s':3.6}.get(speed_unit)
    if factor is None:raise ValueError("Choose the speed unit used in the RaceBox export")
    with open(path,newline='',encoding='utf-8-sig') as f:
        lines=csv.reader(f);fields=None
        for line in lines:
            if line[:1]==['Record']:
                fields=line;break
        need=('Record','Time','Latitude','Longitude','Speed','Lap')
        if fields is None or not set(need)<=set(fields):raise ValueError("Export RaceBox custom CSV with UTC time, GPS, speed and lap fields")
        idx=[fields.index(k) for k in need];prev=None
        for row in lines:
            if not row:continue
            try:
                rec,stamp,lat,lon,speed,lap=(row[i] for i in idx)
                dt=datetime.fromisoformat(stamp.replace('Z','+00:00'))
                if dt.tzinfo is None:raise ValueError('UTC timezone required')
                t=dt.timestamp();lat=float(lat);lon=float(lon);speed=float(speed)*factor;lap=int(lap)
                if not(-90<=lat<=90 and -180<=lon<=180 and math.isfinite(speed) and speed>=0):raise ValueError('GPS value')
                if prev is not None and t<=prev:raise ValueError('time not increasing')
            except (ValueError,IndexError) as e:raise ValueError(f"RaceBox CSV line {lines.line_num}: {e}") from e
            if prev is None:origin=t
            prev=t
            yield t-origin,lat,lon,speed,lap,dt

def gps_export(path,unit,anchors,emit,duration):
    # Anchor abscissas are UTC elapsed from the first actual record, independent of any IMU events.
    fit=clock_fit(anchors)
    if not fit['withheld']:raise ValueError('Add a separate GPS/video check crossing')
    declared={}
    with open(path,newline='',encoding='utf-8-sig') as f:
        for row in csv.reader(f):
            if row[:1]==['Record']:break
            if len(row)>=2 and re.fullmatch(r'Lap [1-9]\d*',row[0]):
                value=float(row[1])
                if not math.isfinite(value) or value<=0:raise ValueError('Invalid RaceBox header lap duration')
                declared[int(row[0].split()[1])]=value
    last=None;steps=[];laps=[];current=None;count=0;distance=0;start=None
    for t,lat,lon,speed,lap,utc in records(path,unit):
        if start is None:start=utc
        src=to_source(t,fit)
        if not fit['low']<=t<=fit['high'] or not 0<=src<duration:continue
        if last:
            dt=t-last[0]
            if len(steps)<1024:steps.append(dt)
            # A cumulative distance across a GPS outage is unknown.
            if dt>.5:distance=float('nan')
            a=math.sin(math.radians(lat-last[1])/2)**2+math.cos(math.radians(lat))*math.cos(math.radians(last[1]))*math.sin(math.radians(lon-last[2])/2)**2
            distance+=12742000*math.asin(math.sqrt(min(1.,a)))
        if current!=lap:
            if current is not None and current>0 and lapstart is not None and (lap==current+1 or lap==0):
                elapsed=src-lapstart
                if current in declared:
                    measured=declared[current]*fit['slope']
                    if abs(measured-elapsed)>max(.1,2*(statistics.median(steps) if steps else 0)):
                        raise ValueError(f'RaceBox lap {current} duration disagrees with GPS transitions. Check layout and file.')
                    elapsed=measured
                laps.append(dict(number=current,start=lapstart,duration=elapsed))
            lapstart=src if current is not None else None
            current=lap
        emit([src,lat,lon,speed,distance if math.isfinite(distance) else ''])
        last=(t,lat,lon);count+=1
    if count<2:raise ValueError('No overlapping GPS samples within independent anchors')
    return dict(count=count,rate=round(1/statistics.median(steps),3),laps=laps,clock=fit,
                utc_first=start.isoformat(),declared_durations=declared,lap_boundary_resolution_s=statistics.median(steps))

