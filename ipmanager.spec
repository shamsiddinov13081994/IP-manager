# -*- mode: python ; coding: utf-8 -*-
# ===========================================================================
# PyInstaller spec — IPmanager.exe yig'ish uchun
# Ishga tushirish (Windows'da):  pyinstaller ipmanager.spec
# Natija: dist\IPmanager\ papkasi ichida IPmanager.exe va kerakli fayllar
# ===========================================================================

block_cipher = None

# --- pywebview backend fayllarini avtomatik yig'ish (native oyna uchun) ---
# pywebview Windows'da Edge WebView2 dvigatelidan foydalanadi; uning yordamchi
# fayllari va submodullarini PyInstaller o'zi topmasligi mumkin, shuning uchun
# collect_all bilan hammasini aniq yig'amiz.
from PyInstaller.utils.hooks import collect_all
_wv_datas, _wv_binaries, _wv_hidden = collect_all('webview')

a = Analysis(
    ['run_server.py'],                 # kirish nuqtasi (launcher)
    pathex=[],
    binaries=_wv_binaries,
    datas=[
        ('static', 'static'),          # CSS/JS/vendor kutubxonalar
        ('templates', 'templates'),    # index.html
    ] + _wv_datas,
    hiddenimports=[
        'waitress',
        'waitress.server',
        'app',                         # bizning Flask ilova moduli
        'clr',                         # pythonnet — pywebview Edge backend uchun
    ] + _wv_hidden,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,             # one-folder rejim (installer uchun qulay)
    name='IPmanager',                  # .exe nomi
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,                     # False = oyna ko'rinmaydi (fonda ishlaydi).
                                       # Sinov paytida True qilsangiz, loglar
                                       # konsolda ko'rinadi (xatoni ko'rish oson).
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='icon.ico',                   # dastur belgisi
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='IPmanager',                  # dist\IPmanager\ papka nomi
)
