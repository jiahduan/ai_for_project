# =============================================================================
# flash.py -- Full flash flow with pre/post log capture
#
# Flow:
#   1. Discover latest img dir
#   2. Capture pre-flash logs  -> logs/{target}_pre_flash_{ts}/
#   3. adb root -> reboot bootloader
#   4. fastboot flash each partition
#   5. fastboot reboot -> wait for device
#   6. Capture post-flash logs -> logs/{target}_post_flash_{ts}/
# =============================================================================

import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from config import (
    ADB_PATH, FASTBOOT_PATH, DEVICE_SERIAL,
    FASTBOOT_WAIT_SEC, LOG_DIR, LOGCAT_DURATION,
)
from img_finder import get_flash_plan

# =============================================================================
# ADB / Fastboot wrappers
# =============================================================================

def _run(tool, *args, check=True, timeout=120):
    cmd = [tool]
    if DEVICE_SERIAL:
        cmd += ["-s", DEVICE_SERIAL]
    cmd += list(args)
    label = tool.split("\\")[-1].split("/")[-1].upper().replace(".EXE", "")
    print("[{}] {}".format(label, " ".join(str(a) for a in args)))
    result = subprocess.run(cmd, capture_output=True, text=True,
                            check=check, timeout=timeout)
    if result.stdout.strip():
        print(result.stdout.strip())
    if result.stderr.strip():
        print(result.stderr.strip())
    return result

def _adb(*args, **kw):      return _run(ADB_PATH,      *args, **kw)
def _fastboot(*args, **kw): return _run(FASTBOOT_PATH, *args, **kw)

# =============================================================================
# Device wait
# =============================================================================

def wait_for_device(mode="adb", timeout=180):
    print("[FLASH] Waiting for device in {} mode ...".format(mode))
    if mode == "adb":
        # adb wait-for-device blocks until device is visible to adb
        print("[FLASH] Running: adb wait-for-device ...")
        try:
            _adb("wait-for-device", check=True, timeout=timeout)
            print("[FLASH] Device online (adb).")
            return True
        except Exception as e:
            raise TimeoutError("adb wait-for-device failed: {}".format(e))
    # fastboot: poll manually
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            r = _fastboot("devices", check=False, timeout=5)
            if r.stdout.strip():
                print("[FLASH] Device online (fastboot).")
                return True
        except Exception:
            pass
        time.sleep(3)
    raise TimeoutError("Device not found in fastboot mode within {}s".format(timeout))

# =============================================================================
# Log capture (adb-based, called before and after flash)
# =============================================================================

def _adb_cmd():
    cmd = [ADB_PATH]
    if DEVICE_SERIAL:
        cmd += ["-s", DEVICE_SERIAL]
    return cmd

def _adb_run(*args, timeout=30):
    cmd = _adb_cmd() + list(args)
    return subprocess.run(cmd, capture_output=True, text=True,
                          timeout=timeout, errors="replace")

def _adb_popen(*args, stdout=None, stderr=None):
    cmd = _adb_cmd() + list(args)
    return subprocess.Popen(cmd, stdout=stdout, stderr=stderr)

def _device_online():
    try:
        r = _adb_run("get-state", timeout=5)
        return "device" in r.stdout
    except Exception:
        return False

def _save(log_dir, filename, *shell_args, label=None):
    """Run adb shell command and save to file. Returns Path or None."""
    out   = log_dir / filename
    label = label or filename
    try:
        r = _adb_run("shell", *shell_args, timeout=30)
        out.write_text(r.stdout, encoding="utf-8", errors="replace")
        print("[LOG]   {:<30} ({} KB)".format(filename, out.stat().st_size // 1024))
        return out
    except Exception as e:
        print("[LOG]   {} FAILED: {}".format(label, e))
        return None

def _save_logcat(log_dir, duration):
    """Capture logcat for duration seconds."""
    out = log_dir / "logcat.txt"
    print("[LOG]   {:<30} ({}s)".format("logcat.txt", duration))
    try:
        _adb_run("logcat", "-c", timeout=10)
        with open(out, "w", encoding="utf-8", errors="replace") as f:
            proc = _adb_popen("logcat", "-v", "threadtime",
                              stdout=f, stderr=subprocess.STDOUT)
            time.sleep(duration)
            proc.terminate()
            proc.wait(timeout=5)
        print("[LOG]   {:<30} ({} KB)".format("logcat.txt", out.stat().st_size // 1024))
        return out
    except Exception as e:
        print("[LOG]   logcat FAILED: {}".format(e))
        return None

def _save_bugreport(log_dir):
    out = log_dir / "bugreport.zip"
    print("[LOG]   {:<30} (running...)".format("bugreport.zip"))
    try:
        subprocess.run(_adb_cmd() + ["bugreport", str(out)],
                       capture_output=True, text=True, timeout=120)
        if out.exists() and out.stat().st_size > 0:
            print("[LOG]   {:<30} ({:.1f} MB)".format(
                "bugreport.zip", out.stat().st_size / 1024 / 1024))
            return out
    except Exception as e:
        print("[LOG]   bugreport FAILED: {}".format(e))
    return None


def capture_logs(log_dir, logcat_duration, with_bugreport=False):
    """
    Capture all available logs into log_dir.
    Returns dict of {name: Path}.
    """
    log_dir = Path(log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    captured = {}

    if not _device_online():
        print("[LOG] Device not online, skipping.")
        return captured

    print("[LOG] Saving to: {}".format(log_dir))

    # Android
    f = _save_logcat(log_dir, logcat_duration)
    if f: captured["logcat"] = f

    # Kernel
    f = _save(log_dir, "dmesg.txt",      "dmesg",                          label="dmesg")
    if f: captured["dmesg"] = f
    f = _save(log_dir, "last_kmsg.txt",  "cat", "/sys/fs/pstore/console-ramoops-0", label="last_kmsg")
    if f and f.stat().st_size < 10:
        f.unlink(); captured.pop("last_kmsg", None)

    # System info
    f = _save(log_dir, "props.txt",      "getprop",                        label="getprop")
    if f: captured["props"] = f
    f = _save(log_dir, "processes.txt",  "ps", "-A",                       label="ps")
    if f: captured["processes"] = f
    f = _save(log_dir, "meminfo.txt",    "cat", "/proc/meminfo",           label="meminfo")
    if f: captured["meminfo"] = f
    f = _save(log_dir, "diskinfo.txt",   "df", "-h",                       label="df")
    if f: captured["diskinfo"] = f

    # Systemd / journal
    f = _save(log_dir, "journal.txt",         "journalctl", "--no-pager", "-o", "short-precise",            label="journalctl")
    if f: captured["journal"] = f
    f = _save(log_dir, "journal_boot.txt",    "journalctl", "--no-pager", "-b", "-o", "short-precise",      label="journalctl -b")
    if f: captured["journal_boot"] = f
    f = _save(log_dir, "journal_kernel.txt",  "journalctl", "--no-pager", "-k", "-o", "short-precise",      label="journalctl -k")
    if f: captured["journal_kernel"] = f
    f = _save(log_dir, "journal_errors.txt",  "journalctl", "--no-pager", "-p", "err", "-o", "short-precise", label="journalctl -p err")
    if f: captured["journal_errors"] = f
    f = _save(log_dir, "systemd_failed.txt",  "systemctl", "--failed", "--no-pager",                        label="systemctl --failed")
    if f: captured["systemd_failed"] = f

    # Bugreport (post-flash only, takes time)
    if with_bugreport:
        f = _save_bugreport(log_dir)
        if f: captured["bugreport"] = f

    print("[LOG] Captured {} files.".format(len(captured)))
    return captured

# =============================================================================
# Flash
# =============================================================================

def flash_device(img_dir=None) -> bool:
    """
    Full flash flow with pre/post log capture.
    Returns True on success.
    """
    try:
        # Step 1: Discover images
        img_dir, flash_list = get_flash_plan(img_dir)
        target    = Path(img_dir).name.rsplit("_", 2)[0]
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        print("[FLASH] Image dir : {}".format(img_dir))
        print("[FLASH] Target    : {}".format(target))
        print("[FLASH] Flash plan: {} partitions".format(len(flash_list)))
        for partition, fpath in flash_list:
            print("  {:12s} <- {}  ({:.1f} MB)".format(
                partition, fpath.name, fpath.stat().st_size / 1024 / 1024))
        print()

        # Step 2: Pre-flash log capture (short logcat snapshot, no bugreport)
        pre_log_dir = Path(LOG_DIR) / "{}_pre_flash_{}".format(target, timestamp)
        print("[FLASH] -- Pre-flash logs --")
        capture_logs(pre_log_dir, logcat_duration=10, with_bugreport=False)
        print()

        # Step 3: adb root -> reboot bootloader
        print("[FLASH] Running adb root ...")
        _adb("root", check=False, timeout=15)
        time.sleep(3)
        print("[FLASH] Rebooting to bootloader ...")
        _adb("reboot", "bootloader", timeout=30)
        time.sleep(FASTBOOT_WAIT_SEC)

        # Step 4: Wait for fastboot
        wait_for_device(mode="fastboot", timeout=60)

        # Step 5: Flash each partition
        for partition, fpath in flash_list:
            print("[FLASH] Flashing {:12s} <- {}  ({:.1f} MB)".format(
                partition, fpath.name, fpath.stat().st_size / 1024 / 1024))
            _fastboot("flash", partition, str(fpath), timeout=300)

        # Step 6: Reboot
        print("[FLASH] Rebooting device ...")
        _fastboot("reboot", timeout=30)

        # Step 7: Wait for device -- no fixed sleep, adb wait-for-device blocks
        print("[FLASH] Waiting for device to come back online ...")
        wait_for_device(mode="adb", timeout=180)
        print("[FLASH] Flash completed successfully.")
        print()

        # Step 8: Post-flash log capture (full logcat + bugreport)
        post_log_dir = Path(LOG_DIR) / "{}_post_flash_{}".format(target, timestamp)
        print("[FLASH] -- Post-flash logs --")
        capture_logs(post_log_dir, logcat_duration=LOGCAT_DURATION, with_bugreport=True)
        print()

        print("[FLASH] Log dirs:")
        print("  pre  : {}".format(pre_log_dir))
        print("  post : {}".format(post_log_dir))
        return True

    except RuntimeError as e:
        print("[FLASH] ERROR: {}".format(e))
        return False
    except Exception as e:
        print("[FLASH] Flash failed: {}".format(e))
        return False


if __name__ == "__main__":
    img_dir = sys.argv[1] if len(sys.argv) > 1 else None
    ok = flash_device(img_dir)
    sys.exit(0 if ok else 1)