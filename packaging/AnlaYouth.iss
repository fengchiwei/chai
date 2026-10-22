; 少年仔、安啦會客室 — Windows 安裝精靈（Inno Setup 6.3 以上）
;
; 先執行：python build_desktop.py      （產生 dist\AnlaYouth\AnlaYouth.exe）
; 再執行：ISCC packaging\AnlaYouth.iss  （產生 dist\AnlaYouth_Setup.exe）
; 指定版本：ISCC /DMyAppVersion=1.3.1 packaging\AnlaYouth.iss
;
; 本檔需以 UTF-8（含 BOM）儲存，中文名稱才不會亂碼。
; 不安裝任何 API 金鑰；GEMINI_API_KEY / WORKBENCH_PASSWORD 由使用者的環境變數提供。
; 解除安裝時保留 %APPDATA%\AnlaYouth（本機資料庫），避免誤刪紀錄；需要時請手動刪除。

#ifndef MyAppVersion
  #define MyAppVersion "1.3.0"
#endif
#define MyAppName "少年仔、安啦會客室"
#define MyAppPublisher "Anla Youth Room Team"
#define MyAppExeName "AnlaYouth.exe"

[Setup]
AppId={{8C3B6E2A-5D41-4F7E-9A1C-2B7D0E6F4A93}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\AnlaYouth
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
; 預設免系統管理員權限（安裝到使用者資料夾）；安裝時可選擇改為所有使用者。
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\dist
OutputBaseFilename=AnlaYouth_Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\{#MyAppExeName}
UninstallDisplayName={#MyAppName}

[Languages]
; 只使用 Inno Setup 內建且保證存在的英文訊息檔；繁中訊息檔（ChineseTraditional.isl）為非官方翻譯，
; 若已自行放入 Inno Setup 的 Languages 資料夾，可再加一行。
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "..\dist\AnlaYouth\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent
