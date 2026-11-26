"""Decode original frame presentation times using FFmpeg. Keep each clip on its own clock."""
from pathlib import Path
import re
import subprocess
import imageio_ffmpeg
import statistics

def frames(path):
    p=subprocess.Popen([imageio_ffmpeg.get_ffmpeg_exe(),'-hide_banner','-nostdin','-copyts','-i',str(path),
        '-map','0:v:0','-an','-vf','showinfo','-vsync','0','-f','null','-'],stderr=subprocess.PIPE,
        stdout=subprocess.DEVNULL,text=True,encoding='utf8',errors='replace')
    try:
        for line in p.stderr:
            m=re.search(r'\bn:\s*(\d+)\s+pts:\s*(-?\d+)\s+pts_time:\s*([-\d.eE+]+)',line)
            if m:yield int(m[1]),int(m[2]),float(m[3])
        if p.wait():raise ValueError("FFmpeg could not decode the selected clip. Select an original, readable video.")
    finally:
        p.stderr.close()
        if p.poll() is None:p.kill();p.wait()

def index_clip(path, target):
    first=prev=None;intervals=[];n=0
    with Path(target).open('w',encoding='ascii') as f:
        f.write('frame,source_tick,source_pts_s,elapsed_s\n')
        for i,tick,sec in frames(path):
            if first is None:first=sec
            if prev is not None:
                if sec<=prev:raise ValueError("Non-increasing video presentation times; split this clip at the discontinuity")
                if len(intervals)<4096:intervals.append(sec-prev)
            f.write(f'{i},{tick},{sec:.9f},{sec-first:.9f}\n');prev=sec;n+=1
    if n<2:raise ValueError("Video has fewer than two readable frames")
    return dict(frames=n,first_pts=first,last_pts=prev,frame_period_s=statistics.median(intervals),duration=prev-first+statistics.median(intervals))

