"""
AL-MUQRI (المقرئ) — single-process launcher for the packaged Windows build.

Runs the quran-muaalem engine and the Flask UI inside ONE process (the engine
in the main thread, the UI in a background thread), so the whole app can be
frozen with PyInstaller without spawning a separate `python` interpreter.

Dev use:   python serve_local.py
Frozen:    al-muqri.exe   (built from this file — see al-muqri.spec)
"""

import os
import sys
import time
import threading
import webbrowser
import multiprocessing

# Windows consoles default to cp1252 and choke on Arabic — force UTF-8.
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass


def _base_dir():
    """Folder that holds index.html / reference_audio / layout JSON.
    Next to the .exe when frozen, else this file's folder."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def _wait_for_engine(url, timeout=1200):
    import requests
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            if requests.get(url, timeout=2).status_code == 200:
                return True
        except Exception:
            pass
        time.sleep(1.5)
    return False


def _start_ui_when_ready(ui_url, engine_health):
    """Wait for the engine, then start the Flask UI (in this thread) + browser."""
    print("  loading the recitation engine (first run downloads the model)...",
          flush=True)
    if not _wait_for_engine(engine_health):
        print("  [error] the engine did not start in time.", flush=True)
        return
    print(f"  READY  ->  {ui_url}", flush=True)
    try:
        webbrowser.open(ui_url)
    except Exception:
        pass
    # Import the Flask app AFTER chdir so it finds its data files.
    from app import app
    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("UI_PORT", "7070"))
    # Werkzeug dev server; fine for a local single-user app.
    app.run(host=host, port=port, threaded=True, use_reloader=False)


def main():
    base = _base_dir()
    os.chdir(base)

    # ---- UI config ----
    # IMPORTANT: the engine's EngineSettings reads the PORT env var, so we must
    # NOT set PORT here (it would move the engine onto the UI's port). The engine
    # keeps its default (8000); the UI uses UI_PORT.
    os.environ.pop("PORT", None)
    os.environ.setdefault("HOST", "127.0.0.1")
    os.environ.setdefault("MUAALEM_ENGINE", "http://127.0.0.1:8000")
    os.environ.setdefault("VERBOSE", "0")
    os.environ.setdefault("UI_PORT", "7070")

    # ---- Engine config (read by quran_muaalem EngineSettings) ----
    # Auto-pick GPU only if this build's torch actually sees a CUDA device;
    # otherwise fall back to CPU so it runs on any machine.
    try:
        import torch
        accel = "cuda" if torch.cuda.is_available() else "cpu"
    except Exception:
        accel = "cpu"
    os.environ.setdefault("ACCELERATOR", accel)
    os.environ.setdefault("DEVICES", "1")
    os.environ.setdefault("WORKERS_PER_DEVICE", "1")
    # engine port stays at its default (8000); do NOT set PORT for it.

    ui_url = f"http://127.0.0.1:{os.environ['UI_PORT']}"
    engine_health = os.environ["MUAALEM_ENGINE"].rstrip("/") + "/health"

    print("=" * 60, flush=True)
    print("  AL-MUQRI", flush=True)
    print(f"  accelerator: {accel}", flush=True)
    print("=" * 60, flush=True)

    # UI waits for the engine in a background thread; the engine (uvicorn) runs
    # in the MAIN thread so its signal handling works correctly.
    threading.Thread(target=_start_ui_when_ready,
                     args=(ui_url, engine_health), daemon=True).start()

    from quran_muaalem.engine.main import main as engine_main
    engine_main()   # blocks


if __name__ == "__main__":
    multiprocessing.freeze_support()   # REQUIRED for frozen multiprocessing
    main()
