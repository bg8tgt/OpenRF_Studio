# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['main_entry.py'],
    pathex=[],
    binaries=[],
    datas=[('examples', 'examples'), ('docs', 'docs'), ('assets', 'assets')],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # _secrets.py 只存在于本机（含密钥），绝不能打进发布包
    excludes=['app.ai._secrets'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='OpenRF_Studio',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['assets/openrf.ico'],
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='OpenRF_Studio',
)
