import { readFile, readdir, mkdir, mkdtemp, rename, writeFile } from 'node:fs/promises';
import { join, dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { createHash } from 'node:crypto';
import { recoverSession, describeSamples } from './kartpedal-v18-core.mjs';
import { makeFixture, testVideo, markerTimes, deviceUs } from './kartpedal-v18-fixture.mjs';
import { joinedCsv, lvzMembers, packFixtureZip, footCaptions } from './kartpedal-v18-adapters.mjs';
import { goldenHex } from './kartpedal-v18-golden.mjs';

const root = dirname(fileURLToPath(import.meta.url));
const utf8 = new TextDecoder('utf-8',{fatal:true});
const hexSha = b => createHash('sha256').update(b).digest('hex');
const json = obj => JSON.stringify(obj,(_,v)=>typeof v === 'bigint' ? v.toString() : v,2);
const print = value => console.log(json(value));

async function ingest(dir, emitRows) {
  const hashes = {};
  async function original(file) {
    const data=await readFile(join(dir,file));
    hashes[file]=hexSha(data);
    return data;
  }
  const entries=await readdir(dir,{withFileTypes:true});
  const names=entries.filter(e=>e.isFile() && /^imu_.*\.bin$/.test(e.name)).map(e=>e.name).sort();
  if(!names.length) throw new Error('No V18 IMU streams');
  const optional=async name=>{
    try{return await original(name);}
    catch(e){if(e.code!=='ENOENT')throw e;return new Uint8Array();}
  };
  const [metaBytes,journal,events,pairs]=await Promise.all([
    original('meta.json'),optional('blocks.jsonl'),optional('events.jsonl'),
    Promise.all(names.map(async name=>[name,await original(name)]))
  ]);
  const result=recoverSession({meta:JSON.parse(utf8.decode(metaBytes)),journal,events,
    streams:new Map(pairs)},b=>utf8.decode(b));
  for(const name of ['blocks.jsonl','events.jsonl']) if(!(name in hashes)) result.issues.push('missing '+name);
  const {results,committedEvents,...qc}=result;
  const streams=[];
  for(const [file,s] of results) {
    const flagCounts={estimatedTick:0,uncertainTime:0,clipping:0,gapBefore:0,fault:0,missingTick:0};
    for(const row of s.rows) Object.keys(flagCounts).forEach((k,bit)=>{if(row.flags & (1<<bit))flagCounts[k]++;});
    streams.push({file,header:s.header,committedRecords:s.rows.length,discardedBytes:s.discardedBytes,
      ...describeSamples(s.rows),
      firstUs:s.rows[0]?.tUs,lastUs:s.rows[s.rows.length-1]?.tUs,flagCounts,error:s.error,
      ...(emitRows?{raw:s.rows}:{})});
  }
  print({...qc,sha256:hashes,streams,committedEventCount:committedEvents.length,
    ...(emitRows?{committedEvents}:{})});
  if(qc.issues.length || !qc.closeMatches || qc.discardedEventsBytes || streams.some(s=>s.discardedBytes)) process.exitCode=2;
}

async function fixtures() {
  // Create a fresh sibling of this module. Never overwrite or merge with original SD trees.
  const dir=await mkdtemp(join(root,'.kartpedal-synthetic-partial-'));
  const folder=join(dir,'golden');
  await mkdir(folder);
  const bytes=Buffer.from(goldenHex.replace(/\s/g,''),'hex');
  const config={accel_range_g:16,gyro_range_dps:2000,accel_odr_hz:100,gyro_odr_hz:100,
    filter:'synthetic',fifo:'header',raw_axes:['x','y','z']};
  const meta={schema:2,side:'R',device_id:'synthetic-R',boot_uuid:'00112233-4455-6677-8899-aabbccddeeff',
    start_us:0,firmware_sha256:'0'.repeat(64),power_mode:'USB_BENCH',calibration_id:null,
    config:{shoe:{...config,address:104},shin:{...config,address:105}}};
  const name='imu_shoe_e000000.bin';
  const block={type:'block',file:name,offset:48,count:2,length:60,crc32:2771538500,events_end:0};
  const f=makeFixture();
  const anchors=Object.fromEntries(Object.entries(markerTimes).map(([side,times])=>[side,times.map((t,i)=>({
    use:i===1?'withheld':'fit',logger_us:deviceUs(side,t),truth_s:t,first_lit_frame:Math.ceil(t*25)
  }))]));
  const files=[
    ['golden/meta.json',json(meta)],['golden/'+name,bytes],['golden/events.jsonl',''],
    ['golden/blocks.jsonl',JSON.stringify(block)+'\n'],['synthetic-merged.csv',joinedCsv(f)],
    ['synthetic-single-right.csv',joinedCsv(makeFixture('R'))], ['synthetic-foot-motion.srt',footCaptions(f)],
    ['synthetic-multirate.lvz',packFixtureZip(lvzMembers(f))],['synthetic-source.y4m',testVideo(f)],
    ['fixture-reference.json',json({source:f.provenance,laps:f.laps,anchors,
      frameRate:25,motionHz:100,gpsHz:25,leftGapSeconds:[19.6,20.2],
      binary:'Independent V18 two-record golden. Its example journal has no close entry.',
      merged:'Generated directly on a known source timeline. No real calibration, GPS alignment or video measurement.',
      video:'4:3 YUV4MPEG2 timing target, left and right LED patches in upper corners. Source PTS = frame/25.'})]
  ];
  for (const [relative,data] of files) await writeFile(join(dir,relative),data,{flag:'wx'});
  const finished=join(root,'kartpedal-synthetic-'+dir.slice(-6));
  await rename(dir,finished);
  print({dir:finished,files:files.map(([name,data])=>({name,sha256:hexSha(data)}))});
}

try {
  const [cmd,path]=process.argv.slice(2);
  if(cmd==='fixtures'&&!path) await fixtures();
  else if((cmd==='qc'||cmd==='decode')&&path) await ingest(resolve(path),cmd==='decode');
  else throw new Error('Usage: node kartpedal-v18-cli.mjs fixtures | qc SESSION_DIR | decode SESSION_DIR');
} catch(e) {console.error(e.message);process.exitCode=1;}
