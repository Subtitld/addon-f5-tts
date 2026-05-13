# PyInstaller spec for the f5-tts add-on.
# Build with: pyinstaller f5-tts-addon.spec --distpath dist/

from PyInstaller.utils.hooks import collect_data_files, collect_submodules


def _safe_collect(fn, name, **kwargs):
    try:
        return fn(name, **kwargs)
    except Exception:
        return []


# Packages whose `.py` source files MUST ship alongside the `.pyc` —
# they decorate module-scope functions with `@torch.jit.script`, which
# at import time calls `inspect.getsourcelines()` on the decorated
# function. PyInstaller's default freeze stores bytecode only, so the
# source-line lookup fails with
# `OSError: Can't get source for <function ...>. TorchScript requires
# source access in order to carry out compilation`.
#
# Confirmed offenders (traced from a 1.0.4 frozen bundle):
#   - x_transformers/attend.py:48  ->  @torch.jit.script softclamp(...)
# Defensive inclusions (small packages from the same dep family that
# use TorchScript heavily — cheap insurance against the next surprise):
#   - ema_pytorch, torchdiffeq, vocos
# `collect_data_files(..., include_py_files=True)` is the lever that
# tells PyInstaller to also ship `.py` files; without that flag only
# non-Python data (configs, fonts, weights) come along.
_TORCHSCRIPT_SOURCE_PACKAGES = (
    'x_transformers',
    'ema_pytorch',
    'torchdiffeq',
    'vocos',
)

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
    # f5_tts/infer/utils_infer.py imports matplotlib at module scope
    # (it ships training-utility plotting code that runs unconditionally).
    # Without matplotlib the import chain fails before we reach inference.
    # We previously listed matplotlib in `excludes` to slim the bundle —
    # that was a mistake; it has to be bundled.
    + _safe_collect(collect_submodules, 'matplotlib')
)
for _pkg in _TORCHSCRIPT_SOURCE_PACKAGES:
    hiddenimports += _safe_collect(collect_submodules, _pkg)

datas = (
    _safe_collect(collect_data_files, 'f5_tts')
    + _safe_collect(collect_data_files, 'vocos')
    + _safe_collect(collect_data_files, 'transformers')
    + _safe_collect(collect_data_files, 'librosa')
    + _safe_collect(collect_data_files, 'pypinyin')
    + _safe_collect(collect_data_files, 'torchaudio')
    + _safe_collect(collect_data_files, 'matplotlib')
    + [('manifest.json', '.')]
)
# Ship .py sources for TorchScript-bearing packages so
# `inspect.getsourcelines()` can find them at runtime. Each of these
# is small (tens of files, single-digit MB), so the freeze grows
# negligibly compared to torch itself.
for _pkg in _TORCHSCRIPT_SOURCE_PACKAGES:
    datas += _safe_collect(collect_data_files, _pkg, include_py_files=True)

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
    excludes=['tensorflow', 'jax', 'flax', 'gradio', 'wandb'],
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
