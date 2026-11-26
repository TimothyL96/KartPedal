"""Match filmed marker pulses by their duration and actual frame PTS. Refuse ambiguous matches."""
import csv
import json
import cv2

def logged_edges(folder):
    with (folder/'events.jsonl').open(encoding='utf8') as f:
        result=[]
        for line in f:
            e=json.loads(line)
            if e.get('type')=='marker' and e.get('edge')=='rise':result.append((str(e['marker_id']),e['t_us']/1e6))
        return result
def detect(clip,frame_index,roi,ids):
    x,y,w,h=map(int,roi)
    if min(x,y)<0 or min(w,h)<2:raise ValueError('Select a rectangle inside the filmed LED')
    cap=cv2.VideoCapture(str(clip));edges=[];rise=None;seen_dark=False
    try:
        if not cap.isOpened():raise ValueError('Could not decode the video for LED inspection')
        if x+w>cap.get(3) or y+h>cap.get(4):raise ValueError('LED rectangle extends beyond the source frame')
        with frame_index.open() as f:
            for r in csv.DictReader(f):
                ok,frame=cap.read()
                if not ok:raise ValueError('Video and source PTS frame counts disagree')
                t=float(r['elapsed_s'])
                mean=float(cv2.cvtColor(frame[y:y+h,x:x+w],cv2.COLOR_BGR2GRAY).mean())
                if mean>=175 and rise is None and seen_dark:rise=t
                elif mean<=125:
                    seen_dark=True
                    if rise is not None:
                        if .57<=t-rise<=.84:edges.append(rise)
                        rise=None
            if cap.read()[0]:raise ValueError('Video and PTS lengths disagree')
    finally:cap.release()
    if len(edges)!=len(ids) or len(ids)<3:
        raise ValueError(f'Detected {len(edges)} complete LED pulses for {len(ids)} selected IDs. Adjust the ROI or enter three frame times manually.')
    return {str(k):dict(pts=t,role='fit' if i in (0,len(ids)-1) else 'check') for i,(k,t) in enumerate(zip(ids,edges))}

