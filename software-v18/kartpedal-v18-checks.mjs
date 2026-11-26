import { crc32, recoverSession, describeSamples } from './kartpedal-v18-core.mjs';
import { makeFixture, testVideo, markerTimes, deviceUs } from './kartpedal-v18-fixture.mjs';
import { joinedCsv, lvzMembers, packFixtureZip, footCaptions } from './kartpedal-v18-adapters.mjs';
import { fitClock } from './kartpedal-v18-clocks.mjs';
import { goldenHex as GOLD } from './kartpedal-v18-golden.mjs';
const viewOf = b => new DataView(b.buffer,b.byteOffset,b.byteLength);
{

const original = Uint8Array.from(GOLD.trim().split(/\s+/), h=>parseInt(h,16));
const encode = s => Uint8Array.from(encodeURIComponent(s).replace(/%([0-9A-F]{2})/g,(_,v)=>String.fromCharCode(parseInt(v,16))), c=>c.charCodeAt(0));
const decode = b => decodeURIComponent(Array.from(b,x=>'%'+x.toString(16).padStart(2,'0')).join(''));
const lines = (...objects) => encode(objects.map(obj=>JSON.stringify(obj)+'\n').join(''));
const append = (...buffers) => {
  const out = new Uint8Array(buffers.reduce((sum,b)=>sum+b.length,0));
  let off = 0;
  for(const b of buffers){out.set(b,off);off+=b.length;}
  return out;
};
const name = 'imu_shoe_e000000.bin', other = 'imu_shin_e000000.bin';
const cfg={accel_range_g:16,gyro_range_dps:2000,accel_odr_hz:100,gyro_odr_hz:100,
  fifo:'header',filter:'synthetic',raw_axes:['x','y','z']};
const meta={schema:2,side:'R',device_id:'synthetic-R',boot_uuid:'00112233-4455-6677-8899-aabbccddeeff',
  firmware_sha256:'0'.repeat(64),start_us:0,calibration_id:null,power_mode:'USB_BENCH',
  config:{shoe:{...cfg,address:104},shin:{...cfg,address:105}}};
const block={type:'block',file:name,offset:48,count:2,length:60,crc32:2771538500,events_end:0};
const close={type:'close',t_us:1030000,reason:'user',events_end:0,streams:[{file:name,end_offset:108,record_count:2}]};
function run({bytes=original, journal=lines(block), events=new Uint8Array(), metadata=meta, extra=[]}={}) {
  return recoverSession({meta:metadata,journal,events,streams:new Map([[name,bytes],...extra])},decode);
}
const state = session=>session.results.get(name);
function change(off,value,operation='setUint32',repair=false) {
  const bytes=original.slice(); viewOf(bytes)[operation](off,value,true);
  if(repair) viewOf(bytes).setUint32(44,crc32(bytes.subarray(0,44)),true);
  return bytes;
}
function committed(bytes) {return run({bytes,journal:lines({...block,crc32:crc32(bytes.subarray(48))})});}
function rejected(fn) {try{fn();return false;}catch{return true;}}
const tests=[];
function test(name,fn) { if(!fn()) throw new Error('FAIL '+name); tests.push(name); }

test('standard CRC vector',()=>crc32(encode('123456789'))===0xcbf43926);
test('golden header CRC',()=>original.length===108&&crc32(original.subarray(0,44))===0x4286723b);
test('golden payload CRC',()=>crc32(original.subarray(48))===0xa5325244);
test('golden both signed records and timestamps',()=>{
  const [a,b]=state(run()).rows;
  return a.seq===0 && a.tick24===256 && a.flags===1 && a.tUs===1010000n
    && a.raw.join() === '100,-200,300,-400,500,-600' && b.seq===1 && b.tick24===512
    && b.tUs===1020000n && b.raw.join() === '101,-201,301,-401,501,-601';
});
test('header corruption',()=>state(run({bytes:change(36,15)})).error==='header CRC');
test('payload byte flip',()=>state(run({bytes:change(66,77,'setUint8')})).rows.length===0);
test('one byte short',()=>state(run({bytes:original.slice(0,-1)})).rows.length===0);
test('no journal accepts zero',()=>state(run({journal:lines()})).rows.length===0);
test('trailing uncommitted bytes',()=>{const s=state(run({bytes:append(original,Uint8Array.of(1,2,3))}));return s.rows.length===2&&s.discardedBytes===3;});
test('short header',()=>state(run({bytes:original.slice(0,47)})).rows.length===0);
test('different boot',()=>state(run({metadata:{...meta,boot_uuid:'12342233-4455-6677-8899-aabbccddeeff'}})).error==='boot UUID mismatch');
test('bad side',()=>rejected(()=>run({metadata:{...meta,side:'?'}})));
test('missing power mode',()=>rejected(()=>run({metadata:{...meta,power_mode:undefined}})));
test('misidentified stream',()=>state(run({bytes:change(14,1,'setUint16',true)})).error==='stream or epoch identity');
test('reserved flag rejects whole committed block',()=>state(committed(change(106,64,'setUint16'))).rows.length===0);
test('missing tick requires flag',()=>state(committed(change(90,0xffffffff))).error==='tick field');
test('missing tick retained as null',()=>{const b=change(90,0xffffffff);viewOf(b).setUint16(106,34,true);return state(committed(b)).rows[1].tick24===null;});
test('unavailable flag with observed tick',()=>state(committed(change(106,32,'setUint16'))).error==='tick field');
test('time regression',()=>state(committed(change(78,1000n,'setBigUint64'))).rows.length===0);
test('undeclared sequence gap',()=>state(committed(change(86,8))).error==='undeclared sequence gap');
test('declared sequence gap retains original seq',()=>{const b=change(86,8);viewOf(b).setUint16(106,9,true);return state(committed(b)).rows[1].seq===8;});
test('independent 24-bit wrap retained',()=>{const b=change(60,0xffff80);viewOf(b).setUint32(90,128,true);return state(committed(b)).rows[1].tick24===128;});
const one={...block,count:1,length:30,crc32:crc32(original.subarray(48,78))};
const two={...one,offset:78,crc32:crc32(original.subarray(78))};
test('bad second block preserves first and ignores later block in same stream',()=>state(run({journal:lines(one,{...two,crc32:0},two)})).rows.length===1);
test('noncontiguous byte offset',()=>state(run({journal:lines(one,{...two,offset:79})})).rows.length===1);
test('torn journal halts global scan',()=>state(run({journal:append(lines(one),encode('{"x":'),lines(two))})).rows.length===1);
test('non-newline final commit ignored',()=>state(run({journal:lines(one,two).slice(0,-1)})).rows.length===1);
const note=lines({type:'annotation',t_us:1,note:'télémétrie'});
test('watermark cannot split UTF-8 JSONL',()=>state(run({events:note,journal:lines({...block,events_end:note.length-1})})).rows.length===0);
test('only committed events exposed',()=>{const q=run({events:append(note,note),journal:lines({...block,events_end:note.length})});return q.committedEvents.length===1&&q.discardedEventsBytes===note.length;});
test('missing close is explicit',()=>!run().closeRecordPresent&&run().issues.includes('no close record'));
test('valid close never proves unmount',()=>{const q=run({journal:lines(block,close)});return q.closeMatches&&q.physicalUnmount==='unknown';});
test('wrong close totals',()=>!run({journal:lines(block,{...close,streams:[]})}).closeMatches);
test('nonterminal close',()=>!run({journal:lines(block,close,block)}).closeMatches);
test('bad shoe does not invalidate shin',()=>{
  const b=change(14,1,'setUint16',true);
  const q=run({journal:lines({...block,crc32:0},{...block,file:other}),extra:[[other,b]]});
  return state(q).rows.length===0&&q.results.get(other).rows.length===2;
});
test('new epoch starts its own sequence and carries its identity',()=>{
  const epoch='imu_shoe_e000001.bin', b=change(16,1,'setUint32',true);
  const d=viewOf(b); d.setBigUint64(36,2000000n,true);d.setUint32(44,crc32(b.subarray(0,44)),true);
  d.setBigUint64(48,2010000n,true);d.setBigUint64(78,2020000n,true);
  const q=run({journal:lines(block,{...block,file:epoch,crc32:crc32(b.subarray(48))}),extra:[[epoch,b]]});
  return state(q).rows.length===2&&q.results.get(epoch).rows[0].seq===0&&q.results.get(epoch).header.epoch===1;
});
test('fault-close retains verified data and reports stop reason',()=>{
  const q=run({journal:lines(block,{...close,reason:'fault'})});
  return q.closeMatches && q.closeReason==='fault' && state(q).rows.length===2
    && q.issues.includes('logger stopped on fault');
});
test('per-epoch observed rate, max interval and known gaps',()=>{
  const rows=state(run()).rows;
  const q=describeSamples(rows);
  const gap=describeSamples([rows[0],{...rows[1],seq:4}]);
  return q.knownMissingFrames===0 && q.observedRateHz===100 && q.maxIntervalUs===10000n
    && gap.knownMissingFrames===3 && describeSamples([rows[0]]).observedRateHz===null;
});
console.log(tests.length+' decoder checks passed');

}
{

const checks=[];
function verify(label,condition){if(!condition)throw new Error(label);checks.push(label);}
const f=makeFixture(),single=makeFixture('R'),csv=joinedCsv(f).trimEnd().split('\n');
const archive=packFixtureZip(lvzMembers(f)),video=testVideo(f);
const ascii=b=>Array.from(b,v=>String.fromCharCode(v)).join('');
const v=viewOf(archive),u32=p=>v.getUint32(p,true),u16=p=>v.getUint16(p,true);
let dir=u32(archive.length-6);
verify('ZIP end, central directory length and count',u32(archive.length-22)===0x06054b50&&u16(archive.length-12)===3&&dir+u32(archive.length-10)===archive.length-22);
const members=new Map();
for(let j=0;j<3;j++){
  const nameLen=u16(dir+28),dataLen=u32(dir+24),name=ascii(archive.slice(dir+46,dir+46+nameLen));
  const local=u32(dir+42),begin=local+30+u16(local+26)+u16(local+28);
  const content=archive.subarray(begin,begin+dataLen);
  verify('ZIP CRC, headers and extent '+name,u32(dir)===0x02014b50&&u32(local)===0x04034b50&&u16(dir+10)===0&&u16(local+8)===0
    &&u32(local+18)===dataLen&&u32(local+22)===dataLen&&u32(dir+20)===dataLen
    &&u32(dir+16)===crc32(content)&&u32(local+14)===crc32(content)&&ascii(archive.subarray(local+30,begin))===name);
  members.set(name,ascii(content));dir+=46+nameLen+u16(dir+30)+u16(dir+32);
}
verify('ZIP full directory consumed',dir===archive.length-22);
const manifest=JSON.parse(members.get('lapviz.json'));
verify('LVZ native rates, units and explicit synthetic origin',manifest.version===3&&manifest.groups[0].channels[0].rate===25
  &&manifest.groups[1].channels[0].rate===100&&manifest.groups[1].channels[0].unit==='deg'
  &&manifest.session.description.includes('SYNTHETIC'));
verify('two declared lap starts and durations',JSON.stringify(manifest.timing[0].laps)===JSON.stringify([{number:1,start:0,duration:40},{number:2,start:40,duration:42}]));
const foot=members.get('samples/foot.csv').trimEnd().split('\n'),gps=members.get('samples/gps.csv').trimEnd().split('\n');
verify('LVZ every numeric value and validity bit at native rate',foot.length===8201&&gps.length===2051&&f.motion.every((m,i)=>{
  const n=foot[i+1].split(','); return +n[0]===m.time&&(n[1]===''?null:+n[1])===m.left&&+n[2]===m.right&&+n[3]===m.leftValid&&+n[4]===m.rightValid;
})&&f.gps.every((g,i)=>gps[i+1].split(',').every((s,j)=>+s===[g.time,g.lat,g.lon,g.speed,g.distance][j])));
verify('LVZ exact 600 ms blank interval',foot.slice(1).filter(row=>row.split(',')[1]==='').length===60);
verify('merged CSV all rows align and preserve model values',csv.length===2051&&f.gps.every((g,i)=>{
  const m=f.motion[4*i],expected=[g.time,g.lat,g.lon,g.speed,g.distance,g.lap,m.left,m.right,m.leftValid,m.rightValid];
  return csv[i+1].split(',').every((s,j)=>(s===''?null:+s)===expected[j]);
}));
verify('merged CSV documents 25 Hz resolution and 15 blank samples',+csv[2].split(',')[0]===0.04&&csv.slice(1).filter(r=>r.split(',')[6]==='').length===15);
verify('single-leg CSV never invents left side',joinedCsv(single).trimEnd().split('\n').slice(1).every(row=>{const c=row.split(',');return c[6]===''&&c[8]==='0';}));
const headerEnd=video.indexOf(10)+1, frameSpan=96*72*3/2+6;
verify('video header and 2050 complete frames',ascii(video.subarray(0,headerEnd))==='YUV4MPEG2 W96 H72 F25:1 Ip A1:1 C420jpeg\n'
  &&(video.length-headerEnd)/frameSpan===2050&&f.gps.every((_,i)=>ascii(video.subarray(headerEnd+i*frameSpan,headerEnd+i*frameSpan+6))==='FRAME\n'));
const pixel=(i,x,y)=>video[headerEnd+i*frameSpan+6+y*96+x];
function visibleRises(x) {
  const pts=[];for(let i=1;i<2050;i++)if(pixel(i,x,5)>200&&pixel(i-1,x,5)<100)pts.push(i/25);
  return pts;
}
const residuals={},visible={};
for(const [side,x] of [['L',7],['R',81]]){
  const pts=visibleRises(x);
  verify('video marker edge frames '+side,pts.length===3&&pts.every((p,i)=>p>=markerTimes[side][i]&&p-markerTimes[side][i]<0.04));
  const points=markerTimes[side].map((t,i)=>({deviceUs:deviceUs(side,t),pts:pts[i]}));
  const fit=fitClock(points[0],points[2]);
  residuals[side]=1000*(fit(points[1].deviceUs)-points[1].pts);
  visible[side]=pts;
  verify('withheld clock residual within one source frame '+side,Math.abs(residuals[side])<40);
  verify('outside clock anchors explicitly unavailable '+side,fit(points[0].deviceUs-1)===null&&fit(points[2].deviceUs+1)===null);
}
verify('missing endpoints disable fitted sync',fitClock(null,null)===null);
verify('invalid left-foot interval produces distinct hatch in frame payload',pixel(500,4,62)===90&&pixel(500,6,62)===30&&pixel(500,8,62)===90);
const captions=footCaptions(f).trim().split('\n\n');
verify('source-timed captions retain gap and right foot',captions.length===2050 &&
  captions[500].includes('00:00:20,000 --> 00:00:20,040') &&
  captions[500].includes('Left ankle unavailable') && captions[500].includes('Right ankle 0.9'));
const mismatchedGrid={...f, gps:[f.gps[0],{...f.gps[1],time:0.041},f.gps[10]],endSeconds:0.44};
verify('CSV exact-time join blanks unmatched readings',joinedCsv(mismatchedGrid).split('\n')[2].endsWith(',,,0,0'));
verify('caption stops before a long GPS gap',footCaptions(mismatchedGrid).includes('00:00:00,041 --> 00:00:00,081'));
verify('invalid clock input has no mapping',fitClock({pts:0,deviceUs:0},{pts:NaN,deviceUs:1})===null);
console.log(checks.length+' fixture and export checks passed', {residuals,visible});
}
