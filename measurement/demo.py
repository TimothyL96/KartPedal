"""Create separate synthetic SD trees, independent RaceBox clock, calibration video and validation truth."""
import argparse
import csv
from datetime import datetime,timedelta,timezone
from pathlib import Path
import subprocess
import numpy as np
import cv2
import imageio_ffmpeg
from raw_sim import generate,base_position,kart_path,ankle
from pipeline import save

LED={'L':(26,23,14,14),'R':(66,23,14,14)}
def create(root,refit=0,video=True):
    root=Path(root);j=generate(root,144,refit);duration=j['duration']
    scale=1.000081;offset=1.36
    utc=datetime(2026,1,1,tzinfo=timezone.utc)
    gps_t=np.arange(0,duration+offset,.04);t=(gps_t-offset)/scale
    phase,xyz=base_position(t);vel=(base_position(t+.001)[1]-base_position(t-.001)[1])/.002
    with (root/'synthetic-racebox.csv').open('w',newline='') as f:
        w=csv.writer(f);w.writerows([['Format','RaceBox CSV'],['Data Source','KartPedal synthetic'],[],
          ['Record','Time','Latitude','Longitude','Altitude','Speed','GForceX','GForceY','GForceZ','Lap','GyroX','GyroY','GyroZ']])
        for i in range(len(t)):
            stamp=(utc+timedelta(seconds=gps_t[i])).isoformat(timespec='milliseconds').replace('+00:00','Z')
            w.writerow([i+1,stamp,1.33+xyz[i,1]/111195,103.85+xyz[i,0]/111165,0,np.linalg.norm(vel[i,:2])*3.6,'','','',
                         int(phase[i]/(2*np.pi))+(1 if t[i]>=28 else 0),'','',''])
    # Independently filmed timing-panel pulses, distinct from the wearables' LEDs.
    crossings=[1.2,72.,142.];j['gps']=dict(file='synthetic-racebox.csv',unit='km/h',
                  anchors=[[offset+s*scale,s,'check' if i==1 else 'fit'] for i,s in enumerate(crossings)])
    if video:
        j['video']='synthetic-camera.mp4'
        for s in j['legs']:j['legs'][s].update(led_roi=LED[s],auto_led=True)
        frame_times=np.arange(duration*50)/50
        angles={s:ankle(frame_times,s) for s in 'LR'}
        cmd=[imageio_ffmpeg.get_ffmpeg_exe(),'-hide_banner','-loglevel','error','-f','rawvideo','-pix_fmt','bgr24','-s','480x360','-r','50','-i','-','-an','-c:v','libx264','-preset','veryfast','-crf','19','-pix_fmt','yuv420p',str(root/j['video'])]
        proc=subprocess.Popen(cmd,stdin=subprocess.PIPE)
        try:
            for k,t in enumerate(frame_times):
                frame=np.full((360,480,3),(32,26,22),np.uint8)
                for i,s in enumerate('LR'):
                    x,y,w,h=LED[s];edges=j['legs'][s]['markers'].values()
                    lit=any(m['pts']<=t<m['pts']+.7 for m in edges)
                    frame[y:y+h,x:x+w]=245 if lit else 12
                    cv2.putText(frame,s,(x,y+36),0,.48,(210,210,210),1,cv2.LINE_AA)
                    px=118+210*i;py=225
                    cv2.line(frame,(px-72,py-42),(px,py),(162,148,122),6,cv2.LINE_AA)
                    angle=np.deg2rad(18-angles[s][k]);end=(px+int(75*np.cos(angle)),py-int(75*np.sin(angle)))
                    cv2.line(frame,(px,py),end,((206,113,219) if i==0 else (173,219,108)),9,cv2.LINE_AA)
                    cv2.circle(frame,(px,py),6,(236,234,225),-1,cv2.LINE_AA)
                if any(c<=t<c+.25 for c in crossings):frame[23:37,125:139]=245
                cv2.putText(frame,'GPS',(118,58),0,.42,(195,190,182),1,cv2.LINE_AA)
                cv2.putText(frame,'SYNTHETIC  /  CAMERA REFERENCE',(23,304),0,.57,(224,218,206),1,cv2.LINE_AA)
                cv2.putText(frame,f'{t:07.2f} s',(23,332),0,.52,(174,165,145),1,cv2.LINE_AA)
                proc.stdin.write(frame.tobytes())
        finally:
            proc.stdin.close()
            if proc.wait():raise RuntimeError('Failed creating synthetic source footage')
    save(root/'job.json',j)
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('out');p.add_argument('--refit',type=int,default=0);p.add_argument('--no-video',action='store_true');a=p.parse_args()
    create(a.out,a.refit,not a.no_video)

