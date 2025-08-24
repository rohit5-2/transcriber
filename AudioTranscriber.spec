# -*- mode: python ; coding: utf-8 -*-
import sys

block_cipher = None

# OS-specific binary inclusion
if sys.platform == "win32":
    ffmpeg_binary = ('ffmpeg.exe', '.')
elif sys.platform == "darwin":  # macOS
    ffmpeg_binary = ('ffmpeg.exe', '.')  # Still Windows ffmpeg for cross-compile
else:  # Linux
    ffmpeg_binary = ('ffmpeg.exe', '.')

a = Analysis(
    ['audio_transcriber.py'],
    pathex=[],
    binaries=[ffmpeg_binary],
    datas=[],
    hiddenimports=[
        'customtkinter', 
        'PIL', 
        'PIL._tkinter_finder',
        'pydub',
        'pydub.utils',
        'openai'
    ],
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
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='AudioTranscriber',
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
)
