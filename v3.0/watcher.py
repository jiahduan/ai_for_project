#!/usr/bin/env python3
# =============================================================================
# watcher.py -- Run on BUILD SERVER
#
# Usage:
#   python3 -u /path/to/share_dir/watcher.py &   (share_dir = server_share_path in project.json)
#
# Log is written to SHARE_DIR/watcher.log so Windows can tail it in real time.
# =============================================================================

import json
import re
import shutil
import subprocess
import sys
import time
import threading
from datetime import datetime
from pathlib import Path

# =============================================================================
# Configuration
# =============================================================================
# -- Load shared config from project.json (lives in same dir as watcher.py) --
_SCRIPT_DIR = Path(__file__).resolve().parent
_proj_file  = _SCRIPT_DIR / "project.json"
if not _proj_file.exists():
    sys.stderr.write("ERROR: project.json not found: {}\n".format(_proj_file))
    sys.exit(1)
_proj = json.loads(_proj_file.read_text(encoding="utf-8"))

# From project.json -- shared with config.py / cp_images.sh / sync_and_build_ok.sh
SHARE_DIR        = Path(_proj["server_share_path"])
LOCAL_STATUS_DIR = Path(_proj["project_root"])

# Derived paths
TRIGGER_FILE      = SHARE_DIR / "trigger.json"
CHOICE_FILE       = SHARE_DIR / "trigger_choice.json"
PING_FILE         = SHARE_DIR / "ping.json"
LOG_FILE          = SHARE_DIR / "watcher.log"
LOCAL_STATUS_FILE = LOCAL_STATUS_DIR / "status.json"
SHARE_STATUS_FILE = SHARE_DIR / "status.json"

# Server-side tuning (not shared)
BITBAKE_RECONNECT_KEYWORD = "Reconnecting to bitbake server"
BUILD_MAX_RETRIES         = 3
POLL_INTERVAL             = 3
PROMPT_KEYWORD            = "Select ["   # matches cp_images.sh: read -rp "Select [0-N]: "

_NINJA_RE = re.compile(r"\[\s*(\d+)%\s+(\d+)/(\d+)\]")

# =============================================================================
# Log: write to both stdout and shared log file
# =============================================================================
_log_lock = threading.Lock()
_log_fh   = None

def _open_log():
    global _log_fh
    try:
        _log_fh = open(LOG_FILE, "a", encoding="utf-8", buffering=1)
    except Exception as e:
        sys.stdout.write("WARNING: cannot open log file {}: {}\n".format(LOG_FILE, e))
        sys.stdout.flush()

def log(msg):
    line = "[{}] {}\n".format(datetime.now().strftime("%H:%M:%S"), msg)
    with _log_lock:
        sys.stdout.write(line)
        sys.stdout.flush()
        if _log_fh:
            try:
                _log_fh.write(line)
                _log_fh.flush()
            except Exception:
                pass

# =============================================================================
# Helpers
# =============================================================================

def _safe_unlink(path):
    try:
        path.unlink()
        return True
    except Exception:
        return False


def write_status(status, message="", last_line="", error="", progress=None):
    data = {
        "status":     status,
        "message":    message,
        "last_line":  last_line,
        "error":      error,
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    if progress is not None:
        data["progress"] = progress
    try:
        tmp = LOCAL_STATUS_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(LOCAL_STATUS_FILE)
        shutil.copy2(LOCAL_STATUS_FILE, SHARE_STATUS_FILE)
    except Exception:
        pass


def parse_progress(line):
    m = _NINJA_RE.search(line)
    if m:
        return {"pct": int(m.group(1)), "done": int(m.group(2)), "total": int(m.group(3))}
    return None


def _clean_bitbake_files(distro_dir):
    """
    Remove bitbake lock files and clean any in-progress task stamps
    that may have been left in a corrupt state by a forced reconnect.
    """
    # 1. Remove bitbake lock files
    pattern = str(distro_dir / "bitbake*")
    log("Cleaning bitbake lock files: {}".format(pattern))
    try:
        result = subprocess.run(
            ["bash", "-c", "rm -f {}".format(pattern)],
            capture_output=True, text=True
        )
        if result.returncode == 0:
            log("Bitbake lock files removed.")
        else:
            log("WARNING: rm bitbake* returned {}: {}".format(
                result.returncode, result.stderr.strip()))
    except Exception as e:
        log("ERROR cleaning bitbake lock files: {}".format(e))

    # 2. Remove in-progress setscene/task stamps that may be corrupt
    #    These are left behind when bitbake is killed mid-task
    tmp_dir = distro_dir / "tmp-glibc"
    stamp_pattern = str(tmp_dir / "stamps" / "**" / "*.do_*_setscene")
    lock_pattern  = str(tmp_dir / "**" / "*.lock")
    log("Cleaning in-progress stamps under: {}".format(tmp_dir))
    try:
        cmd = (
            "find {tmp} -maxdepth 6 -name '*.do_unpack' -newer {bb} -delete 2>/dev/null; "
            "find {tmp} -maxdepth 6 -name '*.do_fetch' -newer {bb} -delete 2>/dev/null; "
            "find {tmp} -maxdepth 8 -name '*.lock' -delete 2>/dev/null || true"
        ).format(tmp=str(tmp_dir), bb=pattern.replace("*", "server"))
        subprocess.run(["bash", "-c", cmd], capture_output=True, text=True)
        log("In-progress stamps cleaned.")
    except Exception as e:
        log("WARNING: stamp cleanup error: {}".format(e))

# =============================================================================
# Run command
# Returns: (success: bool, last_line: str, bitbake_reconnect: bool)
# =============================================================================

def run_cmd(cmd, cp_choice=None, label="CMD", detect_bitbake=False):
    if not cmd or not cmd.strip():
        log("[{}] No command specified, skipping.".format(label))
        return True, "", False

    log("[{}] Running: {}".format(label, cmd))

    # Run directly with bash; stdbuf is unreliable on this Server environment.
    # Use PYTHONUNBUFFERED + bash -u for line-buffered output.
    import os as _os
    _env = _os.environ.copy()
    _env["SHARE_DIR"]        = str(SHARE_DIR)
    _env["PYTHONUNBUFFERED"] = "1"
    if cp_choice is not None:
        _env["CP_CHOICE"] = str(cp_choice)
    proc = subprocess.Popen(
        ["bash", "-c", cmd],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        bufsize=0,
        env=_env,
    )

    last_line         = ""
    last_progress     = None
    choice_sent       = False
    bitbake_reconnect = False

    def _read_output():
        nonlocal last_line, last_progress, choice_sent, bitbake_reconnect
        for raw in iter(proc.stdout.readline, b""):
            line = raw.decode("utf-8", errors="replace").rstrip()
            if not line:
                continue
            last_line = line
            log("[{}] {}".format(label, line))

            # Detect bitbake reconnect -- only for img build
            if detect_bitbake and BITBAKE_RECONNECT_KEYWORD.lower() in line.lower():
                bitbake_reconnect = True
                log("[{}] Detected '{}', killing build ...".format(
                    label, BITBAKE_RECONNECT_KEYWORD))
                proc.kill()
                return

            progress = parse_progress(line)
            if progress:
                last_progress = progress
                write_status("building", last_line=line, progress=progress)
            else:
                write_status(
                    "building" if label == "BUILD" else "copying",
                    last_line=line, progress=last_progress,
                )

            if (label == "COPY"
                    and not choice_sent
                    and PROMPT_KEYWORD in line):
                if cp_choice is not None:
                    log("[{}] Auto-reply: {!r}".format(label, cp_choice))
                    proc.stdin.write((str(cp_choice) + "\n").encode())
                    proc.stdin.flush()
                    choice_sent = True
                else:
                    log("[{}] Waiting for choice from Windows ...".format(label))
                    write_status("waiting_choice", message="Waiting for cp choice input")
                    deadline = time.time() + 120
                    while time.time() < deadline:
                        if CHOICE_FILE.exists():
                            try:
                                data = json.loads(CHOICE_FILE.read_text(encoding="utf-8"))
                                choice = str(data.get("choice", "")).strip()
                                if choice:
                                    log("[{}] Got choice: {!r}".format(label, choice))
                                    proc.stdin.write((choice + "\n").encode())
                                    proc.stdin.flush()
                                    _safe_unlink(CHOICE_FILE)
                                    choice_sent = True
                                    break
                            except Exception:
                                pass
                        time.sleep(1)
                    if not choice_sent:
                        log("[{}] Timeout waiting for choice, sending empty.".format(label))
                        proc.stdin.write(b"\n")
                        proc.stdin.flush()
                        choice_sent = True

    reader = threading.Thread(target=_read_output, daemon=True)
    reader.start()

    proc.wait()   # no timeout -- run until process exits naturally

    reader.join(timeout=5)
    success = proc.returncode == 0 and not bitbake_reconnect
    log("[{}] Exit code: {}  bitbake_reconnect: {}".format(
        label, proc.returncode, bitbake_reconnect))
    return success, last_line, bitbake_reconnect


# =============================================================================
# Trigger handler
# =============================================================================


def handle_trigger(trigger):
    build_cmd   = trigger.get("build_cmd")
    cp_cmd      = trigger.get("cp_cmd")
    cp_choice   = trigger.get("cp_choice")
    build_type  = trigger.get("build_type", "debug")
    max_retries = int(trigger.get("max_retries", BUILD_MAX_RETRIES))
    distro_dir    = LOCAL_STATUS_DIR / "build-qti-distro-fullstack-{}".format(build_type)

    # Ensure sh files are executable every time a trigger is received
    # project_root from trigger ensures we cp to the correct (latest) workspace
    _ensure_sh_executable(project_root=trigger.get("project_root"))

    log("Trigger received.")
    log("  build_cmd  : {}".format(build_cmd))
    log("  cp_cmd     : {}".format(cp_cmd))
    log("  build_type : {}  distro_dir: {}".format(build_type, distro_dir))

    # Retry loop: only for img build (cp_cmd present); others run once
    _max_retries = max_retries if (cp_cmd and cp_cmd.strip()) else 1
    for attempt in range(1, _max_retries + 1):
        if attempt > 1:
            log("=" * 40)
            log("Build attempt {}/{} ...".format(attempt, max_retries))
            log("=" * 40)

        write_status("building", message="Build started (attempt {}/{})".format(
            attempt, max_retries))

        build_ok, last_line, bitbake_reconnect = run_cmd(
            build_cmd, label="BUILD",
            detect_bitbake=bool(cp_cmd and cp_cmd.strip()),
        )

        if bitbake_reconnect:
            log("Bitbake reconnect detected on attempt {}/{}.".format(
                attempt, max_retries))
            if attempt < max_retries:
                _clean_bitbake_files(distro_dir)
                log("Retrying build in 5s ...")
                write_status("building",
                             message="Bitbake reconnect, retrying ({}/{}) ...".format(
                                 attempt, max_retries))
                time.sleep(5)
                continue
            else:
                log("Max retries ({}) reached. Build FAILED.".format(max_retries))
                write_status("error",
                             message="Build failed: bitbake reconnect, max retries exceeded",
                             last_line=last_line,
                             error="Bitbake reconnect: max retries ({}) exceeded".format(
                                 max_retries))
                return

        if not build_ok:
            write_status("error", message="Build failed", last_line=last_line,
                         error="Build command returned non-zero exit code")
            log("Build FAILED.")
            return

        log("Build succeeded on attempt {}/{}.".format(attempt, max_retries))
        break

    # Copy images (only when cp_cmd is provided)
    if cp_cmd and cp_cmd.strip():
        log("Starting copy ...")
        write_status("copying", message="Copying images to shared path")
        copy_ok, last_line, _ = run_cmd(
            cp_cmd, cp_choice=cp_choice, label="COPY",
        )
        if not copy_ok:
            write_status("error", message="Copy failed", last_line=last_line,
                         error="cp script returned non-zero exit code")
            log("Copy FAILED.")
            return
        log("Copy completed.")
    else:
        log("No cp_cmd provided -- build step only, image copy not required.")

    write_status("done", message="Completed successfully")
    log("All done.")

# =============================================================================
# Script handler -- lightweight direct execution, no retry / no bitbake logic
# =============================================================================

def handle_script(trigger):
    """
    Execute a single shell script directly.
    Used for cp_download and other non-build operations.
    No retry loop, no bitbake reconnect detection.
    """
    script_cmd = trigger.get("script_cmd", "")
    if not script_cmd or not script_cmd.strip():
        log("handle_script: script_cmd is empty, nothing to do.")
        write_status("error", error="script_cmd is empty")
        return

    _ensure_sh_executable(project_root=trigger.get("project_root"))
    log("Script trigger received.")
    log("  script_cmd : {}".format(script_cmd))

    write_status("building", message="Running script ...")
    ok, last_line, _ = run_cmd(script_cmd, label="SCRIPT")

    if not ok:
        write_status("error", message="Script failed", last_line=last_line,
                     error="Script returned non-zero exit code")
        log("Script FAILED.")
        return

    write_status("done", message="Script completed successfully")
    log("Script done.")

# =============================================================================
# Ping responder (independent thread)
# =============================================================================

def _ping_responder_loop():
    while True:
        try:
            if PING_FILE.exists():
                _safe_unlink(PING_FILE)
                log("Ping received and consumed.")
        except Exception:
            pass
        time.sleep(1)

# =============================================================================
# Entry point
# =============================================================================

def _get_project_root():
    """Read project_root fresh from project.json every time.
    This ensures we always use the latest workspace after sync.
    """
    try:
        proj = json.loads(_proj_file.read_text(encoding="utf-8"))
        return Path(proj["project_root"])
    except Exception as e:
        log("[PROJ] WARNING: could not read project_root: {}".format(e))
        return LOCAL_STATUS_DIR


def _ensure_sh_executable(project_root=None):
    """
    Copy all .sh files from SHARE_DIR to project_root, then chmod +x.
    project_root: use directly if provided (from trigger), else read from project.json.
    """
    import shutil as _shutil, stat as _stat
    target_dir = Path(project_root) if project_root else _get_project_root()
    log("[DEPLOY_SH] target_dir: {}".format(target_dir))
    sh_files = list(SHARE_DIR.glob("*.sh"))
    if not sh_files:
        log("[DEPLOY_SH] No .sh files found in {}".format(SHARE_DIR))
        return
    target_dir.mkdir(parents=True, exist_ok=True)
    for sh in sh_files:
        dst = target_dir / sh.name
        try:
            _shutil.copy2(str(sh), str(dst))
            mode = dst.stat().st_mode
            new_mode = mode | _stat.S_IXUSR | _stat.S_IXGRP | _stat.S_IXOTH
            dst.chmod(new_mode)
            log("[DEPLOY_SH] {} -> {} (+x)".format(sh.name, dst))
        except Exception as e:
            log("[DEPLOY_SH] WARNING: could not deploy {}: {}".format(sh.name, e))


def main():
    LOCAL_STATUS_DIR.mkdir(parents=True, exist_ok=True)
    _open_log()

    _ensure_sh_executable()

    log("=" * 60)
    log("Watcher started.")
    log("  [CONFIG] project.json    : {}".format(_proj_file))
    log("  [CONFIG] SHARE_DIR       : {}".format(SHARE_DIR))
    log("  [CONFIG] LOCAL_STATUS_DIR: {}".format(LOCAL_STATUS_DIR))
    log("  Trigger    : {}".format(TRIGGER_FILE))
    log("  Ping       : {}".format(PING_FILE))
    log("  Log        : {}".format(LOG_FILE))
    log("  Status     : {} (copy -> {})".format(LOCAL_STATUS_FILE, SHARE_STATUS_FILE))
    log("  Max retries: {}".format(BUILD_MAX_RETRIES))
    log("  Polling every {}s ...".format(POLL_INTERVAL))
    log("=" * 60)

    ping_thread = threading.Thread(target=_ping_responder_loop, daemon=True)
    ping_thread.start()
    log("Ping responder thread started.")

    stale = [TRIGGER_FILE, CHOICE_FILE, PING_FILE]
    for f in stale:
        if f.exists():
            if _safe_unlink(f):
                log("Cleaned up stale file: {}".format(f.name))

    write_status("idle", message="Watcher started, waiting for trigger")

    while True:
        try:
            if TRIGGER_FILE.exists():
                try:
                    trigger = json.loads(TRIGGER_FILE.read_text(encoding="utf-8"))
                except Exception as e:
                    log("Failed to read trigger.json: {}".format(e))
                    _safe_unlink(TRIGGER_FILE)
                    time.sleep(POLL_INTERVAL)
                    continue

                _safe_unlink(TRIGGER_FILE)
                log("trigger.json consumed and deleted.")

                if trigger.get("script_cmd"):
                    handle_script(trigger)
                else:
                    handle_trigger(trigger)

                # Hold done/error long enough for Windows to poll it.
                # POLL_INTERVAL=3s, sleep 10s guarantees at least 2 polls.
                time.sleep(10)

                write_status("idle", message="Watcher ready, waiting for next trigger")
                log("Back to idle, waiting for next trigger ...")

        except Exception as e:
            log("Unexpected error: {}".format(e))
            write_status("error", error=str(e))

        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()