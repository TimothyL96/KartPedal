# Integration results · 27 November 2026

This page preserves the first format trial. Later checks of the measurement engine, hosted public gauge export and local two-foot video are recorded in the [pre-hardware release results](../../docs/TEST_RESULTS.md).

**Use the original KartPedal LVZ for lap comparison.** LapViz Studio opened it locally, displayed the custom left and right ankle channels in degrees, and compared the 40.000 s and 42.000 s laps. Keep the original file for native-rate analysis. Studio’s own LVZ re-export reduced the foot channels from 100 Hz to 25 Hz.

## Application and format trials

The test used an isolated Edge 158.0.4370.33 profile. The public Studio page loaded before the browser went offline for file operations. The tests used the app’s file input, graph and lap controls, video drop target and export menu. The circuit is fictional. No account, session upload, cloud conversion or camera footage was used.

| Trial | Observed result |
|---|---|
| Original LVZ v3 | The official Python reference reader and the official manifest schema accepted separate groups of 8,200 foot rows and 2,050 GPS rows. Studio recognized both laps and units. At 19.7 s its cursor showed an unavailable left angle and validity 0 on lap 1, alongside 14.73° and validity 1 on lap 2. [Screenshot](studio-lvz-compare.png) |
| Studio to LVZ | Studio wrote LVZ v2 with one 2,050-row group. All GPS values, all four foot/validity values at the retained timestamps, and the lap starts and durations survived exactly. All 15 invalid left-foot rows on that grid remained missing. The export labelled the declared synthetic lap timing as device timing. [Returned LVZ](studio-exports/synthetic-multirate.lvz) |
| Studio to CSV | 2,050 rows. The invalid left cells stayed empty. Maximum absolute left-angle difference at valid retained ticks was below 0.00000005°. [Returned CSV](studio-exports/synthetic-multirate.csv) |
| Generic CSV to Studio | The two-foot and single-right imports opened. Studio treated the numeric Lap column as a channel and recognized zero lap boundaries for this track. The re-export preserved the gap and omitted the absent left channel in the single-leg session. [CSV import](studio-csv-import.png) · [Single-leg import](studio-single-import.png) |
| Studio to VBO and back | Both custom channel names survived. All 15 invalid rows acquired a numeric left angle of **10.866906°**, with Left Valid still 0. The angle survived VBO re-import, and Studio recognized zero laps. A consumer must honor validity before using this route. [Returned VBO](studio-exports/synthetic-multirate.vbo) · [Re-imported data](studio-vbo-reimport/synthetic-multirate.csv) |
| LapViz Delimited Data v1 | The published legacy example opened and displayed its 1:13.863 lap. The example has one GPS sample and no custom foot channel. The published specification reserves v1 for reading. [Example](lapviz-legacy-spec-example.txt) · [Screenshot](studio-legacy-spec.png) · [Specification](https://github.com/lapviz/LapViz.Telemetry/blob/0e2755dc303a0ae8245e122f759a0a3ba16acd66/docs/lapviz-format.md#62-version-1-legacy) |
| Studio video | Dropping the H.264 file onto the video panel opened the full 82 s source. The telemetry file input rejected the MP4 offline. The panel reported manual sync. Aligning player 19.9 s with cursor 19.7 s set an offset of −0.2 s. Matching them restored zero. Studio’s subtitle export returned `NoElements` for this session. |

The [fidelity measurements](fidelity.json) identify the Studio assembly, pinned reference-reader revision, channel comparisons and gap values. The [published reference reader](https://github.com/lapviz/LapViz.Telemetry/blob/0e2755dc303a0ae8245e122f759a0a3ba16acd66/tools/python/lvz.py) ran using the existing Python interpreter. The Studio bundle loaded its LapViz.Telemetry assembly. A separate .NET SDK/library integration was not exercised.

## Source-timed overlay

KartPedal’s SRT adapter labels each foot in degrees and emits “unavailable” during the deliberate gap. FFmpeg 4.2.2 burned those captions onto the output canvas, then trimmed four windows from the 4:3 source and concatenated them. The 16:9 sample preserves the whole synthetic image so its marker patches remain visible. OpenCV decoded all 250 frames of the resulting ten-second video. All six marker rises mapped back to the expected source frames. At edited time 4.00 s, source time 20.00 s, the caption shows left unavailable and right 0.9°.

[Review MP4](foot-motion-overlay-review.mp4) · [Rendered gap frame](rendered-gap.png) · [Exact filter, cut map and frame checks](overlay-verification.json)

## Scope and next gate

For this fixture the LVZ workflow took one local import, selecting the second lap and adding the second foot chart. Generic CSV required reconstructing lap timing before a comparable workflow could proceed. VBO requires explicit masking of numeric values during gaps. The CLI and caption generation are repeatable without an account. The graphical controls and Studio export behavior are version-dependent, so retain the original input and repeat the checks after an application update. Operator time and long-term maintenance cost have not been measured.

RaceChrono had no reachable mobile test session. DaVinci Resolve 21.2.0.6 was installed and closed, and its scripting API reported no running session. An actual Resolve import/edit/render and a finished overlay from LapViz’s dedicated video-overlay product remain untested. The review MP4 was rendered by FFmpeg. No real IMU calibration, RaceBox alignment, DJI timing, firmware or hardware gate was exercised.
