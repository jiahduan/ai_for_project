# =============================================================================
# verify.py -- Offline log analysis (no adb, no device needed)
#
# Analyzes log directories captured by flash.py:
#   logs/{target}_pre_flash_{ts}/
#   logs/{target}_post_flash_{ts}/
#
# Usage:
#   python verify.py                          # auto-find latest post_flash dir
#   python verify.py --dir logs/alor_post_flash_20260707_143500
#   python verify.py --pre  logs/alor_pre_flash_20260707_143000 \
#                    --post logs/alor_post_flash_20260707_143500
# =============================================================================

import sys
import argparse
import re
from pathlib import Path
from config import LOG_DIR, ERROR_KEYWORDS, PASS_KEYWORDS

# =============================================================================
# Find latest log dir
# =============================================================================

def find_latest_log_dir(suffix="post_flash"):
    """
    Scan LOG_DIR for directories matching *_{suffix}_{YYYYMMDD_HHMMSS}.
    Returns the most recent one, or None.
    """
    base    = Path(LOG_DIR)
    pattern = re.compile(r"^.+_{}_(\d{{8}}_\d{{6}})$".format(suffix))
    candidates = []
    if not base.exists():
        return None
    for d in base.iterdir():
        if d.is_dir():
            m = pattern.match(d.name)
            if m:
                candidates.append((m.group(1), d))
    if not candidates:
        return None
    candidates.sort(key=lambda x: x[0], reverse=True)
    return candidates[0][1]

# =============================================================================
# Analyze a single log file for keywords
# =============================================================================

def analyze_file(filepath, error_kws=None, pass_kws=None):
    """
    Scan a text file for error/pass keywords.
    Returns dict: {errors: [...], passes: [...], lines: int}
    """
    error_kws = error_kws or ERROR_KEYWORDS
    pass_kws  = pass_kws  or PASS_KEYWORDS
    result    = {"errors": [], "passes": [], "lines": 0}

    p = Path(filepath)
    if not p.exists() or p.suffix == ".zip":
        return result

    try:
        with open(p, encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except Exception:
        return result

    result["lines"] = len(lines)
    for line in lines:
        ls = line.strip()
        for kw in pass_kws:
            if kw.lower() in line.lower():
                result["passes"].append(ls)
        for kw in error_kws:
            if kw.lower() in line.lower():
                result["errors"].append(ls)
    return result

# =============================================================================
# Analyze a log directory
# =============================================================================

def analyze_dir(log_dir):
    """
    Analyze all text log files in log_dir.
    Returns summary dict.
    """
    log_dir = Path(log_dir)
    if not log_dir.exists():
        return {"ok": False, "reason": "Directory not found: {}".format(log_dir)}

    print("[VERIFY] Analyzing: {}".format(log_dir))

    all_errors  = []
    all_passes  = []
    file_report = {}

    # Analyze each text file
    for fpath in sorted(log_dir.iterdir()):
        if fpath.suffix in (".txt",) and fpath.is_file():
            r = analyze_file(fpath)
            file_report[fpath.name] = r
            all_errors.extend([(fpath.name, e) for e in r["errors"]])
            all_passes.extend([(fpath.name, p) for p in r["passes"]])
            if r["errors"] or r["passes"]:
                print("  {:<30} lines={:>6}  errors={:>4}  passes={:>4}".format(
                    fpath.name, r["lines"], len(r["errors"]), len(r["passes"])))
            else:
                print("  {:<30} lines={:>6}".format(fpath.name, r["lines"]))

    boot_completed = any(
        kw.lower() in p.lower()
        for kw in PASS_KEYWORDS
        for _, p in all_passes
    )

    _ok = len(all_errors) == 0
    return {
        "ok":             _ok,
        "summary":        "PASS" if _ok else "FAIL ({} errors)".format(len(all_errors)),
        "boot_completed": boot_completed,
        "errors":         all_errors,
        "passes":         all_passes,
        "file_report":    file_report,
        "log_dir":        str(log_dir),
    }

# =============================================================================
# Print & save report
# =============================================================================

def print_report(result, label=""):
    title = "[VERIFY] {}".format(label) if label else "[VERIFY]"
    print("\n" + "=" * 60)
    status = "PASS" if result["ok"] else "FAIL ({} errors)".format(len(result["errors"]))
    boot   = "Boot OK" if result.get("boot_completed") else "Boot NOT detected"
    print("{}  {}  |  {}".format(title, status, boot))
    print("=" * 60)

    if result.get("passes"):
        print("\nPass signals ({}):" .format(len(result["passes"])))
        for fname, line in result["passes"][:5]:
            print("  [{}] {}".format(fname, line[:100]))

    if result.get("errors"):
        print("\nErrors ({}):" .format(len(result["errors"])))
        for fname, line in result["errors"][:20]:
            print("  [{}] {}".format(fname, line[:100]))
        if len(result["errors"]) > 20:
            print("  ... and {} more".format(len(result["errors"]) - 20))
    print("=" * 60)


def save_report(result, label=""):
    log_dir     = Path(result["log_dir"])
    report_path = log_dir / "verify_report.txt"
    status      = "PASS" if result["ok"] else "FAIL ({} errors)".format(len(result["errors"]))
    boot        = "Boot OK" if result.get("boot_completed") else "Boot NOT detected"

    with open(report_path, "w", encoding="utf-8") as f:
        f.write("Verify Report{}\n".format(" -- " + label if label else ""))
        f.write("Log dir : {}\n".format(log_dir))
        f.write("Result  : {}  |  {}\n".format(status, boot))
        f.write("\nFile summary:\n")
        for fname, r in result.get("file_report", {}).items():
            f.write("  {:<30} lines={:>6}  errors={:>4}  passes={:>4}\n".format(
                fname, r["lines"], len(r["errors"]), len(r["passes"])))
        if result.get("passes"):
            f.write("\nPass signals ({}):\n".format(len(result["passes"])))
            for fname, line in result["passes"]:
                f.write("  [{}] {}\n".format(fname, line))
        if result.get("errors"):
            f.write("\nErrors ({}):\n".format(len(result["errors"])))
            for fname, line in result["errors"]:
                f.write("  [{}] {}\n".format(fname, line))

    print("[VERIFY] Report saved: {}".format(report_path))
    return report_path

# =============================================================================
# Main entry
# =============================================================================

def run_verify(post_dir=None, pre_dir=None):
    """
    Analyze post-flash log dir (and optionally pre-flash for comparison).
    Returns result dict of post-flash analysis.
    """
    # Auto-find if not specified
    if post_dir is None:
        post_dir = find_latest_log_dir("post_flash")
        if post_dir is None:
            print("[VERIFY] ERROR: no post_flash log dir found in {}".format(LOG_DIR))
            return {
            "ok":             False,
            "summary":        "No log dir found",
            "boot_completed": False,
            "errors":         [],
            "passes":         [],
            "log_dir":        None,
        }

    # Analyze pre-flash (optional)
    if pre_dir:
        pre_result = analyze_dir(pre_dir)
        print_report(pre_result, label="PRE-FLASH")
        save_report(pre_result, label="pre-flash")
        print()

    # Analyze post-flash
    post_result = analyze_dir(post_dir)
    print_report(post_result, label="POST-FLASH")
    save_report(post_result, label="post-flash")

    return post_result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Offline log analysis")
    parser.add_argument("--dir",  default=None, help="Post-flash log dir to analyze")
    parser.add_argument("--post", default=None, help="Post-flash log dir")
    parser.add_argument("--pre",  default=None, help="Pre-flash log dir (optional, for comparison)")
    args = parser.parse_args()

    post = args.dir or args.post
    result = run_verify(post_dir=post, pre_dir=args.pre)
    sys.exit(0 if result.get("ok") else 1)