# Troubleshooting

Start at the first unexpected result. Preserve the original files and the exact error. Re-run processing in a fresh export directory.

## Bench

| Symptom | Action and expected recovery |
|---|---|
| No port, wrong side, or wrong LED pattern | Bare XIAO, known USB **data** cable. Compare port lists unplugged/plugged and confirm the Plus board. Close another serial monitor if it owns the port. Cold-start with BOOT released, then hold it during grace. `STATUS` must identify the labelled side. |
| Sensor missing or both appear at one address | Power down. Inspect 3V3/GND, SDA/SCL mapping, pull-ups, CS mode and local SDO straps. Test the shoe alone first. Do not force a hard-strapped pad to the opposite rail. |
| SD FAIL repeats | The message is cached until cold power-on. Power off, inspect FAT32, short SPI leads, CS, cap polarity and the 3.3 V rail. Try a known-good card and cold-start again. Verify both physical adapter/card pairs before changing hardware selection. |
| Resets during writes or triple-flash close | Stop off-body, preserve the full card tree and log the state. Check power under load, cable flex, queue and SD stalls. A meter can miss transient droop. Keep battery tests gated on reliable combined USB operation. |
| Heat, damaged cell, unknown polarity or a snag | Isolate power and stop the physical trial. Resolve the cell ratings, wiring or mechanical interference before advancing. [Bench sequence and gates](HARDWARE_FIRST_TEST.md) |

## Desktop and recordings

| Symptom | What the implemented workflow can recover |
|---|---|
| Launcher exits or a module is missing | Run the Python/Tk and Node checks in [Quick start](QUICK_START.md). Install the listed requirements into the project environment and reopen the launcher. |
| Folder rejected or side mismatch | On the correct foot tab choose the boot directory containing `meta.json`, `blocks.jsonl` and the streams. Check device ID and side. Preserve the recorded metadata. |
| Interrupted SD file or missing close | Select the copied boot folder even if the LED preview cannot read the events. Run **Check SD integrity before calibration**. The decoder reports verified records and flags damaged or uncommitted tails. The measurement pipeline stops on integrity errors. A healthy opposite leg can be processed separately. |
| Only one foot recorded | Start **New session**, select just the healthy foot and calibrate it. With its three filmed markers it can still align to the clip. The missing side has no LVZ channels. Both-foot overlap is unavailable. |
| Forgot a marker or the LED detector found too few pulses | Check the LED rectangle and recorded IDs. Inspect the original frames. If the requisite pulses are visible, turn off automatic detection and enter their true times. Camera alignment requires two fit anchors and an interior check. Without them, select **Single logger only**, keep one SD folder with **Clear**, and use logger-second calibration. The app omits the camera and GPS anchors from that export. Repeat separately for a second foot. |
| DJI split the outing | Process one original clip at a time. Use only observed markers and GPS crossings for that clip. Choose the filmed subset of IDs. A clip without sufficient independent evidence has no accepted camera-aligned export. Filenames and nominal frame counts cannot recover the missing references. |
| Missing RaceBox / UTC or units error | Omit RaceBox and export camera-aligned foot data alone. For a readable CSV with no crossing pairs, clear GPS anchors to keep GPS separate. For a malformed CSV, re-export supported UTC custom CSV or remove it. No GPS-derived speed, distance or lap comparison is available without aligned data. |
| Neutral, hinge or profile rejected | Review the filmed neutral and positive-direction windows, time units and side. Secure the mount and recalibrate after a refit. Select fresh still data when reusing a profile. |
| Blank angle, or a zero validity channel | Inspect the quality code, CRC/sequence history and clock bounds. Wait for valid pose reacquisition. Leave the hole visible and exclude it from coaching comparisons. Zero angle with validity **1** is a real near-neutral result. |
| Video strip black or drifting after a cut | Check that you imported the full-length ProRes MOV on V2, above the matching full-length source, with alpha enabled. Inspect Resolve’s clip alpha interpretation and input scaling. Check first-frame alignment and speed. Reapply the same cuts to both layers from source time and test a rendered excerpt. |
| Output already exists | Choose a fresh path. The GUI timestamps each completed run. **Open settings** can reopen the previous run without rewriting its original inputs. |

### Inspect a card before calibration

This recovery command reads the supplied right session. Replace the last argument with the **copied** physical boot directory when available. Exit 0 means its journal scan succeeded. Exit 2 requests review, and exit 1 indicates an input or execution error. Use the desktop integrity check for the first-leg bench gate. It also requires committed samples from both the shoe and shin.

~~~powershell
node software-v18/kartpedal-v18-cli.mjs qc measurement/artifacts/outing/R
~~~

Save the console output, wiring photo, board/side, exact filenames and state of the terminal LED. A valid close journal record cannot establish successful physical unmount. [Telemetry and video guide](LAPVIZ_AND_VIDEO.md) · [Home](../README.md)
