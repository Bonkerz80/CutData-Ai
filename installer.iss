#define MyAppName "CutData AI"
#define MyAppVersion "0.1.2"
#define MyAppPublisher "CutData AI"
#define MyAppURL "https://github.com/Bonkerz80/CutData-AI"
#define MyAppExeName "CutData AI.exe"

[Setup]
AppId={{A6C7D4A5-42B7-4B20-9E56-7C0C9D1F3A11}}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}
DefaultDirName={localappdata}\Programs\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
MinVersion=10.0.17763
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=installer
OutputBaseFilename=CutData-AI-Setup-{#MyAppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\{#MyAppExeName}
VersionInfoCompany={#MyAppPublisher}
VersionInfoDescription={#MyAppName} Windows installer
VersionInfoProductName={#MyAppName}
VersionInfoProductVersion={#MyAppVersion}
VersionInfoCopyright=Copyright (c) 2026 CutData AI

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Files]
Source: "dist\CutData AI\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[InstallDelete]
; Remove incompatible libraries shipped by 0.1.0; these are Windows components.
Type: files; Name: "{app}\_internal\icu*.dll"
Type: files; Name: "{app}\_internal\api-ms-win-*.dll"
Type: files; Name: "{app}\_internal\ucrtbase.dll"
Type: files; Name: "{app}\icu*.dll"
Type: files; Name: "{app}\api-ms-win-*.dll"
Type: files; Name: "{app}\ucrtbase.dll"
Type: filesandordirs; Name: "{app}\_internal\PySide6"
Type: filesandordirs; Name: "{app}\_internal\shiboken6"
Type: filesandordirs; Name: "{app}\PySide6"
Type: filesandordirs; Name: "{app}\shiboken6"
Type: files; Name: "{app}\Qt6*.dll"
Type: files; Name: "{app}\pyside6.abi3.dll"
Type: files; Name: "{app}\shiboken6.abi3.dll"

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch {#MyAppName}"; Flags: nowait postinstall skipifsilent
