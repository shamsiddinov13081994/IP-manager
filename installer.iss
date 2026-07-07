; ===========================================================================
; IPmanager — Inno Setup o'rnatuvchi skripti
; Bu skript "IPmanager-Setup.exe" yaratadi.
; Kompilyatsiya: Inno Setup Compiler'da ochib "Compile" (yoki F9) bosing.
; ===========================================================================

#define AppName "IPmanager"
#define AppVersion "1.0"
#define AppPublisher "Kiberxavfsizlik Departamenti"
#define ExeName "IPmanager.exe"

[Setup]
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
; Dastur o'rnatiladigan standart joy (foydalanuvchi o'zgartira oladi)
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
UninstallDisplayIcon={app}\{#ExeName}
OutputBaseFilename=IPmanager-Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
; Setup.exe ning o'z belgisi
SetupIconFile=icon.ico
; Papkalar yaratish uchun administrator huquqi kerak
PrivilegesRequired=admin
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "uz"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Ish stoli (desktop) yorlig'ini yaratish"; GroupDescription: "Qo'shimcha yorliqlar:"

[Files]
; PyInstaller yaratgan butun papkani ko'chiramiz
Source: "dist\IPmanager\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
; Start menyu yorlig'i
Name: "{group}\{#AppName}"; Filename: "{app}\{#ExeName}"
; Start menyuda "o'chirish" yorlig'i
Name: "{group}\{#AppName} ni o'chirish"; Filename: "{uninstallexe}"
; Ish stoli yorlig'i (agar tanlansa)
Name: "{commondesktop}\{#AppName}"; Filename: "{app}\{#ExeName}"; Tasks: desktopicon

[Run]
; O'rnatish tugagach dasturni darhol ishga tushirish imkoni
Filename: "{app}\{#ExeName}"; Description: "IPmanager ni hozir ishga tushirish"; Flags: nowait postinstall skipifsilent

[Code]
var
  DataDirPage: TInputDirWizardPage;

// --- Qo'shimcha sahifa: ma'lumot/log/backup papkasini so'rash ---
procedure InitializeWizard;
begin
  DataDirPage := CreateInputDirPage(wpSelectDir,
    'Ma''lumot va zaxira papkasi',
    'Baza, loglar va zaxira nusxalari qayerga saqlansin?',
    'IPmanager barcha ma''lumotlarini (baza, loglar, backup) quyidagi papka ichiga ' +
    'yozadi. Bu — dastur o''rnatilgan papkadan ALOHIDA joy (shunda dasturni qayta ' +
    'o''rnatsangiz ham ma''lumotlar yo''qolmaydi). Standart joyni qoldiring yoki boshqasini tanlang.',
    False, '');
  DataDirPage.Add('');
  DataDirPage.Values[0] := 'C:\IPmanager-data';
end;

// --- O'rnatishdan keyin: papkalarni yaratish va config.ini yozish ---
procedure CurStepChanged(CurStep: TSetupStep);
var
  DataDir: string;
  ConfigPath: string;
  Lines: TArrayOfString;
begin
  if CurStep = ssPostInstall then
  begin
    DataDir := DataDirPage.Values[0];

    // Uch papkani yaratamiz
    ForceDirectories(DataDir + '\data');
    ForceDirectories(DataDir + '\logs');
    ForceDirectories(DataDir + '\backups');

    // config.ini ni tanlangan yo'llar bilan yozamiz (exe yonida)
    SetArrayLength(Lines, 15);
    Lines[0]  := '; IPmanager sozlamalari (o''rnatuvchi tomonidan yaratilgan)';
    Lines[1]  := '';
    Lines[2]  := '[paths]';
    Lines[3]  := 'data_dir = ' + DataDir + '\data';
    Lines[4]  := 'log_dir = ' + DataDir + '\logs';
    Lines[5]  := 'backup_dir = ' + DataDir + '\backups';
    Lines[6]  := '';
    Lines[7]  := '[server]';
    Lines[8]  := 'host = 127.0.0.1';
    Lines[9]  := 'port = 5000';
    Lines[10] := 'ui_mode = auto';
    Lines[11] := '';
    Lines[12] := '[backup]';
    Lines[13] := 'keep_days = 30';
    Lines[14] := '';

    ConfigPath := ExpandConstant('{app}\config.ini');
    SaveStringsToFile(ConfigPath, Lines, False);
  end;
end;

// --- O'chirishdan keyin eslatma: ma'lumot papkasi saqlanib qoladi ---
// (Biz uni ataylab o'chirmaymiz — foydalanuvchi ma'lumotlari qimmatli)
