# Pipeline Pass/Fail Logic -- Design Document
# Generated : 2026-07-08
# Project   : auto_flash
# =============================================================================

## 1. Overview

Each pipeline step returns bool (True=success / False=failure).
pipeline.py converts it to a 3-value status string stored in the steps list:

  "PASS" -- step executed and succeeded
  "FAIL" -- step executed and failed; pipeline aborts, all remaining steps -> SKIP
  "SKIP" -- skipped because a previous step FAILed

Overall result:
  total_ok = all(s in ("PASS", "SKIP") for _, s, _ in steps)
  i.e. pipeline passes as long as no step is FAIL.

=============================================================================
## 2. Step 1 -- Sync Code   (sync_code.trigger_sync)
=============================================================================

Call chain:
  trigger_sync()
    watcher_client.run_trigger(label="SYNC", cmd=SYNC_CMD, timeout=0)

PASS (returns True):
  1. watcher ping responded: ping.json deleted within 15 s
  2. status.json appeared within 120 s (FIRST_STATUS_TIMEOUT)
  3. status.json["status"] == "done"
     OR status == "idle" AND elapsed > 10 s
  4. _reload_config() reads new project_root from project.json

FAIL (returns False):
  A. watcher ping timeout (15 s, no response)
  B. status.json never appeared within 120 s (watcher not running / not handling trigger)
  C. status.json["status"] == "error"
     -> sync_and_build_ok.sh exited non-zero
  D. liveness_monitor: ping failed during execution (30 s interval, 15 s wait)

Timeout:
  timeout=0 -> watcher side: proc.wait() with no timeout (sync can run indefinitely)
  Windows side: timeout > 0 check is skipped when timeout == 0

=============================================================================
## 3. Step 2 -- Copy Downloads   (cp_download.trigger_cp_download)
=============================================================================

Call chain:
  trigger_cp_download()
    watcher_client.run_trigger(label="CP_DL", cmd=CP_DOWNLOAD_CMD,
                               timeout=CP_DOWNLOAD_TIMEOUT=1800)

PASS (returns True):
  Same as Step 1 conditions 1-3, plus:
  cp_download.sh succeeded:
    - downloads_src directory exists
    - project_root directory exists
    - downloads_dst did not exist (no overwrite) OR cp -al / cp -a succeeded

FAIL (returns False):
  A-D: same as Step 1
  E. cp_download.sh exited non-zero:
     - downloads_src not found
     - project_root not found
     - cp command failed (disk full, permission, etc.)
  F. Windows side: elapsed > 1800 + 60 s timeout

=============================================================================
## 4. Step 3 -- ABL Build   (build_abl.trigger_build_abl)
=============================================================================

Call chain:
  trigger_build_abl()
    watcher_client.run_trigger(label="ABL", cmd=BUILD_ABL_CMD,
                               timeout=BUILD_ABL_TIMEOUT=1800)

PASS (returns True):
  Same as Step 1 conditions 1-3, plus:
  sync_and_build_ok.sh -abl exited 0 (ABL compile succeeded)

FAIL (returns False):
  A-D: same as Step 1
  E. ABL compile failed (compile error, missing dependency, etc.)
  F. Windows side: elapsed > 1800 + 60 s timeout

=============================================================================
## 5. Step 4 -- Kernel Build   (build_kernel.trigger_build_kernel)
=============================================================================

Call chain:
  trigger_build_kernel()
    watcher_client.run_trigger(label="KERNEL", cmd=BUILD_KERNEL_CMD,
                               timeout=BUILD_KERNEL_TIMEOUT=3600)

PASS / FAIL: same as Step 3, command is sync_and_build_ok.sh -ker
Timeout: Windows side elapsed > 3600 + 60 s

=============================================================================
## 6. Step 5 -- Remote Build   (build.trigger_build)
=============================================================================

Call chain:
  trigger_build()
    Independent implementation (not via watcher_client)
    Has progress bar and waiting_choice interaction

PASS (returns True):
  1. watcher ping responded
  2. status.json["status"] == "done"
     OR status == "idle" AND elapsed > 10 s
  3. cp step (cp_images.sh) completed successfully

FAIL (returns False):
  A. watcher ping timeout
  B. liveness_monitor: heartbeat lost
  C. status.json["status"] == "error":
     - sync_and_build_ok.sh -img exited non-zero (build failed)
     - cp_images.sh failed
  D. Windows side: elapsed > BUILD_TIMEOUT(7200) + CP_TIMEOUT(120) + 60 s

Special statuses (not PASS/FAIL, keep waiting):
  "building"       -> show bitbake progress bar, continue polling
  "copying"        -> progress bar done, wait for cp to finish
  "waiting_choice" -> cp_images.sh found multiple candidate dirs, wait for user input
                       if CP_CHOICE != None: auto-reply, non-blocking

=============================================================================
## 7. Step 6 -- Flash Device   (flash.flash_device)
=============================================================================

Call chain:
  flash_device()
    Local execution only -- no watcher, no Server

PASS (returns True):
  All of the following succeed without exception:
  1. get_flash_plan()       : image dir found, partition list built
  2. capture_logs(pre, 10s) : pre-flash logcat captured
  3. adb root               : check=False, failure does NOT abort
  4. adb reboot bootloader  : success
  5. fastboot devices       : device detected within 60 s (poll)
  6. fastboot flash <part>  : ALL partitions flashed (check=True, raises on failure)
  7. fastboot reboot        : success
  8. adb wait-for-device    : device online within 180 s
  9. capture_logs(post, LOGCAT_DURATION): post-flash logcat captured

FAIL (returns False):
  Any step raises RuntimeError or Exception:
  A. Image dir not found or no flashable partitions
  B. fastboot device not detected within 60 s
  C. fastboot flash failed on any partition (subprocess.CalledProcessError)
  D. adb wait-for-device timed out (180 s)
  E. Any other unexpected exception

Notes:
  - adb root uses check=False: failure is logged but does NOT affect PASS/FAIL
  - pre-flash log failure does NOT affect PASS/FAIL (caught by try/except)

=============================================================================
## 8. Step 7 -- Verify   (verify.run_verify)
=============================================================================

Call chain:
  run_verify()
    find_latest_log_dir("post_flash")
    analyze_dir(post_dir)
      analyze_file(fpath) for each .txt file in log_dir

PASS (ok=True):
  analyze_dir scans all .txt files in the post_flash log directory:
  -> total ERROR_KEYWORDS matches across all files == 0

  ERROR_KEYWORDS (config.py):
    "FATAL EXCEPTION"
    "kernel panic"
    "ANR in"
    "E HWASan"
    "AddressSanitizer"
    "SIGSEGV"
    "SIGABRT"

FAIL (ok=False):
  A. post_flash log directory not found (find_latest_log_dir returns None)
  B. Any .txt file contains any ERROR_KEYWORDS match

Additional info (does NOT affect ok):
  boot_completed : True if PASS_KEYWORDS found in passes list
                   PASS_KEYWORDS: "Boot completed", "sys.boot_completed=1"
                   Informational only, shown in email report
  errors list    : all lines matching ERROR_KEYWORDS, written to report
  passes list    : all lines matching PASS_KEYWORDS, written to report

=============================================================================
## 9. Pipeline Overall PASS/FAIL
=============================================================================

  total_ok = all(s in ("PASS", "SKIP") for _, s, _ in steps)

Scenarios:

  Scenario 1: All succeed
    Sync Code      PASS
    Copy Downloads PASS
    ABL Build      PASS
    Kernel Build   PASS
    Remote Build   PASS
    Flash Device   PASS
    Verify         PASS
    -> total_ok = True

  Scenario 2: Sync fails, all subsequent SKIP
    Sync Code      FAIL
    Copy Downloads SKIP
    ABL Build      SKIP
    Remote Build   SKIP
    Flash Device   SKIP
    Verify         SKIP
    -> total_ok = False  (contains FAIL)

  Scenario 3: Build fails, Flash/Verify SKIP
    Sync Code      PASS
    Copy Downloads PASS
    Remote Build   FAIL
    Flash Device   SKIP
    Verify         SKIP
    -> total_ok = False

  Scenario 4: Verify fails (error keywords found)
    ...
    Flash Device   PASS
    Verify         FAIL
    -> total_ok = False

  Scenario 5: --skip-build mode, Build not in plan
    Flash Device   PASS
    Verify         PASS
    -> total_ok = True  (no FAIL, no SKIP)

  Scenario 6: --full mode, all succeed
    Sync Code      PASS
    Copy Downloads PASS
    ABL Build      PASS
    Kernel Build   PASS
    Remote Build   PASS
    Flash Device   PASS
    Verify         PASS
    -> total_ok = True

=============================================================================
## 10. Heartbeat / Liveness Monitor
=============================================================================

Windows side (watcher_client):
  Initial ping:
    write ping.json -> wait up to 15 s for it to be deleted
    -> FAIL if not deleted within 15 s

  liveness_monitor thread (runs during entire step execution):
    Every 30 s: send ping, wait up to 15 s for response
    -> if no response: dead_event.set() -> main loop returns False

Server side (watcher._ping_responder_loop):
  Independent thread, checks ping.json every 1 s, deletes if found
  Runs concurrently with build execution thread
  NOT blocked by build/sync running

FIRST_STATUS_TIMEOUT = 120 s:
  If status.json never appears within 120 s after trigger is sent:
  -> assume watcher is not processing the trigger
  -> return False immediately
  -> independent of build timeout; guards against watcher not started

=============================================================================
## 11. Module Dependency Map
=============================================================================

  pipeline.py
    |-- sync_code.py       -> watcher_client.run_trigger  (timeout=0,    no limit)
    |-- cp_download.py     -> watcher_client.run_trigger  (timeout=1800, 30 min)
    |-- build_abl.py       -> watcher_client.run_trigger  (timeout=1800, 30 min)
    |-- build_kernel.py    -> watcher_client.run_trigger  (timeout=3600, 60 min)
    |-- build.py           -> independent impl            (timeout=7200+120)
    |-- flash.py           -> local adb/fastboot          (no watcher)
    |-- verify.py          -> local file analysis         (no watcher, no adb)

  watcher_client.py        -> shared by sync / cp_download / abl / kernel
  config.py                -> all modules read at CALL TIME (not import time)
                              reload after sync ensures PROJECT_ROOT is current

=============================================================================
## 12. Config Values Reference
=============================================================================

  SYNC_TIMEOUT          = 0       (no timeout)
  CP_DOWNLOAD_TIMEOUT   = 1800    (30 min)
  BUILD_ABL_TIMEOUT     = 1800    (30 min)
  BUILD_KERNEL_TIMEOUT  = 3600    (60 min)
  BUILD_TIMEOUT         = 7200    (120 min)
  CP_TIMEOUT            = 120     (2 min)
  FIRST_STATUS_TIMEOUT  = 120     (watcher_client constant, not configurable)
  PING_WAIT             = 15      (initial ping wait)
  PING_CHECK_INTERVAL   = 30      (liveness check interval)
  PING_CHECK_TIMEOUT    = 15      (liveness ping wait)
