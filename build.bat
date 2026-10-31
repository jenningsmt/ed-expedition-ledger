@echo off
rem Build ED Expedition Ledger: PyInstaller bundle, then the Inno Setup installer.
rem Output: dist-installer\EDLedger-Setup-<version>.exe
rem Needs: pip install -r requirements.txt -r requirements-build.txt, and Inno Setup 6.
setlocal
cd /d "%~dp0"

echo == Icon
python -c "from make_shortcut import _png_to_ico, ICON_PNG, ICON; _png_to_ico(ICON_PNG, ICON)" || goto :fail

echo == PyInstaller
python -m PyInstaller EDLedger.spec --clean --noconfirm || goto :fail

echo == Inno Setup
set "ISCC=%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe"
if not exist "%ISCC%" set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if not exist "%ISCC%" (
    echo Inno Setup 6 not found. Install it from https://jrsoftware.org/isdl.php
    goto :fail
)
"%ISCC%" /Q installer.iss || goto :fail

echo.
echo Built:
dir /b dist-installer\EDLedger-Setup-*.exe
exit /b 0

:fail
echo.
echo Build failed.
exit /b 1
