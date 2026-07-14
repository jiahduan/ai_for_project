# =============================================================================
# ota_flash_verify.py -- Push OTA zip, trigger recovery update, verify slot switch
#
# Usage:
#   python ota_flash_verify.py --zip <path\to\full_update_ext4.zip>
#   python ota_flash_verify.py --zip <path> --serial <device_serial>
#
# Steps:
#   1. adb push <zip> /data/full_update_ext4.zip
#   2. adb shell echo "--update_package=..." > /cache/recovery/command
#   3. adb shell /usr/bin/recovery --update_package=...
#   4. adb shell cat /tmp/recovery.log
#   5. adb shell abctl --boot_slot          (slot BEFORE reboot)
#   6. adb reboot
#   7. wait for device to come back online
#   8. adb shell abctl --boot_slot          (slot AFTER reboot, verify switch)
#
# All output is saved to LOG_DIR/ota_<timestamp>/ota.log
# =============================================================================

import argparse
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

from config import ADB_PATH, DEVICE_SERIAL, LOG_DIR

# =============================================================================
# Config
# =============================================================================

DEVICE_ZIP_PATH     = "/data/full_update_ext4.zip"
RECOVERY_CMD_FILE   = "/cache/recovery/command"
RECOVERY_BIN        = "/usr/bin/recovery"
RECOVERY_LOG        = "/tmp/recovery.log"

PUSH_TIMEOUT        = 300    # 5 min  -- large zip
RECOVERY_TIMEOUT    = 600    # 10 min -- recovery update
REBOOT_WAIT_TIMEOUT = 300    # 5 min  -- wait for device online after reboot
REBOOT_POLL         = 5      # poll interval (s)

# =============================================================================
# Logger -- writes to stdout AND log file simultaneously
# =============================================================================

class Tee:
    def __init__(self, log_path):
        self._log = open(log_path, "w", encoding="utf-8", buffering=1)
        self._stdout = sys.stdout

    def write(self, msg):
        self._stdout.write(msg)
        self._stdout.flush()
        self._log.write(msg)
        self._log.flush()

    def flush(self):
        self._stdout.flush()
        self._log.flush()

    def close(self):
        self._log.close()

    # make it usable as context manager
    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


def _ts():
    return datetime.now().strftime("%H:%M:%S")


def log(msg, tee=None):
    line = "[{}] {}".format(_ts(), msg)
    if tee:
        tee.write(line + "\n")
    else:
        print(line)

# =============================================================================
# ADB helpers
# =============================================================================

def _adb_base(serial):
    cmd = [ADB_PATH]
    if serial:
        cmd += ["-s", serial]
    return cmd


def run(cmd, tee, timeout=60, check=False):
    """Run command, stream output to tee, return (returncode, stdout_text)."""
    log("$ {}".format(" ".join(str(c) for c in cmd)), tee)
    out_lines = []
    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        try:
            stdout, _ = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
            stdout, _ = proc.communicate()
            log("  [TIMEOUT] command exceeded {}s".format(timeout), tee)
            return proc.returncode, stdout or ""

        for line in stdout.splitlines():
            log("  {}".format(line), tee)
            out_lines.append(line)

        rc = proc.returncode
        log("  [exit {}]".format(rc), tee)
        if check and rc != 0:
            raise RuntimeError("Command failed (exit {}): {}".format(rc, " ".join(str(c) for c in cmd)))
        return rc, stdout

    except FileNotFoundError:
        log("  [ERROR] adb not found: {}".format(ADB_PATH), tee)
        return -1, ""


def adb_shell(serial, shell_cmd, tee, timeout=60, check=False):
    return run(_adb_base(serial) + ["shell", shell_cmd], tee, timeout=timeout, check=check)


def wait_for_device(serial, tee, timeout=REBOOT_WAIT_TIMEOUT):
    """Use adb wait-for-device then verify shell is responsive."""
    log("Waiting for device (adb wait-for-device, max {}s) ...".format(timeout), tee)
    rc, _ = run(
        _adb_base(serial) + ["wait-for-device"],
        tee, timeout=timeout,
    )
    if rc != 0:
        log("[ERROR] adb wait-for-device failed (exit {}).".format(rc), tee)
        return False
    # wait-for-device returns as soon as USB is detected (may still be booting)
    # do a quick shell ping to confirm shell is up
    log("Device detected, verifying shell is responsive ...", tee)
    deadline = time.time() + 60
    while time.time() < deadline:
        rc2, out = run(
            _adb_base(serial) + ["shell", "echo", "ping"],
            tee=None,
            timeout=10,
        )
        if rc2 == 0 and "ping" in out:
            log("Device shell is responsive.", tee)
            return True
        time.sleep(REBOOT_POLL)
    log("[ERROR] Device shell did not respond after wait-for-device.", tee)
    return False

# =============================================================================
# OTA steps
# =============================================================================

def step_push(serial, zip_path, tee):
    log("=" * 60, tee)
    log("Step 1: adb push OTA zip -> {}".format(DEVICE_ZIP_PATH), tee)
    log("=" * 60, tee)
    rc, _ = run(
        _adb_base(serial) + ["push", str(zip_path), DEVICE_ZIP_PATH],
        tee, timeout=PUSH_TIMEOUT,
    )
    return rc == 0


def step_write_recovery_cmd(serial, tee):
    log("=" * 60, tee)
    log("Step 2: Write recovery command file", tee)
    log("=" * 60, tee)
    cmd = "echo '--update_package={}' > {}".format(DEVICE_ZIP_PATH, RECOVERY_CMD_FILE)
    rc, _ = adb_shell(serial, cmd, tee)
    return rc == 0


def step_run_recovery(serial, tee):
    log("=" * 60, tee)
    log("Step 3: Run recovery update", tee)
    log("=" * 60, tee)
    cmd = "{} --update_package={}".format(RECOVERY_BIN, DEVICE_ZIP_PATH)
    rc, _ = adb_shell(serial, cmd, tee, timeout=RECOVERY_TIMEOUT)
    # recovery may return non-zero even on success; we check log in next step
    return rc == 0


def step_cat_recovery_log(serial, tee):
    log("=" * 60, tee)
    log("Step 4: cat {}".format(RECOVERY_LOG), tee)
    log("=" * 60, tee)
    rc, out = adb_shell(serial, "cat {}".format(RECOVERY_LOG), tee, timeout=30)
    # check for success/failure keywords in recovery log
    out_lower = out.lower()
    if "installation aborted" in out_lower or "error" in out_lower:
        log("[WARN] Recovery log contains error indicators.", tee)
    if "installation complete" in out_lower or "done" in out_lower:
        log("[INFO] Recovery log indicates success.", tee)
    return rc == 0, out


def step_get_slot(serial, tee, label):
    log("=" * 60, tee)
    log("Step {}: abctl --boot_slot ({})".format("5" if label == "before" else "8", label), tee)
    log("=" * 60, tee)
    rc, out = adb_shell(serial, "abctl --boot_slot", tee, timeout=15)
    slot = out.strip().splitlines()[-1].strip() if out.strip() else "unknown"
    log("[SLOT {}] {}".format(label.upper(), slot), tee)
    return slot


def step_reboot(serial, tee):
    log("=" * 60, tee)
    log("Step 6: adb reboot", tee)
    log("=" * 60, tee)
    rc, _ = run(_adb_base(serial) + ["reboot"], tee, timeout=15)
    time.sleep(3)   # brief pause before polling
    return rc == 0


def step_wait_online(serial, tee):
    log("=" * 60, tee)
    log("Step 7: Wait for device online", tee)
    log("=" * 60, tee)
    return wait_for_device(serial, tee)

# =============================================================================
# Main
# =============================================================================

def run_ota_flash_verify(zip_path, serial=None):
    ts       = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_dir  = Path(LOG_DIR) / "ota_{}".format(ts)
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "ota.log"

    print("[OTA] Log dir  : {}".format(log_dir))
    print("[OTA] Log file : {}".format(log_file))
    print("[OTA] OTA zip  : {}".format(zip_path))
    print("[OTA] Serial   : {}".format(serial or "default"))
    print()

    results = {}

    with Tee(str(log_file)) as tee:
        log("OTA Flash & Verify", tee)
        log("Started  : {}".format(datetime.now().strftime("%Y-%m-%d %H:%M:%S")), tee)
        log("OTA zip  : {}".format(zip_path), tee)
        log("Serial   : {}".format(serial or "default"), tee)
        log("Log file : {}".format(log_file), tee)

        # Step 1: push
        ok = step_push(serial, zip_path, tee)
        results["push"] = ok
        if not ok:
            log("[ABORT] Push failed.", tee)
            return _summary(results, log_file, tee)

        # Step 2: write recovery command
        ok = step_write_recovery_cmd(serial, tee)
        results["write_cmd"] = ok
        if not ok:
            log("[ABORT] Failed to write recovery command.", tee)
            return _summary(results, log_file, tee)

        # Step 3: run recovery
        ok = step_run_recovery(serial, tee)
        results["recovery"] = ok
        # non-fatal: recovery exit code is unreliable, continue to check log

        # Step 4: cat recovery log
        ok, recovery_log_text = step_cat_recovery_log(serial, tee)
        results["recovery_log"] = ok

        # Step 5: slot before reboot
        slot_before = step_get_slot(serial, tee, "before")
        results["slot_before"] = slot_before

        # Step 6: reboot
        ok = step_reboot(serial, tee)
        results["reboot"] = ok
        if not ok:
            log("[ABORT] Reboot command failed.", tee)
            return _summary(results, log_file, tee)

        # Step 7: wait online
        ok = step_wait_online(serial, tee)
        results["online"] = ok
        if not ok:
            log("[ABORT] Device did not come back online.", tee)
            return _summary(results, log_file, tee)

        # Step 8: slot after reboot
        slot_after = step_get_slot(serial, tee, "after")
        results["slot_after"] = slot_after

        # Verify slot switched
        slot_switched = (
            slot_before != "unknown"
            and slot_after != "unknown"
            and slot_before != slot_after
        )
        results["slot_switched"] = slot_switched

        return _summary(results, log_file, tee)


def _summary(results, log_file, tee):
    log("", tee)
    log("=" * 60, tee)
    log("OTA Verify Summary", tee)
    log("=" * 60, tee)

    step_labels = [
        ("push",          "Step 1: Push OTA zip"),
        ("write_cmd",     "Step 2: Write recovery command"),
        ("recovery",      "Step 3: Run recovery"),
        ("recovery_log",  "Step 4: Read recovery log"),
        ("slot_before",   "Step 5: Slot before reboot"),
        ("reboot",        "Step 6: Reboot"),
        ("online",        "Step 7: Device online"),
        ("slot_after",    "Step 8: Slot after reboot"),
        ("slot_switched", "Slot switch verified"),
    ]

    all_ok = True
    for key, label in step_labels:
        val = results.get(key)
        if key in ("slot_before", "slot_after"):
            status = "{}".format(val or "N/A")
            log("  INFO  {:<35} {}".format(label, status), tee)
        else:
            ok = bool(val)
            tag = "PASS" if ok else "FAIL"
            log("  {}  {}".format(tag, label), tee)
            if not ok:
                all_ok = False

    log("", tee)
    log("Result : {}".format("PASS" if all_ok else "FAIL"), tee)
    log("Log    : {}".format(log_file), tee)
    log("=" * 60, tee)

    return {
        "ok":           all_ok,
        "slot_before":  results.get("slot_before", "unknown"),
        "slot_after":   results.get("slot_after",  "unknown"),
        "slot_switched":results.get("slot_switched", False),
        "log_file":     str(log_file),
    }


# =============================================================================
# Entry
# =============================================================================

def parse_args():
    p = argparse.ArgumentParser(description="OTA flash and verify slot switch")
    p.add_argument("--zip",    required=True, help="Path to OTA zip (full_update_ext4.zip)")
    p.add_argument("--serial", default=None,  help="ADB device serial (default: DEVICE_SERIAL from config)")
    return p.parse_args()


if __name__ == "__main__":
    args   = parse_args()
    serial = args.serial or DEVICE_SERIAL
    result = run_ota_flash_verify(zip_path=args.zip, serial=serial)
    sys.exit(0 if result["ok"] else 1)