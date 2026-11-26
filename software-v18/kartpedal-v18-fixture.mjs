const sampleSeconds=82, width=96, height=72;
const laps=[{number:1,start:0,duration:40},{number:2,start:40,duration:42}];
const markerTimes={L:[0.417,40.021,80.774],R:[0.866,40.467,81.227]};
const clocks={L:{offset:0.65,scale:1.000085},R:{offset:0.22,scale:0.99994}};
const asAscii=s=>Uint8Array.from(s,c=>c.charCodeAt(0));
function markerOn(side,time) {
  return markerTimes[side].some(rise=>time>=rise && time<rise+0.7);
}
function deviceUs(side,sourceTime) {
  const {offset,scale}=clocks[side];
  return Math.round((sourceTime+offset)*scale*1e6);
}
function motionTruth(time,present) {
  const lap=time<40 ? laps[0] : laps[1];
  const theta=(time-lap.start)/lap.duration*2*Math.PI;
  const phase=theta+(lap.number===2 ? 0.045 : 0);
  const leftValid=present.includes('L') && !(time>=19.6 && time<20.2);
  const rightValid=present.includes('R');
  const braking=Math.pow(Math.max(0,Math.cos(2*(phase+0.29))),5);
  const accelerating=0.5-0.5*Math.cos(2*(phase-0.19));
  return {time,lap:lap.number,theta,
    left:leftValid ? 18*braking : null,right:rightValid ? 24*accelerating : null,
    leftValid:Number(leftValid),rightValid:Number(rightValid)};
}
function makeFixture(present='LR') {
  const motion=[],gps=[];
  let distance=0,previous;
  for (let i=0; i<100*sampleSeconds; i++) {
    const row=motionTruth(i/100,present); motion.push(row);
    if (i%4) continue;
    const {theta,lap,time}=row;
    const x=106*Math.cos(theta), y=62*Math.sin(theta);
    if (previous) distance+=Math.hypot(x-previous.x,y-previous.y);
    previous={x,y};
    const lat=1.32+y/111320,lon=103.82+x/(111320*Math.cos(1.32*Math.PI/180));
    const speed=3.6*2*Math.PI/laps[lap-1].duration*Math.hypot(106*Math.sin(theta),62*Math.cos(theta));
    gps.push({time,lap,lat,lon,speed,distance,x,y});
  }
  return {motion,gps,present,laps, synthetic:true, gpsHz:25, motionHz:100, endSeconds:sampleSeconds,
    start:'2026-11-26T00:00:00.000Z', clock:'manual', generator:'KartPedal synthetic fixture', gpsOrigin:'computed',
    timing:[{source:'Synthetic lap boundaries',declared:true,laps}],
    provenance:'SYNTHETIC analytic ankle angles and GPS; no IMU calibration or real clock acceptance'};
}
function testVideo(fixture) {
  const pre=asAscii('YUV4MPEG2 W96 H72 F25:1 Ip A1:1 C420jpeg\n'), tag=asAscii('FRAME\n');
  const ySize=width*height, yuvSize=ySize*3/2;
  const bytes=new Uint8Array(pre.length+(tag.length+yuvSize)*fixture.gps.length);
  bytes.set(pre);
  for(let i=0;i<fixture.gps.length;i++) {
    const pos=pre.length+i*(tag.length+yuvSize);
    bytes.set(tag,pos);
    const frame=bytes.subarray(pos+tag.length,pos+tag.length+yuvSize);
    frame.fill(30,0,ySize); frame.fill(128,ySize);
    const g=fixture.gps[i],m=fixture.motion[4*i];
    function rect(x,y,w,h,luma) {
      for (let j=y;j<y+h;j++) frame.fill(luma,j*width+x,j*width+x+w);
    }
    // A dot on the track and two separate LED patches provide visible timing references.
    for(let j=0;j<180;j++) {
      const a=j*Math.PI/90;
      frame[(35+Math.round(18*Math.sin(a)))*width+47+Math.round(35*Math.cos(a))]=100;
    }
    rect(46+Math.round(g.x/106*35),34+Math.round(g.y/62*18),3,3,232);
    rect(6,4,10,6,fixture.present.includes('L')&&markerOn('L',g.time)?235:45);
    rect(80,4,10,6,fixture.present.includes('R')&&markerOn('R',g.time)?235:45);
    for(const [v,x] of [[m.left,4],[m.right,50]]) {
      if(v===null) {for(let k=0;k<32;k+=4)rect(x+k,62,2,5,90);}
      else {rect(x,62,Math.round(v/24*38),5,196);}
    }
  }
  return bytes;
}

export { makeFixture, testVideo, markerTimes, deviceUs };
