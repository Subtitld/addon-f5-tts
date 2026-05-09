# PyInstaller spec for the f5-tts add-on.
# Build with: pyinstaller f5-tts-addon.spec --distpath dist/

from PyInstaller.utils.hooks import collect_data_files, collect_submodules


def _safe_collect(fn, name):
    try:
        return fn(name)
    except Exception:
        return []


# f5-tts pulls a *huge* dep tree: torch, torchaudio, vocos, librosa,
# transformers, x_transformers, ema_pytorch, torchdiffeq, descript-codec,
# pydub, etc. The defensive _safe_collect lets the freeze keep going
# even if a sub-package isn't installed in the build environment.
hiddenimports = (
    _safe_collect(collect_submodules, 'f5_tts')
    + _safe_collect(collect_submodules, 'vocos')
    + _safe_collect(collect_submodules, 'transformers')
    + _safe_collect(collect_submodules, 'librosa')
    + _safe_collect(collect_submodules, 'soundfile')
    + _safe_collect(collect_submodules, 'pypinyin')
    + _safe_collect(collect_submodules, 'jieba')
    # f5-tts imports torchaudio at module scope; collect explicitly so we
    # don't depend on PyInstaller's static analysis catching it (coqui's
    # v1.0.3 frozen bundle shipped without torchaudio for that reason).
    + _safe_collect(collect_submodules, 'torchaudio')
)
datas = (
    _safe_collect(collect_data_files, 'f5_tts')
    + _safe_collect(collect_data_files, 'vocos')
    + _safe_collect(collect_data_files, 'transformers')
    + _safe_collect(collect_data_files, 'librosa')
    + _safe_collect(collect_data_files, 'pypinyin')
    + _safe_collect(collect_data_files, 'torchaudio')
    + [('manifest.json', '.')]
)

block_cipher = None

a = Analysis(
    ['f5_tts_addon.py'],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tensorflow', 'jax', 'flax', 'gradio', 'wandb', 'matplotlib'],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name='f5-tts-addon',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
)
coll = COLLECT(
    exe, a.binaries, a.zipfiles, a.datas,
    strip=False, upx=False, upx_exclude=[],
    name='f5-tts-addon',
)
