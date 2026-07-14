# =============================================================================
# cp_img.py -- Copy image files from a local path to WIN_SHARE_PATH
#
# Usage:
#   python cp_img.py --src <path\to\image\dir>
#   python cp_img.py --src <path> --dst <path>   # override destination
#
# Completely standalone -- no watcher, no Server, no network.
# Reads FILES_TO_COPY and WIN_SHARE_PATH from config.py.
# Destination: WIN_SHARE_PATH\<target>_<timestamp>\
# =============================================================================

import argparse
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path

import config
from config import WIN_SHARE_PATH, FILES_TO_COPY, TARGET

# =============================================================================
# Helpers
# =============================================================================

def _fmt_size(n_bytes):
    for unit in ("B", "KB", "MB", "GB"):
        if n_bytes < 1024:
            return "{:.1f} {}".format(n_bytes, unit)
        n_bytes /= 1024
    return "{:.1f} TB".format(n_bytes)


def _fmt_speed(bps):
    return _fmt_size(bps) + "/s"


def _copy_file(src, dst):
    """Copy one file with a live progress bar. Returns elapsed seconds."""
    size = src.stat().st_size
    t0   = time.time()

    with open(src, "rb") as fin, open(dst, "wb") as fout:
        copied   = 0
        buf_size = 4 * 1024 * 1024   # 4 MB chunks
        t_prev   = t0
        b_prev   = 0

        while True:
            chunk = fin.read(buf_size)
            if not chunk:
                break
            fout.write(chunk)
            copied += len(chunk)

            # progress bar
            pct      = copied * 100 // size if size else 100
            now      = time.time()
            interval = now - t_prev
            if interval >= 0.3:
                speed    = (copied - b_prev) / interval if interval > 0 else 0
                eta      = int((size - copied) / speed) if speed > 0 else 0
                bar_fill = pct * 35 // 100
                bar      = "=" * bar_fill + (">" if pct < 100 else "=") + " " * (35 - bar_fill)
                sys.stdout.write(
                    "\r    [{}] {:3d}%  {:>10}  ETA {:d}s  ".format(
                        bar, pct, _fmt_speed(speed), eta)
                )
                sys.stdout.flush()
                t_prev = now
                b_prev = copied

    elapsed = time.time() - t0
    avg_speed = size / elapsed if elapsed > 0 else 0
    sys.stdout.write(
        "\r    [{}] 100%  {:>10}  done{}\n".format(
            "=" * 36, _fmt_speed(avg_speed), " " * 10)
    )
    sys.stdout.flush()
    return elapsed

# =============================================================================
# Main
# =============================================================================

def run_cp_img(src_dir, dst_dir=None):
    src_dir = Path(src_dir)
    if not src_dir.exists():
        print("[CP_IMG] ERROR: source dir not found: {}".format(src_dir))
        return False

    # destination: WIN_SHARE_PATH/<target>_<timestamp>/
    if dst_dir is None:
        ts      = datetime.now().strftime("%Y%m%d_%H%M%S")
        dst_dir = Path(WIN_SHARE_PATH) / "{}_{}".format(TARGET, ts)
    else:
        dst_dir = Path(dst_dir)

    dst_dir.mkdir(parents=True, exist_ok=True)

    print()
    print("=" * 60)
    print("  Copy Images")
    print("=" * 60)
    print("  Source : {}".format(src_dir))
    print("  Dest   : {}".format(dst_dir))
    print("  Files  : {}".format(", ".join(FILES_TO_COPY)))
    print()

    ok_count   = 0
    fail_count = 0
    skip_count = 0
    total      = len(FILES_TO_COPY)

    for idx, fname in enumerate(FILES_TO_COPY, 1):
        src_file = src_dir / fname
        dst_file = dst_dir / fname

        print("  [{}/{}] {}".format(idx, total, fname))

        if not src_file.exists():
            print("    [SKIP] not found in source")
            skip_count += 1
            continue

        size = src_file.stat().st_size
        print("    size : {}".format(_fmt_size(size)))

        try:
            elapsed = _copy_file(src_file, dst_file)
            print("    [OK]  {:.1f}s".format(elapsed))
            ok_count += 1
        except Exception as e:
            print("    [FAIL] {}".format(e))
            fail_count += 1

    # summary
    print()
    print("=" * 60)
    print("  Summary")
    print("=" * 60)
    print("  Copied : {}".format(ok_count))
    print("  Skipped: {}".format(skip_count))
    print("  Failed : {}".format(fail_count))
    print("  Dest   : {}".format(dst_dir))
    print("=" * 60)

    return fail_count == 0


# =============================================================================
# Entry
# =============================================================================

def parse_args():
    p = argparse.ArgumentParser(description="Copy image files to share dir")
    p.add_argument("--src", required=True, help="Source directory containing image files")
    p.add_argument("--dst", default=None,  help="Destination directory (default: WIN_SHARE_PATH/<target>_<ts>)")
    return p.parse_args()


if __name__ == "__main__":
    args = parse_args()
    ok   = run_cp_img(src_dir=args.src, dst_dir=args.dst)
    sys.exit(0 if ok else 1)