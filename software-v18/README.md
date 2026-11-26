# KartPedal V18 software slice

**Archived first integration experiment.** The table and commands below refer to this original test harness. For the current raw measurement engine, endurance-tested streaming decoder, compiled firmware and Windows workflow, start at the [project home](../README.md) or [release results](../docs/TEST_RESULTS.md).

The decoder reads a local V18 schema-v2 session directory. It validates headers, stream and boot identity, journal commits, event byte watermarks, payload CRCs, record ordering and flags. Recovery stops at the last verified contiguous block of each stream. A malformed journal line stops the global scan. Source files are opened read-only.

From the KartPedal folder, using Node.js (tested with v24.22.3):

```powershell
node software-v18/kartpedal-v18-checks.mjs
node software-v18/kartpedal-v18-cli.mjs qc software-v18/synthetic-two-laps/golden
node software-v18/kartpedal-v18-cli.mjs decode software-v18/synthetic-two-laps/golden
node software-v18/kartpedal-v18-cli.mjs fixtures
```

`qc` prints JSON with hashes of the input files it reads, record and flag counts, known sequence loss, observed rate, largest interval, discarded bytes and close status. `decode` also prints the signed raw axes and committed events. Both preserve 64-bit MCU microseconds as decimal strings. Exit 1 indicates an input or execution error. Exit 2 requests integrity review. The supplied golden example intentionally returns 2: both records verify, but the example journal has no terminal close. A matching close entry cannot establish physical unmount or measurement quality.

`fixtures` publishes a fresh synthetic directory under `software-v18`. It produces the golden input tree, merged and single-right-leg CSVs, a native-rate LVZ, source-time SRT captions, a YUV4MPEG2 video and its timing reference. It needs no package installation. The supplied [fixture directory](synthetic-two-laps/) also contains an H.264 copy made with the existing FFmpeg binary for the browser trials.

| Boundary | Source and scope |
|---|---|
| Acquisition and integrity | [Core](kartpedal-v18-core.mjs) decodes independent sensor epochs. Output stays in raw counts and device time. Faults, gaps and uncertain timing remain visible. The current decoder reads a session into memory. Endurance-sized logs have not been qualified. |
| Calibration | No estimator is applied. The [fixture](kartpedal-v18-fixture.mjs) generates a separate synthetic reference for ankle excursion and GPS. It is independent of the two-record binary example. |
| Synchronization | [Clock fitting](kartpedal-v18-clocks.mjs) maps two device-time anchors to source presentation time within their observed range. Synthetic tests withhold the middle light edge. A real sensor-to-MCU fit, clip split and independent RaceBox alignment still need evidence. |
| Export | [Adapters](kartpedal-v18-adapters.mjs) write native-rate LVZ groups, generic CSV on the GPS grid and source-timed captions. The CSV and caption paths join aligned samples by exact timestamp and leave unavailable motion blank or labelled. |

The [integration results](integration-evidence/RESULTS.md) record real Studio imports, lap comparison, exports, round-trip data loss and an inspected synthetic video edit. All hardware and measurement acceptance gates remain open.
