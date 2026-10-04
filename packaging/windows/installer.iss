; Inno Setup script for Jace Launcher. Built by packaging/build.py, which passes:
;   AppVersion, SourceDir (PyInstaller output), OutputDir, OutputName, IconFile

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
AppId={{7D3C2A4E-9B1F-4C8E-A6D2-5E0F1B3C9A71}
AppName=Jace Launcher
AppVersion={#AppVersion}
AppVerName=Jace Launcher {#AppVersion}
AppPublisher=Jace
DefaultDirName={autopf}\Jace Launcher
DefaultGroupName=Jace Launcher
; always ask where to install
DisableDirPage=no
DisableProgramGroupPage=yes
; let the user choose "only for me" (no admin needed) or "all users"
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputDir={#OutputDir}
OutputBaseFilename={#OutputName}
SetupIconFile={#IconFile}
UninstallDisplayIcon={app}\JaceLauncher.exe
UninstallDisplayName=Jace Launcher
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
; close a running launcher before upgrading/uninstalling
CloseApplications=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Shortcuts:"

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\Jace Launcher"; Filename: "{app}\JaceLauncher.exe"
Name: "{group}\Uninstall Jace Launcher"; Filename: "{uninstallexe}"
Name: "{autodesktop}\Jace Launcher"; Filename: "{app}\JaceLauncher.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\JaceLauncher.exe"; Description: "Start Jace Launcher"; Flags: nowait postinstall skipifsilent
