# =============================================================================
# pipeline.py -- Build-Flash-Verify Pipeline
#
# Serial chain (--full):
#   sync -> cp_dl -> abl -> kernel -> img -> flash -> verify
#   Every step depends on the previous; any FAIL aborts the rest.
#
# Standalone modes (assumes build already done):
#   python pipeline.py                   # img -> flash -> verify
#   python pipeline.py --full            # sync -> cp-dl -> abl -> kernel -> img -> flash -> verify
#   python pipeline.py --sync-only       # sync -> cp-dl  (stop after cp-dl)
#   python pipeline.py --skip-cp-download# sync only, skip cp-dl
#   python pipeline.py --cp-dl-only      # cp-dl only (independent)
#   python pipeline.py --abl-only        # abl only   (independent)
#   python pipeline.py --kernel-only     # kernel only (independent)
#   python pipeline.py --skip-build      # flash -> verify (skip img build)
#   python pipeline.py --flash-only      # flash -> verify
#   python pipeline.py --verify-only     # verify only
# =============================================================================

import sys
import argparse
import time
from datetime import datetime

from pathlib import Path

from sync_code     import trigger_sync
import functools
from cp_download   import trigger_cp_download
from build_abl     import trigger_build_abl
from build_kernel  import trigger_build_kernel
from build         import trigger_build
from flash         import flash_device
from verify        import run_verify
from notify        import send_notify
from config        import LOG_DIR


# =============================================================================
# Args
# =============================================================================

def parse_args():
    p = argparse.ArgumentParser(description="Auto Build-Flash-Verify Pipeline")
    p.add_argument("--full",              action="store_true",
                   help="Full serial chain: sync->cp-dl->abl->kernel->img->flash->verify")
    p.add_argument("--sync-only",         action="store_true",
                   help="sync -> cp-dl, then stop")
    p.add_argument("--skip-cp-download",  action="store_true",
                   help="When used with --sync-only or --full: skip cp-dl after sync")
    p.add_argument("--cp-dl-only",        action="store_true",
                   help="Copy downloads only (independent, no sync required)")
    p.add_argument("--abl-only",          action="store_true",
                   help="ABL build only (independent, assumes workspace exists)")
    p.add_argument("--kernel-only",       action="store_true",
                   help="Kernel build only (independent, assumes workspace exists)")
    p.add_argument("--skip-sync",         action="store_true",
                   help="Skip sync: cp-dl->abl->kernel->img->flash->verify")
    p.add_argument("--img-retries",        type=int, default=None, metavar="N",
                   help="img build retry attempts on bitbake reconnect (default: config.BUILD_IMG_RETRIES)")
    p.add_argument("--skip-build",        action="store_true",
                   help="Skip img build: flash -> verify only")
    p.add_argument("--flash-only",        action="store_true",
                   help="Flash -> verify only (same as --skip-build)")
    p.add_argument("--verify-only",       action="store_true",
                   help="Verify only")
    return p.parse_args()


# =============================================================================
# Report
# =============================================================================

def save_report(steps, verify_result):
    ts          = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = Path(LOG_DIR) / "pipeline_report_{}.txt".format(ts)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    with open(report_path, "w", encoding="utf-8") as f:
        f.write("Pipeline Report -- {}\n".format(ts))
        f.write("=" * 60 + "\n\n")
        f.write("Steps:\n")
        for name, status, elapsed in steps:
            f.write("  {:4s}  {:<25}  ({:.1f}s)\n".format(status, name, elapsed))
        f.write("\nVerification Result:\n")
        f.write("  {}\n".format(verify_result.get("summary", "N/A")))
        if verify_result.get("errors"):
            f.write("\nErrors:\n")
            for e in verify_result["errors"][:50]:
                f.write("  {}\n".format(e))
        log_dir = verify_result.get("log_dir") or verify_result.get("log_file")
        if log_dir:
            f.write("\nLog dir: {}\n".format(log_dir))
    print("[PIPELINE] Report saved: {}".format(report_path))
    return report_path


# =============================================================================
# Plan builder
# =============================================================================

def _build_plan(full, sync_only, skip_cp_download,
                cp_dl_only, abl_only, kernel_only,
                skip_sync, skip_build, flash_only, verify_only,
                img_retries=None):
    """
    Return ordered list of (name, fn) to execute.

    Two modes:
      A. Serial chain  -- starts from sync, every step depends on previous
         --full        : sync -> cp_dl -> abl -> kernel -> img -> flash -> verify
         --skip-sync   : cp_dl -> abl -> kernel -> img -> flash -> verify
         --sync-only   : sync -> cp_dl  (or sync only if --skip-cp-download)

      B. Standalone    -- independent single step or partial chain
         --cp-dl-only  : cp_dl
         --abl-only    : abl
         --kernel-only : kernel
         (default)     : img -> flash -> verify
         --skip-build  : flash -> verify
         --flash-only  : flash -> verify
         --verify-only : verify
    """
    # ---- Mode A: serial chain starting from sync ----
    if skip_sync:
        plan = []
        if not skip_cp_download:
            # force=True: workspace already exists, overwrite downloads dir
            plan.append(("Copy Downloads",
                         functools.partial(trigger_cp_download, force=True)))
        plan.extend([
            ("ABL Build",    trigger_build_abl),
            ("Kernel Build", trigger_build_kernel),
            ("Remote Build", functools.partial(trigger_build, retries=img_retries) if img_retries is not None else trigger_build),
            ("Flash Device", flash_device),
            ("Verify",       run_verify),
        ])
        return plan

    if full or sync_only:
        plan = [("Sync Code", trigger_sync)]
        if not skip_cp_download:
            plan.append(("Copy Downloads", trigger_cp_download))
        if full:
            plan.append(("ABL Build",    trigger_build_abl))
            plan.append(("Kernel Build", trigger_build_kernel))
            plan.append(("Remote Build", functools.partial(trigger_build, retries=img_retries) if img_retries is not None else trigger_build))
            plan.append(("Flash Device", flash_device))
            plan.append(("Verify",       run_verify))
        return plan

    # ---- Mode B: standalone single step ----
    if cp_dl_only:
        return [("Copy Downloads", trigger_cp_download)]

    if abl_only:
        return [("ABL Build", trigger_build_abl)]

    if kernel_only:
        return [("Kernel Build", trigger_build_kernel)]

    # ---- Mode B: partial tail chain (assumes build already done) ----
    if verify_only:
        return [("Verify", run_verify)]

    if skip_build or flash_only:
        return [
            ("Flash Device", flash_device),
            ("Verify",       run_verify),
        ]

    # default: img -> flash -> verify
    return [
        ("Remote Build", functools.partial(trigger_build, retries=img_retries) if img_retries is not None else trigger_build),
        ("Flash Device", flash_device),
        ("Verify",       run_verify),
    ]


# =============================================================================
# Main pipeline
# =============================================================================

def run_pipeline(
    full=False, sync_only=False, skip_cp_download=False,
    cp_dl_only=False, abl_only=False, kernel_only=False,
    skip_sync=False, skip_build=False, flash_only=False, verify_only=False,
    img_retries=None,
):
    print("\n" + "=" * 60)
    print("  Auto Build-Flash-Verify Pipeline")
    print("  Started: {}".format(datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
    print("=" * 60 + "\n")

    plan  = _build_plan(full, sync_only, skip_cp_download,
                        cp_dl_only, abl_only, kernel_only,
                        skip_sync, skip_build, flash_only, verify_only,
                        img_retries=img_retries)
    total = len(plan)

    print("  Steps planned ({})".format(total))
    for i, (name, _) in enumerate(plan, 1):
        print("    {}/{}  {}".format(i, total, name))
    print()

    # ---- Execute ----
    steps       = []
    pipeline_ok = True
    verify_result = {
        "ok":             False,
        "summary":        "Not run",
        "boot_completed": False,
        "errors":         [],
        "passes":         [],
        "log_dir":        None,
    }

    for idx, (name, fn) in enumerate(plan, 1):
        print("-- STEP {}/{}: {} {}".format(
            idx, total, name, "-" * max(1, 44 - len(name))))

        if not pipeline_ok:
            steps.append((name, "SKIP", 0.0))
            print("[PIPELINE] Skipped: {}".format(name))
            if name == "Verify":
                verify_result["summary"] = "Skipped due to previous failure"
            continue

        t0 = time.time()

        if name == "Verify":
            result        = fn()
            elapsed       = time.time() - t0
            verify_result = result
            ok            = result.get("ok", False)
        else:
            ok      = fn()
            elapsed = time.time() - t0

        steps.append((name, "PASS" if ok else "FAIL", elapsed))

        if not ok:
            print("[PIPELINE] {} failed. Aborting.".format(name))
            pipeline_ok = False

    # ---- Summary ----
    print("\n" + "=" * 60)
    print("  Pipeline Summary")
    print("=" * 60)
    for name, status, elapsed in steps:
        print("  {:4s}  {:<25}  {:>7.1f}s".format(status, name, elapsed))
    print("-" * 60)
    total_ok = all(s in ("PASS", "SKIP") for _, s, _ in steps)
    print("  Result: {}".format("ALL PASSED" if total_ok else "PIPELINE FAILED"))
    print("=" * 60 + "\n")

    report_path = save_report(steps, verify_result)

    # ---- Notify ----
    from img_finder import find_latest_img_dir
    img_dir = find_latest_img_dir()
    target  = img_dir.name.rsplit("_", 2)[0] if img_dir else "device"
    send_notify(steps, verify_result, target=target, report_path=report_path)

    return total_ok


# =============================================================================
# Entry
# =============================================================================

if __name__ == "__main__":
    args = parse_args()
    ok = run_pipeline(
        full             = args.full,
        sync_only        = args.sync_only,
        skip_cp_download = args.skip_cp_download,
        cp_dl_only       = args.cp_dl_only,
        abl_only         = args.abl_only,
        kernel_only      = args.kernel_only,
        skip_sync        = args.skip_sync,
        skip_build       = args.skip_build,
        flash_only       = args.flash_only,
        verify_only      = args.verify_only,
        img_retries      = args.img_retries,
    )
    sys.exit(0 if ok else 1)