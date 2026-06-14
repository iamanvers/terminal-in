; TERMINAL//IN — Inno Setup installer (PRD 5b.1, "full package").
; Wraps the PyInstaller onedir tree (dist\TerminalIN) into a single
; TERMINAL-IN-Setup.exe with Start-menu + desktop shortcuts, an optional
; logon auto-start, a license page, and a clean uninstaller.
;
; Build:  iscc packaging\installer.iss        (after build_installer.ps1 stages dist\)
; Needs:  Inno Setup 6  (https://jrsoftware.org/isdl.php) → iscc on PATH.
;
; Mutable state (DB, reports, models, logs, settings) lives in
; %LOCALAPPDATA%\TerminalIN and is created at runtime — the install dir stays
; read-only and the uninstaller never touches user data.

#define MyAppName "TERMINAL//IN"
#define MyAppVersion "1.0.0"
#define MyAppPublisher "Anmol Verma"
#define MyAppExeName "TerminalIN.exe"
#define DistDir "..\dist\TerminalIN"

[Setup]
AppId={{8E5C1B7A-3F42-4D9E-9C21-7A0B6F2D4E11}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\TerminalIN
DefaultGroupName=TERMINAL//IN
DisableProgramGroupPage=yes
OutputDir=..\dist
OutputBaseFilename=TERMINAL-IN-Setup
SetupIconFile=terminalin.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
LicenseFile=..\docs\LEGAL.md
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Shortcuts:"
Name: "autostart"; Description: "Start TERMINAL//IN automatically at logon"; GroupDescription: "Startup:"; Flags: unchecked

[Files]
; The entire PyInstaller onedir payload (exe + _internal\ runtime + UI + data).
Source: "{#DistDir}\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{group}\TERMINAL//IN"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\terminalin.ico"
Name: "{group}\Uninstall TERMINAL//IN"; Filename: "{uninstallexe}"
Name: "{autodesktop}\TERMINAL//IN"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\terminalin.ico"; Tasks: desktopicon
Name: "{userstartup}\TERMINAL//IN"; Filename: "{app}\{#MyAppExeName}"; Tasks: autostart

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch TERMINAL//IN"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Remove only app-dir caches we may create; user data in %LOCALAPPDATA% is kept.
Type: filesandordirs; Name: "{app}\_internal\hf-cache"
