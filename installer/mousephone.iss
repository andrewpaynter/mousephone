; Inno Setup script for the Windows installer. Built by build_windows.ps1,
; which passes the version in: ISCC /DAppVersion=1.2.0 installer\mousephone.iss
;
; Installs per-user (no admin prompt) into %LOCALAPPDATA%\Programs, so the
; app can update itself: the in-app updater downloads the next installer
; and runs it with /VERYSILENT, and the [Run] entry relaunches the app.

#ifndef AppVersion
  #error Pass the version: ISCC /DAppVersion=x.y.z
#endif

[Setup]
; Never change AppId: it's how Windows recognizes upgrades of the same app.
AppId={{548E215B-935E-4D5A-B712-2165A7055965}
AppName=mousephone
AppVersion={#AppVersion}
AppPublisher=mousephone
AppPublisherURL=https://github.com/andrewpaynter/mousephone
DefaultDirName={localappdata}\Programs\mousephone
PrivilegesRequired=lowest
DisableDirPage=yes
DisableProgramGroupPage=yes
OutputDir=..\dist
OutputBaseFilename=mousephone-{#AppVersion}-windows-setup
SetupIconFile=..\assets\mousephone.ico
UninstallDisplayIcon={app}\mousephone.exe
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
; If mousephone is running during a manual install, offer to close it.
CloseApplications=yes
Compression=lzma2
SolidCompression=yes
WizardStyle=modern

[InstallDelete]
; Clear the previous version's bundled libraries, so files a new version
; no longer ships don't linger alongside it.
Type: filesandordirs; Name: "{app}\_internal"

[Files]
Source: "..\dist\mousephone\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\mousephone"; Filename: "{app}\mousephone.exe"

[Run]
; Shown as a "Launch mousephone" checkbox after a manual install; always
; runs after a silent (in-app) update, which is what relaunches the app.
Filename: "{app}\mousephone.exe"; Description: "Launch mousephone"; Flags: nowait postinstall
