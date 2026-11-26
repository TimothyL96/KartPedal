"""Project-local Arduino CLI provisioning and reproducible XIAO Plus builds. Never flashes."""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parent
TOOLS = ROOT / ".tools"
CLI = TOOLS / "arduino-cli.exe"
CFG = TOOLS / "config.json"
CORE = "3.3.5"
BOSCH = "41129fcfe39c583ee5462d79195741945d51c1fe"
BOARD = "esp32:esp32:XIAO_ESP32S3_Plus"
INDEX = "https://espressif.github.io/arduino-esp32/package_esp32_index.json"
env = dict(os.environ)
env["SOURCE_DATE_EPOCH"] = "1795651200"  # Fixed V18 release date for compiler timestamps.
for key in ("TEMP", "TMP"):
    env[key] = str(TOOLS / "temp")

def fetch(url):
    with urllib.request.urlopen(url, timeout=180) as response:
        return response.read()

def run(*args):
    subprocess.run([str(CLI), "--config-file", str(CFG), *map(str, args)], env=env, check=True)

def provision():
    for name in ("temp", "data", "downloads", "user", "cache"):
        (TOOLS / name).mkdir(parents=True, exist_ok=True)
    CFG.write_text(json.dumps({"directories":{k:str(TOOLS / v) for k,v in
        [("data","data"),("downloads","downloads"),("user","user")]},"build_cache":{"path":str(TOOLS/"cache")},
        "board_manager":{"additional_urls":[INDEX]},"updater":{"enable_notification":False}}))
    if not CLI.exists():
        asset="arduino-cli_1.2.2_Windows_64bit.zip"
        base="https://github.com/arduino/arduino-cli/releases/download/v1.2.2/"
        sums=fetch(base+"1.2.2-checksums.txt").decode()
        expected=next(line.split()[0] for line in sums.splitlines() if line.split()[-1]==asset)
        data=fetch(base+asset)
        if hashlib.sha256(data).hexdigest()!=expected: raise ValueError("Arduino CLI checksum")
        CLI.write_bytes(zipfile.ZipFile(io.BytesIO(data)).read("arduino-cli.exe"))
    dest=ROOT/"KartPedal"/"src"/"bosch"
    dest.mkdir(parents=True,exist_ok=True)
    for name in ("LICENSE","bmi2.h","bmi2_defs.h","bmi2.c","bmi270.h","bmi270.c"):
        (dest/name).write_bytes(fetch(f"https://raw.githubusercontent.com/boschsensortec/BMI270_SensorAPI/{BOSCH}/{name}"))
    run("core","update-index")
    run("core","install","esp32:esp32@"+CORE,"--skip-post-install")

def build(side, gain=2., offset=0., clean=False):
    out=ROOT/"build"/side
    out.mkdir(parents=True,exist_ok=True)
    # The Espressif Windows post-export recipe copies partitions.csv here even with --output-dir.
    (ROOT/"KartPedal"/"build"/BOARD.replace(":",".")).mkdir(parents=True,exist_ok=True)
    run("compile",*(["--clean"] if clean else []),"--fqbn",BOARD,"--jobs","4","--build-path",TOOLS/("build-"+side),
        "--output-dir",out,"--build-property",f"compiler.cpp.extra_flags=-DKP_LEFT={int(side=='L')} -DKP_BAT_GAIN={gain} -DKP_BAT_OFFSET={offset}",ROOT/"KartPedal")
    image=(out/"KartPedal.ino.bin").read_bytes()
    info={"side":side,"fqbn":BOARD,"arduino_esp32":CORE,"bosch_commit":BOSCH,
          "battery_gain":gain,"battery_offset_mv":offset,"bytes":len(image),
          "sha256":hashlib.sha256(image).hexdigest(),
          "appended_image_sha256":image[-32:].hex(),"flashed":False}
    if image[-32:]!=hashlib.sha256(image[:-32]).digest():raise ValueError("ESP image trailer checksum")
    (out/"build-info.json").write_text(json.dumps(info,indent=2))
    print(side,info["sha256"],flush=True)

if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--provision",action="store_true")
    p.add_argument("--side",choices=("L","R","both"))
    p.add_argument("--clean",action="store_true",help="Rebuild the selected side from a clean compilation directory")
    p.add_argument("--battery-gain",type=float,default=2.)
    p.add_argument("--battery-offset-mv",type=float,default=0.)
    a=p.parse_args()
    if a.provision: provision()
    if not 1.8<=a.battery_gain<=2.2 or not -200<=a.battery_offset_mv<=200:p.error("Check the calibrated divider gain and offset")
    for side in (("R","L") if a.side=="both" else (a.side,) if a.side else ()): build(side,a.battery_gain,a.battery_offset_mv,a.clean)
