# =============================================================================
# img_finder.py -- Locate latest build output directory and scan img files
#
# cp_images.sh copies to: {WIN_SHARE_PATH}/{TARGET}_{YYYYMMDD_HHMMSS}/
# This module finds the newest such directory and returns flash-ready file map.
# =============================================================================

import re
from datetime import datetime
from pathlib import Path
from config import WIN_SHARE_PATH, IMG_MAP, FLASH_PARTITIONS

# Directory name pattern: any_name_YYYYMMDD_HHMMSS
_DIR_RE = re.compile(r"^.+_(\d{8}_\d{6})$")


def find_latest_img_dir():
    """
    Scan WIN_SHARE_PATH for directories matching {TARGET}_{TIMESTAMP}.
    Returns the Path of the most recently created one, or None if not found.
    """
    share = Path(WIN_SHARE_PATH)
    candidates = []
    for d in share.iterdir():
        if not d.is_dir():
            continue
        m = _DIR_RE.match(d.name)
        if m:
            try:
                ts = datetime.strptime(m.group(1), "%Y%m%d_%H%M%S")
                candidates.append((ts, d))
            except ValueError:
                continue

    if not candidates:
        return None

    candidates.sort(key=lambda x: x[0], reverse=True)
    return candidates[0][1]


def scan_img_files(img_dir):
    """
    Scan img_dir for files listed in IMG_MAP.
    Returns list of (partition, filepath) tuples in FLASH_PARTITIONS order,
    skipping files that are missing or have None partition mapping.

    Example return:
        [
            ("abl",      Path(".../abl.elf")),
            ("boot",     Path(".../boot.img")),
            ("dtbo",     Path(".../dtbo.img")),
            ("system",   Path(".../system.img")),
            ("persist",  Path(".../persist.img")),
            ("userdata", Path(".../userdata.img")),
        ]
    """
    img_dir = Path(img_dir)
    result  = []

    # Build partition -> filepath map from files present in directory
    available = {}
    for filename, partition in IMG_MAP.items():
        if partition is None:
            continue   # skip (e.g. OTA zip)
        fpath = img_dir / filename
        if fpath.exists():
            available[partition] = fpath

    # Return in FLASH_PARTITIONS order
    for partition in FLASH_PARTITIONS:
        if partition in available:
            result.append((partition, available[partition]))

    return result


def get_flash_plan(img_dir=None):
    """
    High-level helper: find latest dir (if not specified) and return flash plan.
    Returns (img_dir, flash_list) or raises RuntimeError if nothing found.

    flash_list: [(partition, filepath), ...]
    """
    if img_dir is None:
        img_dir = find_latest_img_dir()
        if img_dir is None:
            raise RuntimeError(
                "No build output directory found in {}.\n"
                "Expected pattern: {{TARGET}}_{{YYYYMMDD_HHMMSS}}".format(WIN_SHARE_PATH)
            )

    flash_list = scan_img_files(img_dir)
    if not flash_list:
        raise RuntimeError(
            "No flashable images found in {}.\n"
            "Expected files: {}".format(img_dir, list(IMG_MAP.keys()))
        )

    return img_dir, flash_list


if __name__ == "__main__":
    # Quick test
    try:
        img_dir, flash_list = get_flash_plan()
        print("Latest img dir: {}".format(img_dir))
        print("Flash plan ({} partitions):".format(len(flash_list)))
        for partition, fpath in flash_list:
            size_mb = fpath.stat().st_size / 1024 / 1024
            print("  {:12s} <- {}  ({:.1f} MB)".format(partition, fpath.name, size_mb))
    except RuntimeError as e:
        print("ERROR:", e)