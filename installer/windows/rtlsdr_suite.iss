; Inno Setup script for RTL-SDR Suite (Windows installer)
;
; Bundles the PyInstaller onedir build (dist\RTL-SDR-Suite\) plus the
; external command-line tools the ADS-B/ISM/POCSAG tabs need (rtl_adsb,
; rtl_433, rtl_fm, multimon-ng, librtlsdr.dll, ...) and adds that tools
; folder to the user's PATH so the tabs find them without extra setup.
;
; Build with: "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" rtlsdr_suite.iss
; Expects, relative to this .iss file:
;   ..\..\dist\RTL-SDR-Suite\       <- PyInstaller onedir output
;   ..\..\rtl-sdr-bin-new\          <- external tool binaries + librtlsdr.dll

#define MyAppName "RTL-SDR Suite"
#define MyAppVersion "1.0.0"
#define MyAppPublisher "RTL-SDR Suite"
#define MyAppExeName "RTL-SDR-Suite.exe"
#define DistDir "..\..\dist\RTL-SDR-Suite"
#define ToolsDir "..\..\rtl-sdr-bin-new"

[Setup]
AppId={{8F2C1E3A-8B4D-4B7E-9C1A-2D6F0E9B4A11}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir=..\..\dist_installer
OutputBaseFilename=RTL-SDR-Suite-Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible
ChangesEnvironment=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "german"; MessagesFile: "compiler:Languages\German.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked
Name: "addpath"; Description: "Add the RTL-SDR command-line tools (rtl_433, rtl_fm, multimon-ng, ...) to PATH"; GroupDescription: "Command-line tools"; Flags: checkedonce

[Files]
Source: "{#DistDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#ToolsDir}\*"; DestDir: "{app}\tools"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\..\README.md"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent

; -- add {app}\tools to the *user* PATH so rtl_adsb/rtl_433/rtl_fm/multimon-ng
;    are found without needing admin rights or a reboot's worth of ceremony --
[Code]
const
  EnvKey = 'Environment';

function GetUserPath(): String;
var
  Value: String;
begin
  if not RegQueryStringValue(HKEY_CURRENT_USER, EnvKey, 'Path', Value) then
    Value := '';
  Result := Value;
end;

procedure AddToUserPath(Dir: String);
var
  Path: String;
begin
  Path := GetUserPath();
  if (Pos(LowerCase(Dir), LowerCase(Path)) = 0) then
  begin
    if (Length(Path) > 0) and (Path[Length(Path)] <> ';') then
      Path := Path + ';';
    Path := Path + Dir;
    RegWriteStringValue(HKEY_CURRENT_USER, EnvKey, 'Path', Path);
  end;
end;

procedure RemoveFromUserPath(Dir: String);
var
  Path, NewPath: String;
  P: Integer;
begin
  Path := GetUserPath();
  NewPath := Path;
  P := Pos(Dir + ';', NewPath);
  if P > 0 then
    Delete(NewPath, P, Length(Dir) + 1)
  else
  begin
    P := Pos(';' + Dir, NewPath);
    if P > 0 then
      Delete(NewPath, P, Length(Dir) + 1)
    else if NewPath = Dir then
      NewPath := '';
  end;
  if NewPath <> Path then
    RegWriteStringValue(HKEY_CURRENT_USER, EnvKey, 'Path', NewPath);
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if (CurStep = ssPostInstall) and WizardIsTaskSelected('addpath') then
    AddToUserPath(ExpandConstant('{app}\tools'));
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usPostUninstall then
    RemoveFromUserPath(ExpandConstant('{app}\tools'));
end;
