@echo off
setlocal
cd /d "%~dp0"
if not exist build\host mkdir build\host
set "TEMP=%CD%\.tools\temp"
set "TMP=%TEMP%"
for /f "tokens=*" %%i in ('^""%ProgramFiles(x86)%\Microsoft Visual Studio\Installer\vswhere.exe" -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath^"') do set "KP_VS=%%i"
if not defined KP_VS exit /b 3
call "%KP_VS%\VC\Auxiliary\Build\vcvars64.bat" >nul
if errorlevel 1 exit /b 4
pushd build\host
cl /nologo /O2 /Oi /GS- /LD /Zl /std:c++17 /Fe:codec_test.dll ..\..\codec_test.cpp /link /NOENTRY /NODEFAULTLIB
if errorlevel 1 exit /b 5
python -B -c "import ctypes,pathlib; b=(ctypes.c_ubyte*108)(); code=ctypes.CDLL(str(pathlib.Path('codec_test.dll').resolve())).checkCodec(b); pathlib.Path('golden.bin').write_bytes(bytes(b)); raise SystemExit(code)"
if errorlevel 1 exit /b 6
fc /b golden.bin ..\..\..\software-v18\synthetic-two-laps\golden\imu_shoe_e000000.bin
exit /b %errorlevel%

