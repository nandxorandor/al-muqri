"""
AL-MUQRI (المقرئ) — one command to run everything.

Starts all three pieces as child processes, waits for each to be ready, opens
the browser, and shuts everything down cleanly on Ctrl+C.

    conda run --live-stream -n quran_teacher python run.py

Replaces the old three-terminal dance:
    quran-muaalem-engine   (port 8000, the model)
    quran-muaalem-app      (port 8001, search + correction)
    app.py                 (port 5000, the UI)
"""

import os
import sys
import time
import signal
import atexit
import subprocess
import threading
import webbrowser

import requests

HERE = os.path.dirname(os.path.abspath(__file__))
PY = sys.executable

ENGINE_PORT = int(os.getenv('ENGINE_PORT', '8000'))
APP_PORT = int(os.getenv('APP_PORT', '8001'))
UI_PORT = int(os.getenv('PORT', '7070'))

procs = []


def log(tag, msg):
    print(f"  [{tag}] {msg}", flush=True)


def lan_ip():
    """Best-effort local network IP of this laptop (for sharing on the LAN)."""
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(('8.8.8.8', 80))          # no packets sent; just picks the NIC
        return s.getsockname()[0]
    except Exception:
        return '127.0.0.1'
    finally:
        s.close()


def pump(proc, tag, quiet_markers=()):
    """Forward a child's output, filtered so the console stays readable."""
    for raw in iter(proc.stdout.readline, b''):
        try:
            line = raw.decode('utf-8', errors='replace').rstrip()
        except Exception:
            continue
        if not line:
            continue
        if any(m in line for m in quiet_markers):
            continue
        print(f"  [{tag}] {line}", flush=True)


def spawn(name, args, env=None, quiet_markers=()):
    e = dict(os.environ)
    if env:
        e.update(env)
    # Force UTF-8 so Arabic in child output does not crash on Windows cp1252
    e.setdefault('PYTHONIOENCODING', 'utf-8')
    e.setdefault('PYTHONUNBUFFERED', '1')

    # Console scripts (.exe shims) are not always found without shell=True
    # on Windows when invoked from a child process.
    use_shell = (os.name == 'nt' and not args[0].lower().endswith('.exe')
                 and not args[0] == PY)

    p = subprocess.Popen(
        (' '.join(args) if use_shell else args),
        shell=use_shell,
        cwd=HERE, env=e,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        creationflags=(subprocess.CREATE_NEW_PROCESS_GROUP
                       if os.name == 'nt' else 0),
    )
    procs.append((name, p))
    t = threading.Thread(target=pump, args=(p, name, quiet_markers), daemon=True)
    t.start()
    return p


def wait_for(url, name, timeout=420):
    """Poll a /health endpoint until it answers."""
    t0 = time.time()
    dots = 0
    while time.time() - t0 < timeout:
        for nm, p in procs:
            if nm == name and p.poll() is not None:
                log('run', f"{name} exited early with code {p.returncode}")
                return False
        try:
            r = requests.get(url, timeout=2)
            if r.status_code == 200:
                log('run', f"{name} ready ({time.time()-t0:.0f}s)")
                return True
        except Exception:
            pass
        time.sleep(1.5)
        dots += 1
        if dots % 8 == 0:
            log('run', f"still waiting for {name}... "
                       f"({time.time()-t0:.0f}s)")
    log('run', f"timed out waiting for {name}")
    return False


def shutdown(*_):
    print("\n  shutting down...", flush=True)
    for name, p in procs:
        if p.poll() is None:
            try:
                if os.name == 'nt':
                    p.send_signal(signal.CTRL_BREAK_EVENT)
                else:
                    p.terminate()
            except Exception:
                pass
    time.sleep(1.5)
    for name, p in procs:
        if p.poll() is None:
            try:
                p.kill()
            except Exception:
                pass
    print("  done.", flush=True)


def main():
    atexit.register(shutdown)
    try:
        signal.signal(signal.SIGINT, lambda *a: (shutdown(), sys.exit(0)))
    except Exception:
        pass

    print("=" * 64)
    print("  AL-MUQRI  -  المقرئ")
    print("=" * 64)

    # 1. engine (loads the model, slowest)
    log('run', "starting engine...")
    # The console script is what actually worked when run by hand, so try it
    # FIRST. Output is not filtered: if it dies we need to see why.
    engine_cmds = [
        ['quran-muaalem-engine'],
        [PY, '-m', 'quran_muaalem.engine.serve'],
        [PY, '-c',
         'from quran_muaalem.engine.serve import main; main()'],
    ]
    started = False
    for cmd in engine_cmds:
        log('run', f"trying: {' '.join(cmd)}")
        spawn('engine', cmd, env={'PORT': str(ENGINE_PORT)})
        if wait_for(f"http://127.0.0.1:{ENGINE_PORT}/health", 'engine',
                    timeout=420):
            started = True
            break
        log('run', "that attempt failed, trying next...")
    if not started:
        log('run', "")
        log('run', "ENGINE WOULD NOT START.")
        log('run', "Run it by hand in another terminal to see the error:")
        log('run', "    conda run --live-stream -n quran_teacher "
                   "quran-muaalem-engine")
        return 1

    # 3. the UI
    log('run', "starting UI...")
    spawn('ui', [PY, 'app.py'],
          env={'PORT': str(UI_PORT),
               'MUAALEM_ENGINE': f"http://127.0.0.1:{ENGINE_PORT}"},
          quiet_markers=('WARNING: This is a development server',
                         'Press CTRL+C', '* Running on', '* Debug mode',
                         '* Serving Flask', 'GET /health', 'GET /state'))
    time.sleep(2.5)

    scheme = 'https' if os.getenv('HTTPS', '0').lower() not in (
        '0', '', 'false', 'no') else 'http'
    local_url = f"{scheme}://127.0.0.1:{UI_PORT}"
    lan = lan_ip()
    print("=" * 64)
    print(f"  READY (this laptop) -> {local_url}")
    if lan != '127.0.0.1':
        print(f"  Other home PCs open -> {scheme}://{lan}:{UI_PORT}")
        if scheme == 'http':
            print("  NOTE: mic won't work on other PCs over http. "
                  "Relaunch with HTTPS=1 to enable it.")
    print("  Ctrl+C here stops everything.")
    print("=" * 64)
    try:
        webbrowser.open(local_url)
    except Exception:
        pass

    # keep alive; surface it if a child dies
    try:
        while True:
            time.sleep(2)
            for name, p in procs:
                if p.poll() is not None:
                    log('run', f"{name} stopped (code {p.returncode})")
                    return 1
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == '__main__':
    sys.exit(main())
