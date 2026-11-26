"""A transparent foot-channel strip for editing a KartPedal export on a final video canvas."""
import argparse,json,subprocess,tempfile
from contextlib import ExitStack
from pathlib import Path
import numpy as np
import imageio_ffmpeg
from PIL import Image,ImageDraw,ImageFont
from pipeline import save,project_output

FF=imageio_ffmpeg.get_ffmpeg_exe()
def font(size,bold=False):
    for path in (Path('C:/Windows/Fonts')/('segoeuib.ttf' if bold else 'segoeui.ttf'),'DejaVuSans.ttf'):
        try:return ImageFont.truetype(str(path),size)
        except OSError:pass
    return ImageFont.load_default()

def strip(output,dest,fps=50):
    output=Path(output);dest=project_output(dest)
    if dest.exists():raise ValueError('Choose a new overlay output filename')
    q=json.loads((output/'quality.json').read_text());w,h=576,88
    large=font(25,True);small=font(14,True)
    frames=round(q['rows']/100*fps)
    cmd=[FF,'-hide_banner','-loglevel','error','-f','rawvideo','-pixel_format','rgba','-video_size',f'{w}x{h}','-framerate',str(fps),'-i','-','-c:v','prores_ks','-profile:v','4','-pix_fmt','yuva444p10le','-alpha_bits','16',str(dest)]
    proc=subprocess.Popen(cmd,stdin=subprocess.PIPE)
    try:
        with ExitStack() as stack:
            files={s:stack.enter_context((output/(s+'-motion.f32')).open('rb')) for s in q['legs']}
            last=-1
            for k in range(frames):
                idx=min(q['rows']-1,int(k*100/fps))
                img=Image.new('RGBA',(w,h));d=ImageDraw.Draw(img)
                for j,s in enumerate('LR'):
                    x=9+282*j;y=4
                    d.rounded_rectangle((x,y,x+274,y+78),radius=12,fill=(18,22,28,221))
                    tone=(231,152,202,255) if s=='L' else (154,220,173,255)
                    label=('LEFT' if j==0 else 'RIGHT')+'  /  ANKLE'
                    d.text((x+14,y+7),label,font=small,fill=tone)
                    good=False
                    if s in files:
                        f=files[s];f.seek(idx*12);a,_,code=np.frombuffer(f.read(12),'<f4')
                        good=code==0 and np.isfinite(a)
                    d.text((x+14,y+26),f'{a:+.1f}°' if good else 'Unavailable',font=large,fill=(246,246,246,255))
                    d.rounded_rectangle((x+15,y+64,x+258,y+69),radius=2,fill=(83,89,98,255))
                    if good:
                        width=min(243,max(0,round(a/30*243)))
                        if width:d.rounded_rectangle((x+15,y+64,x+15+width,y+69),radius=2,fill=tone)
                proc.stdin.write(img.tobytes())
    finally:
        proc.stdin.close()
        if proc.wait():raise RuntimeError('FFmpeg failed writing the transparent strip')
    return dict(file=dest.name,size=[w,h],fps=fps,frames=frames,format='ProRes 4444',source_time='k / fps from clip first PTS',bar_full_scale_deg=30)
def review(output,source,mov,folder):
    # Keep visible start, driving, deliberate gap, withheld check and end. Same cuts for both layers.
    cuts=[(0,1.3),(39,42),(62.9,64.4),(73,75),(142.5,144)]
    branches=''.join(f'[mix{i}]' for i in range(len(cuts)))
    graph='[0:v]setpts=PTS-STARTPTS,scale=720:540,pad=960:540:120:0[base];[base][1:v]overlay=(W-w)/2:110,split=5'+branches+';'
    graph+=';'.join(f'[mix{i}]trim=start={a}:end={b},setpts=PTS-STARTPTS[v{i}]' for i,(a,b) in enumerate(cuts))
    graph+=';'+''.join(f'[v{i}]' for i in range(len(cuts)))+'concat=n=5:v=1:a=0[v]'
    movie=folder/'review.mp4'
    with tempfile.TemporaryDirectory(dir=folder) as temp:
        staging=Path(temp)/'review.mp4'
        subprocess.run([FF,'-hide_banner','-loglevel','error','-i',str(source),'-i',str(mov),'-filter_complex',graph,'-map','[v]','-an','-c:v','libx264','-preset','veryfast','-crf','17','-pix_fmt','yuv420p',str(staging)],check=True)
        staging.replace(movie)
    mapped=[];t=0
    for a,b in cuts:mapped.append(dict(source_in=a,source_out=b,timeline_in=t));t+=b-a
    save(folder/'edit-map.json',mapped)
    return movie
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('run',type=Path);p.add_argument('output',type=Path);p.add_argument('--demo-review',type=Path);a=p.parse_args()
    meta=strip(a.run,a.output);save(a.output.with_suffix('.json'),meta)
    if a.demo_review:review(a.run,a.demo_review,a.output,a.output.parent)

