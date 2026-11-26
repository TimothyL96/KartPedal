import { crc32 } from './kartpedal-v18-core.mjs';

const utf8 = new TextEncoder();

// The caller supplies one aligned session. Match source timestamps exactly on the
// chosen export grid. Interpolation and clock estimation belong upstream.
function* gpsGrid(session) {
  const motionByTime = new Map(session.motion.map(row => [row.time, row]));
  for (const gps of session.gps) {
    const motion = motionByTime.get(gps.time);
    yield { gps, left: angle(motion, 'left'), right: angle(motion, 'right') };
  }
}

function angle(row, side) {
  return row?.[side + 'Valid'] && Number.isFinite(row[side]) ? row[side] : null;
}

export function joinedCsv(session) {
  const rows = [['Time','Latitude','Longitude','GPS Speed','Distance','Lap',
    'Left Ankle Excursion (deg)','Right Ankle Excursion (deg)','Left Valid','Right Valid'].join(',')];
  for (const {gps, left, right} of gpsGrid(session)) {
    rows.push([gps.time, gps.lat, gps.lon, gps.speed, gps.distance, gps.lap,
      left, right, Number(left !== null), Number(right !== null)].join(','));
  }
  return rows.join('\n') + '\n';
}

function cueTime(seconds) {
  const ms = Math.round(seconds * 1000);
  const two = n => String(n).padStart(2,'0');
  return two(Math.floor(ms / 3600000)) + ':' + two(Math.floor(ms / 60000) % 60) +
    ':' + two(Math.floor(ms / 1000) % 60) + ',' + String(ms % 1000).padStart(3,'0');
}

// Captions use source time and stop after one export interval, even across a GPS gap.
export function footCaptions(session) {
  const cues = [];
  const display = value => value === null ? 'unavailable' : value.toFixed(1) + '°';
  for (const {gps, left, right} of gpsGrid(session)) {
    const next = session.gps[cues.length + 1]?.time ?? session.endSeconds;
    const end = Math.min(next, gps.time + 1 / session.gpsHz, session.endSeconds);
    if (!Number.isFinite(end) || end <= gps.time) throw new Error('Invalid caption bounds');
    cues.push([cues.length + 1, cueTime(gps.time) + ' --> ' + cueTime(end),
      (session.synthetic ? 'SYNTHETIC   |   ' : '') + 'Left ankle ' + display(left) +
        '   |   Right ankle ' + display(right)].join('\n'));
  }
  return cues.join('\n\n') + '\n';
}

// Native-rate groups preserve foot samples between GPS epochs.
export function lvzMembers(session) {
  const entries = new Map();
  function group(name, definitions, rows, rate, origin) {
    const file = 'samples/' + name + '.csv';
    const channels = definitions.map(([name, unit, , step]) => ({
      name, unit, rate, origin, ...(step ? {interpolation:'step'} : {})
    }));
    const csv = [['time', ...channels.map(c => c.name)].join(',')];
    for (const row of rows) {
      const values = definitions.map(([, , key]) => {
        if (key === 'left' || key === 'right') return angle(row, key);
        if (key === 'leftValid' || key === 'rightValid') return Number(angle(row, key.slice(0,-5)) !== null);
        return Number.isFinite(row[key]) ? row[key] : null;
      });
      csv.push([row.time, ...values].join(','));
    }
    entries.set(file, utf8.encode(csv.join('\n') + '\n'));
    return {name, channels, samples:{file, encoding:'csv', count:rows.length}};
  }
  const gps = group('gps', [
    ['Latitude','deg','lat'], ['Longitude','deg','lon'], ['GPS Speed','km/h','speed'], ['Distance','m','distance']
  ], session.gps, session.gpsHz, session.gpsOrigin);
  const foot = group('foot', [
    ['Left Ankle Excursion','deg','left'], ['Right Ankle Excursion','deg','right'],
    ['Left Valid','','leftValid',true], ['Right Valid','','rightValid',true]
  ], session.motion, session.motionHz, 'computed');
  const manifest = {format:'lapviz', version:3, generator:{name:session.generator},
    session:{start:session.start, clock:session.clock, description:session.provenance,
      properties:{sides:session.present}}, groups:[gps,foot], timing:session.timing};
  entries.set('lapviz.json', utf8.encode(JSON.stringify(manifest,null,2)));
  return entries;
}

// Minimal uncompressed ZIP32 writer limited to the three generated ASCII fixture entries.
export function packFixtureZip(entries) {
  const chunks=[],directory=[];
  let offset=0;
  function record(size,signature) {
    const b=new Uint8Array(size),v=new DataView(b.buffer);
    v.setUint32(0,signature,true);
    return {b,u16:(p,n)=>v.setUint16(p,n,true),u32:(p,n)=>v.setUint32(p,n,true)};
  }
  for(const [name,data] of entries) {
    const n=utf8.encode(name),crc=crc32(data);
    const local=record(30,0x04034b50);
    local.u16(4,20);local.u16(12,0x21);
    local.u32(14,crc);local.u32(18,data.length);local.u32(22,data.length);local.u16(26,n.length);
    chunks.push(local.b,n,data);
    const central=record(46,0x02014b50);
    central.u16(4,20);central.u16(6,20);central.u16(14,0x21);
    central.u32(16,crc);central.u32(20,data.length);central.u32(24,data.length);
    central.u16(28,n.length);central.u32(42,offset);
    directory.push(central.b,n);
    offset+=30+n.length+data.length;
  }
  const directoryLength=directory.reduce((n,c)=>n+c.length,0);
  const end=record(22,0x06054b50);
  end.u16(8,entries.size);end.u16(10,entries.size);
  end.u32(12,directoryLength);end.u32(16,offset);
  const result=new Uint8Array(offset+directoryLength+22);
  let p=0;
  for(const b of [...chunks,...directory,end.b]) {result.set(b,p);p+=b.length;}
  return result;
}
