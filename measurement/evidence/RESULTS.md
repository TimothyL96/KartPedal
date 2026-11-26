# KartPedal V18 software verification

This is the measurement-stage record. The [final pre-hardware verification](../../docs/TEST_RESULTS.md) includes the subsequent clean firmware builds, desktop demonstration, SD diagnostic correction and endurance rerun.

The main demonstration is [the final LVZ](../artifacts/final/KartPedal.lvz), [the edited video](../artifacts/final/review.mp4) and [the transparent ankle strip](../artifacts/final/ankle-strip.mov). The [Windows operating and arrival guide](../../OPERATING.md) covers the desktop application and board bring-up.

## Measurement

Each simulated mounting produced four independent six-axis streams. The simulator modelled the rotating kart, a fixed-pivot calibration, heel-supported ankle motion, segment acceleration, vibration, mounting rotation, quantization, gyro bias, oscillator drift and lost shoe samples. The SD trees contain packed V18 records and a CRC journal. Reference ankle angles live outside those trees. The estimator learns the hinge, bias and observable lever components from calibration observations. The exporter reads its angle, rate and quality outputs.

| Test across four simulated mountings | Observed |
|---|---|
| Driving cycles per side per mounting | 28 left and 31 right onset crossings inside the scored window |
| Ground-truth onset/return detection, including deliberately disrupted cycles | 96.36% left, 96.72% right |
| p95 absolute crossing-time error | 3.95–20.97 ms |
| Relative-angle RMSE | 0.022–0.112° |
| Largest instantaneous driving angle error | 0.182° |
| Largest absolute change in neutral bias across the scored window | 0.111° |
| Common-motion-only interval | Maximum excursion error 0.132°, zero confident events |
| Deliberate gap | Zero numeric angles inside either side's injected dropout; acquisition of a stable pose also masks subsequent samples |
| Extra confident driving events | Zero across all eight side/mount combinations |

Timing compares like-for-like synthetic angle threshold crossings. Dwell confirmation is retained separately. The four mountings share the same driving model, with new sensor orientation and noise. The last mounting was withheld from estimator changes. This tests repeatability in the model. Ground-truth timing against visible human movement, bracing, strap motion and performance on a real kart are physical gates. [All per-side scores and missed events](synthetic-accuracy.json)

The 144 s primary clip has 7,200 camera frames. The final LVZ preserves 14,400 rows on the 100 Hz estimated-motion grid and 3,520 independently timed GPS samples inside the GPS alignment window. LapViz Studio opened two laps of 37.997 s, compared them and displayed both ankle gauge channels locally. The reference reader and official manifest schema accepted the archive. Every LVZ angle equals the estimator's float32 output, including its missingness. Changing gyro bytes in a re-journalled test stream changed the result. An unreadable truth file alongside the SD recording did not affect processing. [Studio screenshot](studio-final-local.jpg) · [QC, sensor clock fits and source hashes](../artifacts/final/quality.json)

## Firmware and endurance

Both firmware images compile for `esp32:esp32:XIAO_ESP32S3_Plus` with Arduino ESP32 3.3.5 and the pinned Bosch driver. The compiled host test uses the production header, CRC, button classifier and FIFO parser. Its 108 output bytes match the V18 golden file exactly. The microcontroller also runs the codec check before recording. No board was connected or flashed. [Right build](../../firmware/build/R/build-info.json) · [Left build](../../firmware/build/L/build-info.json) · [Build log](../../firmware/compile-final.log)

The 13,500 s one-leg run processed 2,699,917 committed six-axis records and exported 1,350,000 rows. On this Windows machine wall time was 20.47 s including Node decode, Python estimation/JIT, source hashes and LVZ writing. Decode took 3.23 s and estimation took 7.85 s. Peak combined working set sampled every 100 ms was 143.2 MiB. The Python working set stabilized near 139 MiB after warm-up. Each sensor supplied 27,000 timing anchors across approximately 20 tick rollovers. [Benchmark and memory trace](../artifacts/benchmark-final/benchmark.json)

## RaceBox and video

The RaceBox importer ran on a genuine public vendor CSV containing 32,856 rows. Timestamps started at 2022-08-07 14:01:20.520 UTC, and all seven complete laps were checked against the vendor header durations. Only the synthetic RaceBox file was aligned to the synthetic outing. The import profile tested is extended custom CSV with UTC timestamps and explicitly selected speed units. [Public export provenance and hash](racebox-import.json) · [RaceBox export options](https://www.racebox.pro/info/session-export)

The signed-in LapViz web overlay editor accepted the public example's Steering Angle channel in its Channel widget. It exported a 1920×1080 RGBA still and a 55.48 s 1280×720, 25 fps VP9 WebM. Decoded frames at 0, 1 and 20 s contained both fully transparent and fully opaque pixels. The hosted importer advertised public lap times and a default-sharing change. The synthetic session stayed local, so rendering KartPedal's two custom foot channels together in the hosted editor remains unverified. [Native WebM](lapviz-public-channel.webm) · [Decoded frame](lapviz-native-frame.png) · [Encoder and alpha evidence](lapviz-video.json)

The KartPedal demo uses its compact local strip adapter for the two feet. FFmpeg composited the transparent strip onto the synthetic footage and applied five source-time cuts. All 465 edited frames decoded. All six visible LED rises matched the edit map within one frame. The source clip was indexed by decoded presentation times. The final hosted and local media have different data sources. The earlier Studio video-panel trial remains available in [the original integration evidence](../../software-v18/integration-evidence/RESULTS.md). The fresh Studio file picker for attaching the new synthetic MP4 did not open in the in-app browser. The final synthetic edit was rendered and checked locally with FFmpeg. An actual DJI/Resolve edit remains part of the real-outing gate. [Cut map](../artifacts/final/edit-map.json) · [Frame checks](video-check.json)

## Repeat the checks

Run these commands from the KartPedal folder after the firmware toolchain is available. The benchmark command needs a new destination directory; it preserves earlier runs.

~~~powershell
python -B firmware/build.py --side both
.\firmware\check_codec.cmd
python -B measurement/regression.py
python -B measurement/acceptance.py
python -B measurement/benchmark.py measurement/artifacts/endurance-final/job.json measurement/user-data/exports/endurance-repeat
~~~

The regression suite exercises original decoder/adapters, input corruption, epoch reset, missing side, independent clocks, native LVZ round-trip, all mountings, byte-identical raw generation, device-relative processing, calibration reuse, the real desktop process/export button, public RaceBox input, transparent media and the edited marker checks. VBO remains experimental because the earlier actual Studio round trip filled invalid angles with numeric values. [Regression output](regression-final.log)

All 15 stage tests passed. The legacy regression inside that run executed the original 36 decoder and 25 fixture/adapter checks. A clean rerun also reproduced both motion streams, both event files, the frame index and every final LVZ member byte-for-byte.

| Implementation | Source |
|---|---|
| Board operation, FIFO parsing, journal and shared codec | [Firmware sketch directory](../../firmware/KartPedal), [project-local build](../../firmware/build.py), [compiled host test](../../firmware/codec_test.cpp) |
| Synthetic raw generation, camera and independent GPS | [Rigid-body simulator](../raw_sim.py), [demonstration builder](../demo.py) |
| Shared V18 decode, clock fitting, calibration and motion | [Streaming verifier](../verify-stream.mjs), [estimator](../engine.py) |
| Session workflow and independent adapters | [Desktop interface](../app.py), [pipeline](../pipeline.py), [RaceBox](../racebox.py), [video PTS](../video.py), [LED detection](../markers.py), [LVZ](../export_lvz.py), [transparent strip](../overlay.py) |
| Executed checks | [Regression suite](../regression.py), [accuracy scoring](../acceptance.py), [endurance benchmark](../benchmark.py) |

