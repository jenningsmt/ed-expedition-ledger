; Inno Setup script for ED Expedition Ledger.
;
; Builds a per-user installer (no admin rights) from the PyInstaller onedir
; output. Use build.bat, which runs:
;   pyinstaller EDLedger.spec --clean --noconfirm
;   iscc installer.iss
; The installer is written to dist-installer\ and is not committed.

; Bump together with version_info.txt and engine/__init__.py's __version__.
#define MyAppName "ED Expedition Ledger"
#define MyAppVersion "1.0.0"
#define MyAppExeName "EDLedger.exe"

[Setup]
AppId={{846F29F9-EE6A-4F18-AAF5-EC1C36B141AB}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher=jenningsmt
DefaultDirName={localappdata}\Programs\EDLedger
DefaultGroupName={#MyAppName}
PrivilegesRequired=lowest
DisableProgramGroupPage=yes
; Closes a running tray instance (via Restart Manager) before upgrading.
CloseApplications=yes
RestartApplications=no
OutputDir=dist-installer
OutputBaseFilename=EDLedger-Setup-{#MyAppVersion}
UninstallDisplayIcon={app}\{#MyAppExeName}
SetupIconFile=ledger.ico
Compression=lzma2
SolidCompression=yes
ArchitecturesInstallIn64BitMode=x64compatible

; Wipe the bundle before installing, so an upgrade can't keep files an older
; release shipped. User data lives outside {app} — %APPDATA%\EDLedger
; (config.toml) and %LOCALAPPDATA%\EDLedger (database, log, output) — so
; neither upgrades nor uninstalls touch it.
[InstallDelete]
Type: filesandordirs; Name: "{app}\_internal"

[Files]
Source: "dist\EDLedger\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\Configure expedition"; Filename: "{app}\{#MyAppExeName}"; Parameters: "--configure"
Name: "{userdesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch {#MyAppName}"; Flags: nowait postinstall skipifsilent
