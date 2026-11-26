function crc32(bytes, initial = 0) {
  let value = initial ^ 0xffffffff;
  for (const byte of bytes) {
    value ^= byte;
    for (let bit = 0; bit < 8; bit++)
      value = (value >>> 1) ^ ((value & 1) ? 0xedb88320 : 0);
  }
  return (value ^ 0xffffffff) >>> 0;
}

function check(condition, reason) {
  if (!condition) throw new Error(reason);
}
const natural = value => Number.isSafeInteger(value) && value >= 0;
const viewOf = bytes => new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
const streamName = /^(imu_(shoe|shin)_e([0-9]{6,})\.bin)$/;

function decodeHeader(bytes, name, uuid) {
  check(bytes.length >= 48, 'short header');
  const view = viewOf(bytes);
  const match = streamName.exec(name);
  check(match && match[3] === String(Number(match[3])).padStart(6, '0'), 'stream filename');
  check([75,80,73,77,85,50,0,0].every((v,i) => v === bytes[i]), 'magic');
  check(view.getUint16(8,true) === 2 && view.getUint16(10,true) === 48
    && view.getUint16(12,true) === 30, 'unsupported layout');
  check(view.getUint32(44,true) === crc32(bytes.subarray(0,44)), 'header CRC');
  check(view.getUint16(14,true) === (match[2] === 'shoe' ? 0 : 1)
    && view.getUint32(16,true) === Number(match[3]), 'stream or epoch identity');
  const hex = Array.from(bytes.subarray(20,36), b => b.toString(16).padStart(2,'0')).join('');
  check(hex === uuid.replace(/-/g,'').toLowerCase(), 'boot UUID mismatch');
  return {stream:match[2], epoch:Number(match[3]), openUs:view.getBigUint64(36,true)};
}

function decodeBlock(bytes, previous) {
  const view = viewOf(bytes);
  const rows = [];
  for (let off = 0; off < bytes.length; off += 30) {
    const tUs = view.getBigUint64(off,true);
    const seq = view.getUint32(off+8,true);
    const tick = view.getUint32(off+12,true);
    const flags = view.getUint16(off+28,true);
    check(!(flags & ~63), 'reserved flags');
    check(tick === 0xffffffff ? Boolean(flags & 32) : tick <= 0xffffff && !(flags & 32), 'tick field');
    if (previous) {
      check(tUs > previous.tUs && seq > previous.seq, 'record order');
      check(seq === previous.seq + 1 || (flags & 8), 'undeclared sequence gap');
    } else {
      check(seq === 0 || (flags & 8), 'missing initial sequence');
    }
    const raw = Array.from({length:6}, (_,i) => view.getInt16(off+16+2*i,true));
    const row = {tUs, seq, tick24: tick === 0xffffffff ? null : tick, flags, raw};
    rows.push(row);
    previous = row;
  }
  return rows;
}

// Inputs are the original file bytes. The caller supplies a strict UTF-8 decoder.
// Errors in an individual data stream stop that stream. A broken journal stops all scanning.
function validateMeta(meta) {
  check(meta.schema === 2 && ['L','R'].includes(meta.side)
    && typeof meta.device_id === 'string' && meta.device_id.trim()
    && /^[\da-f]{8}(?:-[\da-f]{4}){3}-[\da-f]{12}$/i.test(meta.boot_uuid), 'session identity');
  check(/^[a-f0-9]{64}$/i.test(meta.firmware_sha256) && natural(meta.start_us)
    && ['USB_BENCH','WEARABLE_EXPECTED_USB_ABSENT'].includes(meta.power_mode)
    && (meta.calibration_id === null || typeof meta.calibration_id === 'string'), 'session metadata');
  for (const [name,address] of [['shoe',0x68],['shin',0x69]]) {
    const cfg = meta.config?.[name];
    check(cfg && cfg.address === address
      && ['accel_range_g','gyro_range_dps','accel_odr_hz','gyro_odr_hz'].every(k =>
        Number.isFinite(cfg[k]) && cfg[k] > 0), 'sensor config ' + name);
  }
}
function recoverSession({meta, streams, journal, events}, utf8) {
  validateMeta(meta);
  const results = new Map(), issues = [];
  for (const [name, bytes] of streams) {
    const state = {bytes, rows:[], end:0, error:null};
    try { state.header = decodeHeader(bytes,name,meta.boot_uuid); state.end = 48; }
    catch (error) { state.error = error.message; issues.push(name + ': ' + error.message); }
    results.set(name,state);
  }
  function* lines(bytes) {
    let start = 0;
    while (start < bytes.length) {
      const end = bytes.indexOf(10,start);
      check(end >= 0, 'unterminated JSONL');
      const entry = JSON.parse(utf8(bytes.subarray(start,end)));
      check(entry && typeof entry === 'object' && !Array.isArray(entry), 'invalid JSONL object');
      yield {entry, end:end+1};
      start = end+1;
    }
  }
  const eventEnds = new Set([0]), eventLines = [];
  try {
    for (const {entry,end} of lines(events)) {
      check(typeof entry.type === 'string' && natural(entry.t_us), 'invalid event');
      eventEnds.add(end);
      eventLines.push({entry,end});
    }
  } catch (error) { issues.push('events: ' + error.message); }
  let watermark = 0, closeRecordPresent = false, closeMatches = false, closeReason = null;
  try {
    for (const {entry:b} of lines(journal)) {
      check(!closeRecordPresent, 'journal data after close');
      if (b.type === 'close') {
        closeRecordPresent = true;
        const committed = Array.from(results).filter(([,s]) => s.rows.length);
        const seen = new Set();
        check(natural(b.t_us) && ['user','low_battery','fault'].includes(b.reason)
          && eventEnds.has(b.events_end) && b.events_end >= watermark
          && Array.isArray(b.streams), 'close fields');
        for (const item of b.streams) {
          const s = results.get(item.file);
          check(s && !s.error && !seen.has(item.file) && item.end_offset === s.end
            && item.record_count === s.rows.length, 'close stream totals');
          seen.add(item.file);
        }
        check(committed.every(([name]) => seen.has(name)), 'incomplete close inventory');
        closeReason = b.reason;
        watermark = b.events_end;
        closeMatches = !issues.some(message => message.startsWith('missing stream:'))
          && Array.from(results.values()).every(s => !s.error);
        continue;
      }
      check(b.type === 'block' && streamName.test(b.file), 'unknown journal entry');
      const s = results.get(b.file);
      if (!s) { issues.push('missing stream: ' + b.file); continue; }
      if (s.error) continue;
      try {
        check(b.offset === s.end && natural(b.count) && b.count > 0
          && natural(b.length) && b.length === 30*b.count
          && b.length <= s.bytes.length-s.end, 'block extent');
        check(eventEnds.has(b.events_end) && b.events_end >= watermark, 'event watermark');
        const payload = s.bytes.subarray(s.end,s.end+b.length);
        check(crc32(payload) === b.crc32, 'payload CRC');
        const rows = decodeBlock(payload,s.rows[s.rows.length-1]);
        for (const row of rows) s.rows.push(row);
        s.end += b.length;
        watermark = b.events_end;
      } catch (error) { s.error = error.message; issues.push(b.file + ': ' + error.message); }
    }
  } catch (error) { closeMatches = false; issues.push('journal: ' + error.message); }
  if (!closeRecordPresent) issues.push('no close record');
  if (closeReason === 'fault') issues.push('logger stopped on fault');
  for (const state of results.values()) state.discardedBytes = state.bytes.length-state.end;
  return {side:meta.side, deviceId:meta.device_id, bootUuid:meta.boot_uuid,
    config:meta.config, calibrationId:meta.calibration_id, powerMode:meta.power_mode,
    results, issues, closeRecordPresent, closeMatches, closeReason, physicalUnmount:'unknown',
    committedEvents:eventLines.filter(line => line.end <= watermark).map(line => line.entry),
    discardedEventsBytes:events.length-watermark, calibration:'unapplied', clock:'device-epoch only'};
}

// Per stream and epoch. Unknown-count gap events cannot be counted from sequence IDs.
function describeSamples(rows) {
  if (!rows.length) return { knownMissingFrames: null, observedRateHz: null, maxIntervalUs: null };
  const last = rows[rows.length - 1];
  let maxIntervalUs = null;
  for (let i = 1; i < rows.length; i++) {
    const interval = rows[i].tUs - rows[i - 1].tUs;
    if (maxIntervalUs === null || interval > maxIntervalUs) maxIntervalUs = interval;
  }
  return {
    knownMissingFrames: last.seq + 1 - rows.length,
    observedRateHz: rows.length > 1 ? (rows.length - 1) * 1e6 / Number(last.tUs - rows[0].tUs) : null,
    maxIntervalUs
  };
}

export { crc32, recoverSession, describeSamples };
export { validateMeta, decodeHeader, decodeBlock };
