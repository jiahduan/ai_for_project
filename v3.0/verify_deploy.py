# =============================================================================
# verify_deploy.py -- Verify all deployed files are present and correct
# Run after deploy.py to confirm everything is in place.
# =============================================================================

import json, ast, re, sys, io, contextlib
from pathlib import Path

AUTO_FLASH = Path(__file__).resolve().parent
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    sys.path.insert(0, str(AUTO_FLASH))
    import importlib, config
    importlib.reload(config)

SHARE_WIN = Path(config.WIN_SHARE_PATH)

ok_n = fail_n = 0

def check(label, passed, detail=""):
    global ok_n, fail_n
    tag = "[PASS]" if passed else "[FAIL]"
    print("  {} {:<38} {}".format(tag, label, detail))
    if passed: ok_n += 1
    else:       fail_n += 1

# ── 1. AUTO_FLASH files (source) ─────────────────────────
print("\n[1] AUTO_FLASH source files  ({})".format(AUTO_FLASH))
auto_files = {
    "config.py":        "all configuration",
    "pipeline.py":      "main entry point",
    "build.py":         "remote build trigger",
    "flash.py":         "flash + log capture",
    "verify.py":        "offline log analysis",
    "notify.py":        "Outlook email notify",
    "img_finder.py":    "auto img discovery",
    "watcher_client.py": "shared watcher helpers",
    "sync_code.py":     "sync code trigger",
    "cp_download.py":   "copy downloads trigger",
    "build_abl.py":     "ABL build trigger",
    "build_kernel.py":  "Kernel build trigger",
    "cp_img.py":          "image copy trigger",
    "ota_flash_verify.py": "OTA flash and verify",
    "watcher.py":       "Server trigger listener",
    "deploy.py":        "deploy script",
    "verify_deploy.py": "this verify script",
}
for fname, desc in auto_files.items():
    fp = AUTO_FLASH / fname
    exists = fp.exists()
    detail = "{:.1f} KB".format(fp.stat().st_size / 1024) if exists else "NOT FOUND"
    check("{} ({})".format(fname, desc), exists, detail)

# ── 2. SHARE_DIR deployed files ───────────────────────────
print("\n[2] SHARE_DIR deployed files  ({})".format(SHARE_WIN))
share_files = {
    # py files deployed from auto_flash
    "config.py":            "deployed from auto_flash",
    "pipeline.py":          "deployed from auto_flash",
    "build.py":             "deployed from auto_flash",
    "flash.py":             "deployed from auto_flash",
    "verify.py":            "deployed from auto_flash",
    "notify.py":            "deployed from auto_flash",
    "img_finder.py":        "deployed from auto_flash",
    "watcher_client.py":    "deployed from auto_flash",
    "sync_code.py":         "deployed from auto_flash",
    "cp_download.py":       "deployed from auto_flash",
    "build_abl.py":         "deployed from auto_flash",
    "build_kernel.py":      "deployed from auto_flash",
    "cp_img.py":            "deployed from auto_flash",
    "ota_flash_verify.py":  "deployed from auto_flash",
    "watcher.py":           "deployed from auto_flash",
    "deploy.py":            "deployed from auto_flash",
    "verify_deploy.py":     "deployed from auto_flash",
    # sh / json maintained in share
    "project.json":         "shared config",
    "cp_download.sh":       "copy downloads script",
    "cp_images.sh":         "image copy script",
    "sync_and_build_ok.sh": "build script",
}
for fname, desc in share_files.items():
    fp = SHARE_WIN / fname
    exists = fp.exists()
    detail = "{:.1f} KB".format(fp.stat().st_size / 1024) if exists else "NOT FOUND"
    check("{} ({})".format(fname, desc), exists, detail)

# ── 2b. SHARE_DIR py files in sync with AUTO_FLASH ────────
print("\n[2b] SHARE_DIR py files in sync with AUTO_FLASH")
py_files = [f for f in auto_files if f.endswith(".py")]
for fname in py_files:
    src_fp  = AUTO_FLASH / fname
    dst_fp  = SHARE_WIN  / fname
    if not src_fp.exists() or not dst_fp.exists():
        check("{} in sync".format(fname), False, "file missing")
        continue
    src_bytes = src_fp.read_bytes()
    dst_bytes = dst_fp.read_bytes()
    in_sync = src_bytes == dst_bytes
    check("{} in sync".format(fname), in_sync,
          "OK" if in_sync else "OUT OF SYNC - run deploy.py")

# ── 3. project.json schema ────────────────────────────────
print("\n[3] project.json schema & values")
pj = json.loads((SHARE_WIN / "project.json").read_text(encoding="utf-8"))
for k in ["project_root", "server_share_path", "target", "build_type", "files_to_copy"]:
    check("key: {:<24}".format(k), k in pj, str(pj.get(k, "MISSING")))
check("build_server_user absent", "build_server_user" not in pj,
      "OK" if "build_server_user" not in pj else "STILL PRESENT")

# ── 4. Python syntax ──────────────────────────────────────
print("\n[4] Python syntax check")
for fname, base in (
    [(f, SHARE_WIN) for f in ["watcher.py"]] +
    [(f, AUTO_FLASH) for f in ["config.py","pipeline.py","build.py","flash.py",
                                "verify.py","notify.py","img_finder.py"]]
):
    fp = base / fname
    if not fp.exists():
        check(fname, False, "file missing")
        continue
    try:
        ast.parse(fp.read_text(encoding="utf-8"))
        check(fname, True, "syntax OK")
    except SyntaxError as e:
        check(fname, False, str(e))

# ── 5. config.py loads project.json ──────────────────────
print("\n[5] config.py loads project.json")
out = buf.getvalue()
for line in out.strip().splitlines()[:6]:   # first load only
    print("       " + line)
check("PROJECT_ROOT loaded",      bool(config.PROJECT_ROOT))
check("SERVER_SHARE_PATH loaded", bool(config.SERVER_SHARE_PATH))
check("TARGET loaded",            bool(config.TARGET))
check("BUILD_TYPE loaded",        bool(config.BUILD_TYPE))
check("FILES_TO_COPY loaded",     bool(config.FILES_TO_COPY))
check("BUILD_SERVER_USER absent", not hasattr(config, "BUILD_SERVER_USER"))

# ── 6. BUILD_CMD / CP_CMD ─────────────────────────────────
print("\n[6] BUILD_CMD / CP_CMD sh paths")
srv = pj["server_share_path"]
pr  = pj["project_root"]
# SYNC: sh from SHARE_DIR (workspace not yet created)
check("SYNC_CMD sh from SHARE_DIR",            srv in config.SYNC_CMD,        config.SYNC_CMD)
# ABL/KERNEL/IMG/CP: sh from PROJECT_ROOT (copied by watcher)
check("BUILD_ABL_CMD sh from PROJECT_ROOT",    pr in config.BUILD_ABL_CMD,    config.BUILD_ABL_CMD)
check("BUILD_KERNEL_CMD sh from PROJECT_ROOT", pr in config.BUILD_KERNEL_CMD, config.BUILD_KERNEL_CMD)
check("BUILD_CMD sh from PROJECT_ROOT",        pr in config.BUILD_CMD,        config.BUILD_CMD)
check("CP_CMD sh from PROJECT_ROOT",           pr in config.CP_CMD,           config.CP_CMD)
check("CP_CMD    passes PROJECT_ROOT", pj["project_root"] in config.CP_CMD)
check("BUILD_CMD passes target",     pj["target"]      in config.BUILD_CMD)
check("BUILD_CMD passes build_type", pj["build_type"]  in config.BUILD_CMD)

# ── 7. watcher.py ─────────────────────────────────────────
print("\n[7] watcher.py")
wsrc    = (SHARE_WIN / "watcher.py").read_text(encoding="utf-8")
wsrc_nc = re.sub(r"#.*", "", wsrc)
check("reads project.json",        "project.json"          in wsrc)
check("no hardcoded share path",   pj["server_share_path"] not in wsrc_nc)
check("no hardcoded project_root", pj["project_root"]      not in wsrc_nc)
check("injects SHARE_DIR to env",  '"SHARE_DIR"'           in wsrc)
check("prints [CONFIG] on start",  "[CONFIG]"              in wsrc)

# ── 8. sh scripts ─────────────────────────────────────────
print("\n[8] sh scripts")
for sh in ["cp_images.sh", "sync_and_build_ok.sh"]:
    src    = (SHARE_WIN / sh).read_text(encoding="utf-8")
    src_nc = re.sub(r"#.*", "", src)
    check("{}: reads project.json".format(sh[:22]), "project.json" in src)
    check("{}: no hardcoded paths".format(sh[:22]), pj["server_share_path"] not in src_nc)
    check("{}: prints [CONFIG]".format(sh[:22]),    "[CONFIG]"     in src)

# ── 9. No stale runtime files ─────────────────────────────
print("\n[9] No stale runtime files in SHARE_DIR")
for f in ["trigger.json", "trigger_choice.json", "ping.json"]:
    fp = SHARE_WIN / f
    check("no stale {}".format(f), not fp.exists(),
          "clean" if not fp.exists() else "EXISTS (leftover)")

# ── Summary ───────────────────────────────────────────────
total = ok_n + fail_n
print()
print("=" * 60)
print("  Result : {}/{} {}".format(
    ok_n, total,
    "ALL PASSED" if fail_n == 0 else "{} FAILED".format(fail_n)))
print("=" * 60)
if fail_n:
    sys.exit(1)