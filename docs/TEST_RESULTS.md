# ✅ Pre-hardware release results

**27 November 2026 · Windows.** The release passed its software checks using synthetic SD recordings. The components are still in delivery. The next qualification run starts with one bare controller on USB.

The public-release pass covers 17 regression tests. New cases exercise a torn event tail and closed logs with missing or empty sensor streams. The desktop test switches between logger and camera timelines, processes both, and compares every camera-aligned LVZ member with the reference.

| Release check | Observed result |
|---|---|
| Fresh desktop environment and normal launch | Installed the project Python requirements into a fresh local environment. Launched **Start KartPedal.cmd**, clicked **Load synthetic demo** and **Process and export LVZ**, and saw **LVZ ready**. [Inputs](images/desktop-inputs.jpg) · [Quality](images/desktop-quality.jpg) |
| Native LVZ | The GUI, CLI and reference outputs had identical content in every archive member. 14,400 foot rows at 100 Hz, 3,520 GPS rows at their own rate, two laps. Both motion files, event files and frame index also matched. [Integration evidence](../measurement/evidence/release-integration.json) |
| Reproducible firmware | Two clean builds per side on this Windows path and toolchain. Application, bootloader, partitions and merged flash image all matched their same-side counterparts. L and R have distinct applications. Arduino CLI 1.2.2, ESP32 3.3.5 and pinned Bosch SensorAPI. [First hashes](../firmware/build/clean-1.sha256) · [Second hashes](../firmware/build/clean-2.sha256) |
| Firmware contract and pin review | The compiled host codec reproduced the 108-byte original golden fixture byte-for-byte. Host tests covered the FIFO parser, button classification and cached SD diagnostic success/failure. Replays performed one probe per boot. Source pin assignments matched the V18 wiring table. [Host test](../firmware/codec_test.cpp) · [Wiring](HARDWARE_FIRST_TEST.md) |
| Regression | 15/15 stage tests passed, including the 36 original decoder checks and 25 fixture/adapter checks. Exercised corruption, reset epochs, changed gyro bytes, missing side, profile reuse, independent clocks, GUI errors, native LVZ and video. [Executed suite](../measurement/evidence/release-regression.log) |
| Exported video | Re-rendered the full strip and five-cut review. Compared every decoded frame against the supplied media. All 7,200 RGBA strip frames and 465 RGB edit frames matched. Alpha spanned 0–255. Six LED rises agreed with the edit map within one 50 fps frame. [Frame evidence](../measurement/evidence/video-check.json) |
| Endurance workload | 3 h 45 min synthetic, one logger, two sensors, 2,699,917 records → 1,350,000 foot rows. This release run took **21.37 s**, with **147.4 MiB** peak sampled combined process memory. Decoder 3.04 s, estimation 8.04 s. This measures PC processing. [Benchmark and memory trace](../measurement/user-data/exports/release-endurance/benchmark.json) |
| Input preservation | SHA-256 matched before and after for all 22 checked source files, including the original V18 HTML, both demo SD trees, source video/GPS, golden fixture and genuine vendor CSV. [Fingerprints](../measurement/evidence/release-source-hashes.json) |

## Measurement results

Four synthetic mountings, including the held-out mounting, passed on both sides. Deliberately interrupted cycles count as misses. Event timing compares estimated crossings to the corresponding synthetic crossings.

| Metric | V18 target | Across the eight side/mount cases |
|---|---|---|
| Detection | ≥95%, ≥20 cycles per side | Left 96.36%, right 96.72%, 28–31 onset cycles per side per mounting |
| p95 event timing error | ≤50 ms | 3.95–20.97 ms |
| Angle error and neutral drift | Each <10% usable range | RMSE 0.022–0.112°, worst angle error 0.182°, largest absolute neutral drift 0.111° |
| Common movement | No confident relative event | Zero false events, maximum common-motion error 0.132° |
| Missing samples | Suppress invalid measurements | No numeric angle in the scored dropout, no extra confident driving events |

[Per-side scores and misses](../measurement/evidence/synthetic-accuracy.json) · [Worked plots](CALIBRATION_AND_SYNC.md)

## External applications and remaining gates

| Tested | Requires further evidence |
|---|---|
| Local Studio opened the estimated channels, compared two laps and displayed both gauges. | Studio re-export previously reduced their sampling rate. Retain the original LVZ. [Actual Studio screenshot](../measurement/evidence/studio-final-local.jpg) |
| Imported 32,856 genuine RaceBox CSV rows and checked seven lap durations. The synthetic outing separately exercised independent GPS alignment. | A real RaceBox/DJI outing with verified shared crossings is required to qualify that alignment on track. [Vendor import](../measurement/evidence/racebox-import.json) |
| LapViz’s hosted editor exported a transparent 55.48 s VP9 example with a public steering channel. The local KartPedal two-foot ProRes strip passed alpha and timing checks. | Hosted two-foot rendering remains unverified under the keep-off-rankings constraint. An actual Resolve import/edit/render is also unverified. Neither blocks local LVZ processing or strip generation. [Video evidence](LAPVIZ_AND_VIDEO.md) |
| Both flashable binaries compile and their shared codec runs on the host. | Board boot/flash, electrical safety, SD power and integrity, loaded battery behavior and stop deadlines, mounting/refit, real event accuracy and end-to-end edited practice all require physical evidence. [G0–G8](HARDWARE_FIRST_TEST.md) |

## Reproduce from PowerShell

Run from the project root after [desktop setup](QUICK_START.md). The compiler is already present here. On another Windows machine the first command provisions its pinned toolchain inside KartPedal. Host codec compilation uses the installed MSVC x64 C++ tools. The build commands do not upload.

~~~powershell
python -B firmware/build.py --provision
python -B firmware/build.py --side both --clean
.\firmware\check_codec.cmd
.\.venv\Scripts\python.exe -B measurement/regression.py
.\.venv\Scripts\python.exe -B measurement/acceptance.py
~~~

For the endurance repeat, select a fresh destination. Fresh destinations are required by the pipeline to protect earlier exports.

~~~powershell
$run = "measurement/user-data/exports/endurance-$(Get-Date -Format yyyyMMdd-HHmmss-fff)"
.\.venv\Scripts\python.exe -B measurement/benchmark.py measurement/artifacts/endurance-final/job.json $run
~~~

Windows installation, project-local compiler provisioning with the core already present, build, port listing, QC, processing, overlay rendering, accuracy and benchmark commands ran on this PC. Upload and serial diagnostics require a connected XIAO and were deliberately left for arrival. [Older integration evidence](../measurement/evidence/RESULTS.md) · [Home](../README.md)
