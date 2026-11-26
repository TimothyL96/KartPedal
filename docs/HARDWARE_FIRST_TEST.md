# 🔧 First leg on the bench

**First success:** the bare XIAO reports its intended side and `golden PASS` over USB, and its 3V3 rail measures about 3.3 V. Set the second leg and both cells aside. Gates below are targets for the delivered parts. No physical gate has passed.

## 1 · Receive and prepare (G0)

- [ ] Photograph labels and both faces. Set out one **XIAO ESP32-S3 Plus**, two BMI270 breakouts, one mini **3.3 V SPI** SD adapter, one 32 GB SDHC card and a data-capable USB-C cable. Identify the shoe and shin boards.
- [ ] Check the protected **703048** pack, marking, connector, protection and operating limits against the delivered item. The listing photo shows a different variant. A 2 mm pitch alone cannot identify the pinout or plug family. Keep it disconnected.
- [ ] Set the iron in its stand on a heat-resistant bench with good light, ventilation and eye protection. Practice on scrap wire. Solder with all power removed, inspect for bridges and strain-relieve the wires. Wash hands after using leaded solder. Never solder to the cell.
- [ ] On the HABOTEST, put black in **COM**, red in **V/Ω**. With power disconnected, use continuity to test the probes, map all four connector paths and check adjacent pads for shorts. A capacitor can cause a momentary beep. Investigate a sustained near-zero reading.
- [ ] For powered voltage measurements, select **DC V**, 20 V if manual. Black goes to GND, red to the labelled rail. Keep the red lead out of the current sockets. Never measure current across a rail or battery. Disconnect before moving wiring.
- [ ] Back up the intended cards. Verify full capacity by write/read on the PC, then FAT32 and readback. Check which drive is selected before formatting. The adapter seller’s ≤2 GB claim remains an open question until the selected cards pass.

The owner's local copy of `KartPedal_Master_Engineering_Report_V18_2026-11-26.html` includes the original connector drawings, soldering examples and purchase evidence.

## 2 · Flash one bare controller over USB

Choose the side that fits best. If both fit equally, V18 suggests starting on the right. Label the board and keep that identity through processing.

| Device | Complete flash directory for the CLI | Compiled application |
|---|---|---|
| Left / brake foot | [firmware/build/L](../firmware/build/L/) | [Left .bin](../firmware/build/L/KartPedal.ino.bin) |
| Right / throttle foot | [firmware/build/R](../firmware/build/R/) | [Right .bin](../firmware/build/R/KartPedal.ino.bin) |

Use the full side directory in the upload command so the uploader gets the application, bootloader and partitions. The small application binary alone is insufficient for a blank board. [Build instructions and hashes](TEST_RESULTS.md)

From PowerShell in KartPedal, with no battery or peripherals attached, list ports once unplugged and again after connecting the board. Choose the port that actually appeared. After delivery only, enter that port and the labelled side when prompted below.

On a fresh checkout, run `python -B firmware/build.py --provision` first to download the local Arduino CLI and its board tools.

~~~powershell
$cli = ".\firmware\.tools\arduino-cli.exe"
$cfg = ".\firmware\.tools\config.json"
& $cli --config-file $cfg board list
~~~

~~~powershell
$port = Read-Host "New XIAO port, e.g. COM7"
$side = Read-Host "Labelled foot, L or R"
if ($side -notin 'L','R') { throw "Choose L or R" }
& $cli --config-file $cfg upload --fqbn esp32:esp32:XIAO_ESP32S3_Plus --port $port --input-dir ".\firmware\build\$side" --verify .\firmware\KartPedal
~~~

Expect the CLI to verify the upload. Cold-start by unplugging and reconnecting USB with BOOT released. During the first **8 seconds**, hold **BOOT for 2 seconds**. Two flashes followed by a pause indicate maintenance. Open the port at 115200 and send each command as a line with Enter. If the port changed, list it again. [Seeed flashing recovery](https://wiki.seeedstudio.com/xiao_esp32s3_getting_started/)

~~~powershell
& $cli --config-file $cfg monitor --port $port --config baudrate=115200
~~~

Send `STATUS`. Expect `MAINTENANCE side L` or `R` and `golden PASS`. Measure the USB-powered 3V3 rail. The reported divider voltage during USB operation cannot establish cell presence. **Stop** for wrong side, sustained short, heat, resets or unstable rail.

## 3 · Wire one step at a time (G1)

Unplug USB before each change. Match actual pad labels and breakout straps. The shoe connector carries only **3V3, GND, SDA and SCL**. Record cavity order on both halves.

| XIAO pad | Connection |
|---|---|
| 3V3, GND | Both BMI270s and SD adapter. Common local return. |
| D4 / GPIO5, D5 / GPIO6 | SDA, SCL to both sensors. Bus starts at 100 kHz. |
| Shoe / shin address | Shoe SDO low → 0x68. Shin SDO high → 0x69. CS high for I²C **only after** checking actual breakout straps. |
| D8 / GPIO7, D9 / GPIO8, D10 / GPIO9 | SD SCK, MISO/DO, MOSI/DI respectively. Short local leads. |
| D3 / GPIO4 | SD CS. Place 100 µF across the SD supply, positive to 3V3, striped negative to GND. |
| BOOT / GPIO0, LED / GPIO21 | Existing controls, active-low LED. Leave accessible. |
| D0 / GPIO1 | Battery-divider midpoint only. Add during G3. |

1. **Shoe only.** Connect 0x68, power by USB, enter maintenance and send `PROBE_SHOE`. Expect ID **0x24** and 20 readings. At rest acceleration magnitude is about 1 g and gyro near zero. Move it gently and watch the axes change.
2. **Add shin.** Unplug, wire 0x69, repeat with `PROBE_BOTH`. Expect both addresses with ID **0x24**. Move one sensor at a time. Stop for missing IDs, repeated read failures or indistinguishable sensors.
3. **Add SD last.** Insert the FAT32 card while off. Cold-start maintenance and send `CHECK_SD`. Expect `SD PASS (this boot)`, repeated about every **5 seconds**. The first request writes, syncs, reopens and verifies one newly named `KP_SMOKE_….TXT`. Repeated prints and commands reuse that result, including a failure. Power down before removing the card. On the PC, confirm the file contains exactly `KARTPEDAL-V18-SD-OK`. To test again after a correction, cold-start with the intended card.

## 4 · Prove combined capture (G2)

With the battery still isolated, enter USB maintenance and send `BENCH_RECORD`. Look for the short heartbeat every 2 seconds. Record at least **30 minutes** with both IMUs and SD, flexing the final ankle cable through its intended range. Film some short-press markers. Hold BOOT ≥2 seconds to stop.

| Terminal indication | What to do |
|---|---|
| Steady LED, **SAFE_OFF** | Successful drain, sync, close and unmount. Disconnect USB before card removal. |
| Three flashes and a pause, **ERROR_STOPPED** | Power off and preserve the entire card tree. A partial recording is possible. |
| Still stopping or ambiguous | Keep the unit stationary and off-body. The required deadline is 10 seconds. Treat failure to reach an identifiable terminal state as a failed gate. |

Copy the boot folder and run **Check SD integrity before calibration**. Require ≥99.9% fresh expected frames per sensor at 100 Hz, all gaps accounted for, no unexplained resets or corrupted blocks, and evidence across two sensor-clock wraps. Inspect queue high-water, counts and stalls. Repeat safe cycles and qualify timeout/reset behavior off-body. A smoke readback alone cannot qualify combined logging.

The desktop audit shows observed Hz and the fraction of known frames received per sensor. Unknown losses are outside that fraction. Compare committed counts with the expected recording duration at 100 Hz. In the logger's `summary.json`, `queue_high_water` is the maximum queued item count and `max_io_us` is the longest measured writer operation in microseconds.

## 5 · Battery, fit and the first real outing

| Gate | Evidence needed to advance |
|---|---|
| **G3 · Power** | Verify cell limits, connector mating and polarity with the meter. Protected BAT+ → latch → XIAO BAT+, BAT− direct. Switched BAT+ → 100 kΩ → D0 → 100 kΩ → common GND, plus 100 nF from D0 to GND. Check several safe voltages against the meter under load. Default divider gain 2, offset 0 mV. Build options `--battery-gain` and `--battery-offset-mv` accept the measured calibration. Verify 3.65 V start, 3.55 V warning, sustained <3.40 V for ~3 s stop as initial settings. Demonstrate graceful closure before rail instability and ≥3 h 45 min logging, acceptable temperature and repeatable safe stops. Never force a deep discharge. |
| **G4 · Worn fit** | Measure before CAD. Dry-use, rigid shoe capture with two lace contacts, two stable shin restraints and an isolated cell pocket. Keep **straps clear of the LED, BOOT and latch switch**. Guard the outside connector, capture cable bends and keep the pedal zone clear. Check each refit in the actual suit. |
| **G5 · Stationary kart** | With venue approval and engine safe, check full pedal stroke, steering, entry and exit. Run the rigid common-motion trial and filmed press/return, held-pose effort, bracing, cable-flex and three-refit checks. [Measurement gates](CALIBRATION_AND_SYNC.md) |
| **G6 · Controlled practice** | After G0–G5, capture one real leg, DJI and RaceBox. Inspect before and after. Require a useful lap comparison, held-out alignment check and an inspected edited export. Stop for a loose lead, heat, discomfort or snagging. |
| **G7 / G8** | After first-leg acceptance, qualify the other side independently. Check both sides across three representative sessions including refit. Pressure expansion needs separate electrical, fit and measured-value evidence later. |

**Portable use begins after qualification.** Charge off-body. With latch OFF, attach USB and enter maintenance, then latch ON to connect the inspected cell. Latch OFF before unplugging USB. For recording, unplug USB, release BOOT and cold-start on the latch. Wait for RECORD. Finish with BOOT stop and the terminal LED before latch-off.

[Troubleshooting](TROUBLESHOOTING.md) · [Everyday checklist](USER_GUIDE.md) · [Home](../README.md)
