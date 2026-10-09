# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['C:\\SynologyDrive\\WorkData\\00Securite\\00 MP4\\mp4_chapter_tool.py'],
    pathex=[],
    binaries=[],
    datas=[('C:\\SynologyDrive\\WorkData\\00Securite\\00 MP4\\assets\\icon.ico', 'assets')],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='MP4ChapterTool',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['C:\\SynologyDrive\\WorkData\\00Securite\\00 MP4\\assets\\icon.ico'],
)
