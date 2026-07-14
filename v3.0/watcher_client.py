# =============================================================================
# watcher_client.py -- Shared helpers for communicating with watcher.py
#
# Used by: sync_code.py / build_abl.py / build_kernel.py / build.py
# Provides: ping, log-tail, liveness-monitor, trigger, poll-status
# =============================================================================

import json
import sys
import time
import threading
from datetime import datetime
from pathlib import Path

from config import (
    WIN_TRIGGER_FILE, WIN_STATUS_FILE, WIN_PING_FILE,
    WIN_SHARE_PATH, BUILD_TYPE,
)

POLL_INTERVAL       = 3
PING_WAIT           = 15
PING_CHECK_INTERVAL = 30
PING_CHECK_TIMEOUT  = 15
WIN_LOG_FILE        = str(Path(WIN_SHARE_PATH) / "watcher.log")

# =============================================================================
# JSON helpers
# =============================================================================

def write_json(path, data):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(p)


def read_json(path):
    p = Path(path)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def clear_files(label=""):
    for f in [WIN_STATUS_FILE, WIN_TRIGGER_FILE, WIN_PING_FILE]:
        p = Path(f)
        try:
            if p.exists():
                p.unlink()
                print("[{}] Cleared stale file: {}".format(label, p.name))
        except Exception:
            pass

# =============================================================================
# Ping
# =============================================================================

def do_ping(timeout):
    ping_path = Path(WIN_PING_FILE)
    try:
        if ping_path.exists():
            ping_path.unlink()
    except Exception:
        pass
    write_json(WIN_PING_FILE, {
        "ping":    True,
        "sent_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
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


def check_watcher_alive(label="CLIENT"):
    print("[{}] Checking watcher status (ping) ...".format(label))
    if do_ping(PING_WAIT):
        print("[{}] Watcher alive.".format(label))
        return True
    print("[{}] ERROR: watcher did not respond within {}s.".format(label, PING_WAIT))
    print("       Please start watcher on the Server:")
    print("       python3 -u /path/to/share_dir/watcher.py &")
    return False

# =============================================================================
# Background threads
# =============================================================================

def start_liveness_monitor(stop_event, dead_event):
    def _monitor():
        while not stop_event.is_set():
            for _ in range(PING_CHECK_INTERVAL):
                if stop_event.is_set():
                    return
                time.sleep(1)
            if stop_event.is_set():
                return
            if not do_ping(PING_CHECK_TIMEOUT):
                dead_event.set()
                return
    t = threading.Thread(target=_monitor, daemon=True)
    t.start()
    return t


def start_log_tail(stop_event):
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
# Core: send script trigger and poll until done (no build/cp split)
# =============================================================================

def run_script(label, cmd, project_root=None):
    """
    Send a script_cmd trigger to watcher and poll until done/error.
    Lightweight path: no retry, no bitbake, no cp_cmd.
    Returns True on success, False on failure.
    label : prefix for print messages
    cmd   : shell script command to execute on Server
    """
    if not check_watcher_alive(label):
        return False

    clear_files(label)

    stop_event = threading.Event()
    dead_event = threading.Event()
    start_log_tail(stop_event)
    start_liveness_monitor(stop_event, dead_event)
    print("[{}] Liveness monitor started.".format(label))
    print("[{}] Log tail started.".format(label))
    print()

    trigger = {
        "script_cmd": cmd,
    }
    if project_root is not None:
        trigger["project_root"] = project_root
    print("[{}] Command : {}".format(label, cmd))
    print("[{}] Writing trigger -> {}".format(label, WIN_TRIGGER_FILE))
    write_json(WIN_TRIGGER_FILE, trigger)
    print("[{}] Trigger sent. Waiting ...".format(label))
    print()

    start           = time.time()
    first_status_at = None
    FIRST_STATUS_TIMEOUT = 120

    try:
        while True:
            time.sleep(POLL_INTERVAL)

            if dead_event.is_set():
                print("\n[{}] ERROR: watcher stopped responding!".format(label))
                return False

            data = read_json(WIN_STATUS_FILE)
            if data is None:
                elapsed = time.time() - start
                if elapsed > 30:
                    sys.stdout.write("\r[{}] Waiting for watcher ... ({:.0f}s)  ".format(
                        label, elapsed))
                    sys.stdout.flush()
                if first_status_at is None and elapsed > FIRST_STATUS_TIMEOUT:
                    print("\n[{}] ERROR: watcher did not respond within {}s.".format(
                        label, FIRST_STATUS_TIMEOUT))
                    return False
                continue

            if first_status_at is None:
                first_status_at = time.time()

            status  = data.get("status", "")
            error   = data.get("error", "")
            message = data.get("message", "")

            if status == "building":
                pass   # script running, shown via log tail

            elif status == "done":
                elapsed = time.time() - start
                print("[{}] Completed in {:.0f}s".format(label, elapsed))
                return True

            elif status == "error":
                elapsed = time.time() - start
                print("[{}] Failed after {:.0f}s: {}".format(
                    label, elapsed, error or message))
                return False

    finally:
        stop_event.set()

# =============================================================================
# Core: send trigger and poll until done
# =============================================================================

def run_trigger(label, cmd, project_root=None):
    """
    Send a trigger to watcher and poll until done/error.
    Returns True on success, False on failure.
    label : prefix for print messages, e.g. "SYNC" / "ABL" / "KERNEL"
    cmd   : shell command watcher will execute
    """
    if not check_watcher_alive(label):
        return False

    clear_files(label)

    stop_event = threading.Event()
    dead_event = threading.Event()
    start_log_tail(stop_event)
    start_liveness_monitor(stop_event, dead_event)
    print("[{}] Liveness monitor started.".format(label))
    print("[{}] Log tail started.".format(label))
    print()

    trigger = {
        "build_cmd":  cmd,
        "build_type": BUILD_TYPE,
    }
    if project_root is not None:
        trigger["project_root"] = project_root
    print("[{}] Command : {}".format(label, cmd))
    print("[{}] Writing trigger -> {}".format(label, WIN_TRIGGER_FILE))
    write_json(WIN_TRIGGER_FILE, trigger)
    print("[{}] Trigger sent. Waiting ...".format(label))
    print()

    start           = time.time()
    first_status_at = None   # time when status.json first appeared
    # How long to wait for watcher to write the first status.json.
    # Independent of build timeout: guards against watcher never starting.
    FIRST_STATUS_TIMEOUT = 120

    try:
        while True:
            time.sleep(POLL_INTERVAL)

            if dead_event.is_set():
                print("\n[{}] ERROR: watcher stopped responding!".format(label))
                return False

            data = read_json(WIN_STATUS_FILE)
            if data is None:
                elapsed = time.time() - start
                if elapsed > 30:
                    sys.stdout.write("\r[{}] Waiting for watcher ... ({:.0f}s)  ".format(
                        label, elapsed))
                    sys.stdout.flush()
                if first_status_at is None and elapsed > FIRST_STATUS_TIMEOUT:
                    print("\n[{}] ERROR: watcher did not respond within {}s.".format(
                        label, FIRST_STATUS_TIMEOUT))
                    print("[{}]         Check watcher is running on the Server.".format(label))
                    return False
                continue

            if first_status_at is None:
                first_status_at = time.time()

            status  = data.get("status", "")
            error   = data.get("error", "")
            message = data.get("message", "")

            if status in ("building", "copying"):
                pass   # progress shown via log tail

            elif status == "done":
                elapsed = time.time() - start
                print("[{}] Completed in {:.0f}s".format(label, elapsed))
                return True

            elif status == "error":
                elapsed = time.time() - start
                print("[{}] Failed after {:.0f}s: {}".format(
                    label, elapsed, error or message))
                return False

            pass  # no business timeout; run until done/error/heartbeat-fail

    finally:
        stop_event.set()