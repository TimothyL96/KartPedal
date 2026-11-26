import fs from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import { crc32, validateMeta, decodeBlock, decodeHeader } from '../software-v18/kartpedal-v18-core.mjs';

// One journal block is an atomic unit. Validate in bounded chunks, writing to private staging;
// on any error truncate back to the last verified prefix and stop that stream.
export async function verifySession(source, output) {
  const meta=JSON.parse(fs.readFileSync(path.join(source,'meta.json'),'utf8'));
  validateMeta(meta);
  fs.mkdirSync(output,{recursive:true});
  const states=new Map(), issues=[];
  const handles=[];
  const open=(p,m)=>{const h=fs.openSync(p,m);handles.push(h);return h;};
  const utf8=new TextDecoder('utf-8',{fatal:true});
  const eol=Buffer.from('\n');
  let eventsEnd=0, close=null, journal=null;
  function readExact(fd,n,off) {
    const buf=Buffer.allocUnsafe(n);
    if(fs.readSync(fd,buf,0,n,off)!==n) throw Error('short read');
    return buf;
  }
  try {
    const ev=open(path.join(source,'events.jsonl'),'r');
    const clean=open(path.join(output,'events.jsonl'),'wx');
    function commitEvents(end) {
      if(!Number.isSafeInteger(end)||end<eventsEnd||end>fs.fstatSync(ev).size) throw Error('event watermark');
      let pos=eventsEnd,tail=Buffer.alloc(0);
      while(pos<end) {
        const raw=readExact(ev,Math.min(65536,end-pos),pos);
        const joined=Buffer.concat([tail,raw]);let start=0,i;
        while((i=joined.indexOf(eol,start))>=0) {
          const e=JSON.parse(utf8.decode(joined.subarray(start,i)));
          if(typeof e.type!=='string'||!Number.isSafeInteger(e.t_us)||e.t_us<0) throw Error('event fields');
          start=i+1;
        }
        tail=joined.subarray(start);
        if(tail.length>65536) throw Error('oversize event');
        fs.writeSync(clean,raw,0,raw.length,pos);pos+=raw.length;
      }
      if(tail.length) throw Error('event ends inside line');
      eventsEnd=end;
    }
    for(const name of fs.readdirSync(source).filter(n=>/^imu_.*\.bin$/.test(n))) {
      const s={bytes:0,count:0,error:null};states.set(name,s);
      try {
        s.fd=open(path.join(source,name),'r');
        const h=readExact(s.fd,48,0);
        const identity=decodeHeader(h,name,meta.boot_uuid);
        Object.assign(s,{stream:identity.stream,epoch:identity.epoch,end:48});
        s.out=open(path.join(output,name),'wx');fs.writeSync(s.out,h);
      } catch(e){s.error=e.message;issues.push(name+': '+e.message);}
    }
    journal=fs.createReadStream(path.join(source,'blocks.jsonl'));
    // Keep the newline terminator: readline would also emit a torn last commit.
    let tail=Buffer.alloc(0);
    for await(const chunk of journal) {
      const buf=Buffer.concat([tail,chunk]);let start=0,i;
      while((i=buf.indexOf(eol,start))>=0) {
        const b=JSON.parse(utf8.decode(buf.subarray(start,i)));start=i+1;
        if(close) throw Error('records after close');
        if(b.type==='close') {
          if(!Number.isSafeInteger(b.t_us)||b.t_us<0||!['user','fault','low_battery'].includes(b.reason)||!Array.isArray(b.streams)) throw Error('invalid close');
          const seen=new Set();
          for(const v of b.streams) {
            const s=states.get(v.file);
            if(!s||seen.has(v.file)||s.error||v.end_offset!==s.end||v.record_count!==s.count) throw Error('close totals');
            seen.add(v.file);
          }
          if([...states].some(([n,s])=>s.count&&!seen.has(n)))throw Error('close inventory');
          commitEvents(b.events_end);close=b;continue;
        }
        if(b.type!=='block'||!states.has(b.file))throw Error('unknown stream or record');
        const s=states.get(b.file);if(s.error)continue;
        try {
          if(!Number.isSafeInteger(b.count)||b.count<=0||b.length!==30*b.count||b.offset!==s.end||
            !Number.isSafeInteger(b.offset+b.length)||b.offset+b.length>fs.fstatSync(s.fd).size)throw Error('block extent');
          // CRC over the full committed block, not over individually accepted records.
          let crc=0,prev=s.prev,first=s.firstUs,lost=s.lost??0,clipped=s.clipped??0,uncertain=s.uncertain??0;
          for(let k=0;k<b.count;k+=1024) {
            const off=s.end+k*30, data=readExact(s.fd,Math.min(1024,b.count-k)*30,off);
            crc=crc32(data,crc);const rows=decodeBlock(data,prev);
            for(const r of rows){
              first??=Number(r.tUs);lost+=r.seq-(prev?prev.seq+1:0);
              if(r.flags&4)clipped++;if(r.flags&50)uncertain++;prev=r;
            }
            fs.writeSync(s.out,data,0,data.length,off);
          }
          if(crc!==b.crc32)throw Error('payload CRC');
          commitEvents(b.events_end);s.end+=b.length;s.count+=b.count;
          Object.assign(s,{prev,firstUs:first,lost,clipped,uncertain});
        } catch(e){s.error=e.message;issues.push(b.file+': '+e.message);fs.ftruncateSync(s.out,s.end);fs.ftruncateSync(clean,eventsEnd);}
      }
      tail=buf.subarray(start);if(tail.length>1048576)throw Error('oversize journal line');
    }
    if(tail.length)throw Error('torn journal');
    if(!close)throw Error('no close record');
    if(close.reason==='fault')issues.push('logger fault close');
    if(fs.fstatSync(ev).size!==eventsEnd)issues.push('uncommitted events tail');
    for (const [n,s] of states) if(s.fd!==undefined&&s.end!==fs.fstatSync(s.fd).size) issues.push(n+': discarded tail');
  } catch(e){issues.push(e.message);}
  finally {journal?.destroy();for(const h of handles)fs.closeSync(h);}
  const report={issues,closeReason:close?.reason??null,physicalUnmount:'unknown',
    streams:[...states].map(([file,s])=>({file,stream:s.stream,epoch:s.epoch,count:s.count,error:s.error,
      first_us:s.firstUs??null,last_us:s.prev?Number(s.prev.tUs):null,known_lost:s.lost??0,clipped:s.clipped??0,
      uncertain:s.uncertain??0,observed_hz:s.count>1?(s.count-1)*1e6/(Number(s.prev.tUs)-s.firstUs):null,
      known_fresh_fraction:s.count?s.count/(s.count+s.lost):null}))};
  fs.writeFileSync(path.join(output,'meta.json'),JSON.stringify(meta));
  fs.writeFileSync(path.join(output,'qc.json'),JSON.stringify(report,null,2));
  return report;
}
if(process.argv[1] && fileURLToPath(import.meta.url)===path.resolve(process.argv[1])) {
  const report=await verifySession(process.argv[2],process.argv[3]);
  console.log(JSON.stringify(report)); if(report.issues.length)process.exitCode=2;
}
