# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for AL-MUQRI (المقرئ) — builds a portable "onedir" folder.
#
#   Build:  pyinstaller al-muqri.spec --noconfirm
#   (or just run build_exe.bat, which also copies the runtime data.)
#
# Data files (index.html, reference_audio, layout JSON, fonts) are NOT frozen
# inside the bundle — build_exe.bat copies them NEXT TO the .exe, and app.py
# reads them from there (it is frozen-aware).

from PyInstaller.utils.hooks import collect_all, collect_submodules

datas, binaries, hiddenimports = [], [], []

# Packages that ship data files / lazy imports PyInstaller can't see on its own.
_collect = [
    "quran_muaalem", "quran_transcript",
    "litserve", "transformers", "tokenizers", "safetensors",
    "huggingface_hub", "pydantic", "pydantic_settings",
    "fastapi", "starlette", "uvicorn",
    "librosa", "soundfile", "audioread", "lazy_loader", "pooch",
    "scipy", "sklearn", "numba", "llvmlite", "joblib",
    "torch",
]
for pkg in _collect:
    try:
        d, b, h = collect_all(pkg)
        datas += d
        binaries += b
        hiddenimports += h
    except Exception as e:
        print(f"[spec] skip {pkg}: {e}")

hiddenimports += collect_submodules("quran_muaalem")
hiddenimports += collect_submodules("quran_transcript")

a = Analysis(
    ["serve_local.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "gradio", "IPython", "notebook"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="al-muqri",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,          # keep a console so users see progress / errors
    disable_windowed_traceback=False,
    icon=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="al-muqri",
)
