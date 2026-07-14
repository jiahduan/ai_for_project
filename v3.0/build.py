# =============================================================================
# build.py -- Trigger remote build, show progress + real-time watcher log
# =============================================================================

import json
import sys
import time
import threading
from datetime import datetime
from pathlib import Path
import config as _config
from config import (
    WIN_TRIGGER_FILE, WIN_STATUS_FILE, WIN_CHOICE_FILE, WIN_PING_FILE,
    WIN_SHARE_PATH,
)

POLL_INTERVAL       = 3
PING_WAIT           = 15
PING_CHECK_INTERVAL = 30
PING_CHECK_TIMEOUT  = 15
WIN_LOG_FILE        = str(Path(WIN_SHARE_PATH) / "watcher.log")

# =============================================================================
# Helpers
# =============================================================================

def _write_json(path, data):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(p)


def _read_json(path):
    p = Path(path)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def _clear_files():
    for f in [WIN_STATUS_FILE, WIN_CHOICE_FILE, WIN_TRIGGER_FILE, WIN_PING_FILE]:
        p = Path(f)
        try:
            if p.exists():
                p.unlink()
                print("[BUILD] Cleared stale file: {}".format(p.name))
        except Exception:
            pass


def _render_progress(progress):
    pct   = progress.get("pct", 0)
    done  = progress.get("done", 0)
    total = progress.get("total", 0)
    width = 35
    filled = int(width * pct / 100)
    bar = "#" * filled + "-" * (width - filled)
    return "[{}] {:3d}%  {}/{}".format(bar, pct, done, total)

# =============================================================================
# Ping
# =============================================================================

def _do_ping(timeout):
    ping_path = Path(WIN_PING_FILE)
    try:
        if ping_path.exists():
            ping_path.unlink()
    except Exception:
        pass
    _write_json(WIN_PING_FILE, {
        "ping": True,
        "sent_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    })
    deadline = time.time() + timeout
    while time.time() < deadline:
        time.sleep(1)
        if not ping_path.exists():
            return True
    try:
        ping_path.unlink()
    except Exception:
        pass
    return False


def check_watcher_alive():
    print("[BUILD] Checking watcher status (ping) ...")
    if _do_ping(PING_WAIT):
        print("[BUILD] Watcher alive.")
        return True
    print("[BUILD] ERROR: watcher did not respond within {}s.".format(PING_WAIT))
    print("        Please start watcher on the Server:")
    print("        python3 -u /path/to/share_dir/watcher.py &")
    return False

# =============================================================================
# Background threads
# =============================================================================

def _start_liveness_monitor(stop_event, dead_event):
    def _monitor():
        while not stop_event.is_set():
            for _ in range(PING_CHECK_INTERVAL):
                if stop_event.is_set():
                    return
                time.sleep(1)
            if stop_event.is_set():
                return
            if not _do_ping(PING_CHECK_TIMEOUT):
                dead_event.set()
                return
    t = threading.Thread(target=_monitor, daemon=True)
    t.start()
    return t


def _start_log_tail(stop_event):
    def _tail():
        log_path = Path(WIN_LOG_FILE)
        for _ in range(30):
            if log_path.exists():
                break
            time.sleep(1)
        if not log_path.exists():
            return
        with open(log_path, "r", encoding="utf-8", errors="replace") as f:
            f.seek(0, 2)
            while not stop_event.is_set():
                line = f.readline()
                if line:
                    sys.stdout.write("[LOG] {}\n".format(line.rstrip()))
                    sys.stdout.flush()
                else:
                    time.sleep(0.3)
    t = threading.Thread(target=_tail, daemon=True)
    t.start()
    return t

# =============================================================================
# Main build trigger
# =============================================================================

def trigger_build(verbose=True, retries=None):
    if not check_watcher_alive():
        return False

    _clear_files()

    stop_event = threading.Event()
    dead_event = threading.Event()
    _start_log_tail(stop_event)
    _start_liveness_monitor(stop_event, dead_event)
    print("[BUILD] Watcher liveness monitor started (check every {}s).".format(PING_CHECK_INTERVAL))
    print("[BUILD] Log tail started.")
    print()

    _retries = retries if retries is not None else _config.BUILD_IMG_RETRIES
    trigger = {
        "build_cmd":   _config.BUILD_CMD,
        "build_type":  _config.BUILD_TYPE,
        "cp_cmd":      _config.CP_CMD,
        "cp_choice":   _config.CP_CHOICE,
        "max_retries": _retries,
    }
    print("[BUILD] Writing trigger -> {}".format(WIN_TRIGGER_FILE))
    _write_json(WIN_TRIGGER_FILE, trigger)
    print("[BUILD] Trigger sent.")
    print()

    start         = time.time()
    last_progress = None
    in_progress   = False

    try:
        while True:
            time.sleep(POLL_INTERVAL)

            if dead_event.is_set():
                if in_progress:
                    sys.stdout.write("\n")
                    in_progress = False
                print("\n[BUILD] ERROR: watcher stopped responding during build!")
                print("        Build aborted. Please check watcher on the Server.")
                return False

            data = _read_json(WIN_STATUS_FILE)

            if data is None:
                elapsed = time.time() - start
                if elapsed > 30:
                    sys.stdout.write("\r[BUILD] Waiting for watcher ... ({:.0f}s)  ".format(elapsed))
                    sys.stdout.flush()
                continue

            status    = data.get("status", "")
            last_line = data.get("last_line", "")
            error     = data.get("error", "")
            message   = data.get("message", "")
            updated   = data.get("updated_at", "")
            progress  = data.get("progress")

            if status == "building":
                if progress:
                    sys.stdout.write("\r[PROGRESS] {}  {}  ".format(
                        _render_progress(progress), updated))
                    sys.stdout.flush()
                    last_progress = progress
                    in_progress = True

            elif status == "copying":
                if in_progress:
                    sys.stdout.write("\r[PROGRESS] {}  done\n".format(
                        _render_progress(last_progress) if last_progress else ""))
                    in_progress = False

            elif status == "waiting_choice":
                if in_progress:
                    sys.stdout.write("\n")
                    in_progress = False
                if _config.CP_CHOICE is not None:
                    print("[COPY] Auto-reply: {!r}".format(_config.CP_CHOICE))
                    _write_json(WIN_CHOICE_FILE, {"choice": _config.CP_CHOICE})
                else:
                    print("\n[COPY] cp script is waiting for your input.")
                    choice = input("[COPY] Enter your choice: ").strip()
                    _write_json(WIN_CHOICE_FILE, {"choice": choice})
                    print("[COPY] Choice {!r} sent.".format(choice))

            elif status == "done":
                if in_progress:
                    sys.stdout.write("\r[PROGRESS] {}  done\n".format(
                        _render_progress(last_progress) if last_progress else ""))
                    in_progress = False
                elapsed = time.time() - start
                print("[BUILD] Build and copy completed in {:.0f}s".format(elapsed))
                return True

            elif status == "error":
                if in_progress:
                    sys.stdout.write("\n")
                    in_progress = False
                elapsed = time.time() - start
                print("[BUILD] Failed after {:.0f}s: {}".format(elapsed, error or message))
                return False

            pass  # no business timeout

    finally:
        stop_event.set()


if __name__ == "__main__":
    ok = trigger_build()
    sys.exit(0 if ok else 1)