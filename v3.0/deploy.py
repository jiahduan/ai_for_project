# =============================================================================
# deploy.py -- Deploy all files to their target locations
# Run this after any code change to sync everything.
#
# SHARE_DIR  (Windows mount = Server share):
#   watcher.py, cp_images.sh, sync_and_build_ok.sh, project.json
#
# AUTO_FLASH (Windows local, this directory):
#   config.py, pipeline.py, build.py, flash.py, verify.py,
#   notify.py, img_finder.py
#   (these are already here -- no copy needed, just verified)
# =============================================================================

import shutil, sys, io, contextlib
from pathlib import Path
from datetime import datetime

# ── Paths ─────────────────────────────────────────────────────────────────────
AUTO_FLASH = Path(__file__).resolve().parent
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    sys.path.insert(0, str(AUTO_FLASH))
    import importlib, config
    importlib.reload(config)

SHARE_WIN = Path(config.WIN_SHARE_PATH)

# ── Deploy manifest ───────────────────────────────────────────────────────────
# Each entry: filename -> (src_dir, dst_dir)
# All files deployed to SHARE_DIR so Server always has the latest.
# (src, dst)
MANIFEST = {
    # -- py files: maintained in auto_flash, deployed to SHARE_DIR --
    "config.py":            (AUTO_FLASH, SHARE_WIN),
    "pipeline.py":          (AUTO_FLASH, SHARE_WIN),
    "build.py":             (AUTO_FLASH, SHARE_WIN),
    "flash.py":             (AUTO_FLASH, SHARE_WIN),
    "verify.py":            (AUTO_FLASH, SHARE_WIN),
    "notify.py":            (AUTO_FLASH, SHARE_WIN),
    "img_finder.py":        (AUTO_FLASH, SHARE_WIN),
    "watcher_client.py":    (AUTO_FLASH, SHARE_WIN),
    "sync_code.py":         (AUTO_FLASH, SHARE_WIN),
    "cp_download.py":       (AUTO_FLASH, SHARE_WIN),
    "build_abl.py":         (AUTO_FLASH, SHARE_WIN),
    "build_kernel.py":      (AUTO_FLASH, SHARE_WIN),
    "cp_img.py":            (AUTO_FLASH, SHARE_WIN),
    "ota_flash_verify.py":  (AUTO_FLASH, SHARE_WIN),
    "watcher.py":           (AUTO_FLASH, SHARE_WIN),
    "deploy.py":            (AUTO_FLASH, SHARE_WIN),
    "verify_deploy.py":     (AUTO_FLASH, SHARE_WIN),
    # -- sh / json: maintained in SHARE_DIR (in place) --
    "cp_download.sh":       (SHARE_WIN,  SHARE_WIN),
    "cp_images.sh":         (SHARE_WIN,  SHARE_WIN),
    "sync_and_build_ok.sh": (SHARE_WIN,  SHARE_WIN),
    "project.json":         (SHARE_WIN,  SHARE_WIN),
}

AUTO_FLASH_FILES = []   # all files now in MANIFEST

# ── Deploy ────────────────────────────────────────────────────────────────────
print("=" * 60)
print(" deploy.py  --  {}".format(datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
print("=" * 60)

ok = fail = 0

print("\n[DEPLOY -> SHARE_DIR]  {}".format(SHARE_WIN))
for fname, (src_dir, dst_dir) in MANIFEST.items():
    src = src_dir / fname
    dst = dst_dir / fname
    if not src.exists():
        print("  [FAIL] {:<28} src not found: {}".format(fname, src))
        fail += 1
        continue
    try:
        if src.resolve() == dst.resolve():
            # in-place: ensure LF for .sh files
            if fname.endswith(".sh"):
                raw = dst.read_bytes()
                if b"\r\n" in raw:
                    dst.write_bytes(raw.replace(b"\r\n", b"\n"))
            kb = round(dst.stat().st_size / 1024, 1)
            print("  [OK]   {:<28} {:5.1f} KB  (in place)".format(fname, kb))
        else:
            raw = src.read_bytes()
            # ensure LF line endings when deploying .sh files
            if fname.endswith(".sh") and b"\r\n" in raw:
                raw = raw.replace(b"\r\n", b"\n")
            dst.write_bytes(raw)
            kb = round(dst.stat().st_size / 1024, 1)
            print("  [OK]   {:<28} {:5.1f} KB".format(fname, kb))
        ok += 1
    except Exception as e:
        print("  [FAIL] {:<28} {}".format(fname, e))
        fail += 1

# AUTO_FLASH_FILES is empty -- all files handled in MANIFEST above

print()
print("=" * 60)
print("  Deployed : {}  Failed : {}  {}".format(
    ok, fail, "ALL OK" if fail == 0 else "CHECK ABOVE"))
print("=" * 60)

if fail:
    sys.exit(1)