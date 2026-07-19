#ifndef MyAppVersion
  #define MyAppVersion "0.0.0-dev"
#endif

[Setup]
AppId={{A80FBA4A-7877-4BD4-8B20-70FB45C01A2A}
AppName=WinSSH UI
AppVersion={#MyAppVersion}
AppPublisher=AceAsket
AppPublisherURL=https://github.com/AceAsket/winsshui
AppSupportURL=https://github.com/AceAsket/winsshui/issues
AppUpdatesURL=https://github.com/AceAsket/winsshui/releases/latest
DefaultDirName={localappdata}\Programs\WinSSH UI
DefaultGroupName=WinSSH UI
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\dist
OutputBaseFilename=WinSSH-UI-Setup
SetupIconFile=..\src\winsshui\assets\AppIcon.ico
UninstallDisplayIcon={app}\WinSSH-UI.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Создать ярлык на рабочем столе"; GroupDescription: "Дополнительные ярлыки:"; Flags: unchecked

[Files]
Source: "..\dist\WinSSH-UI.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\dist\WinSSH-AskPass.exe"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\WinSSH UI"; Filename: "{app}\WinSSH-UI.exe"
Name: "{autodesktop}\WinSSH UI"; Filename: "{app}\WinSSH-UI.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\WinSSH-UI.exe"; Description: "Запустить WinSSH UI"; Flags: nowait postinstall skipifsilent
