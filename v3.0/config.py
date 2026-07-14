# =============================================================================
# config.py -- All configurable items here, modify according to your environment
# =============================================================================

# ============================================================================
# [CHANGE HERE] Local Windows paths
# ============================================================================
PLATFORM_TOOLS_DIR = r"C:\UPON\anroidtool\platform-tools"   # adb/fastboot dir
LOCAL_WORKSPACE    = r"C:\UPON\py_tool\auto_flash"           # this project dir

# ============================================================================
# [CHANGE HERE] Shared directory (Windows mount path)
# project.json inside this dir provides all shared config with Server side
# ============================================================================
WIN_SHARE_PATH = r"C:\UPON\share_ai_bak"

# ============================================================================
# Load shared config from project.json
# Shared between: config.py / watcher.py / cp_images.sh / sync_and_build_ok.sh
# ============================================================================
import json as _json
from pathlib import Path as _Path

_project_json = _Path(WIN_SHARE_PATH) / "project.json"
if _project_json.exists():
    _proj = _json.loads(_project_json.read_text(encoding="utf-8"))
else:
    raise FileNotFoundError(
        "project.json not found: {}\n"
        "Please create it in the shared directory.".format(_project_json)
    )

PROJECT_ROOT      = _proj["project_root"]       # Server: project root dir
SERVER_SHARE_PATH = _proj["server_share_path"]  # Server: share dir path
TARGET            = _proj["target"]             # e.g. "alor"
BUILD_TYPE        = _proj["build_type"]         # "debug" / "perf"
FILES_TO_COPY     = _proj["files_to_copy"]      # list of image filenames
DOWNLOADS_SRC     = _proj["downloads_src"]      # source downloads dir for cp_download

print("[CONFIG] Loaded project.json : {}".format(_project_json))
print("[CONFIG] PROJECT_ROOT        : {}".format(PROJECT_ROOT))
print("[CONFIG] SERVER_SHARE_PATH   : {}".format(SERVER_SHARE_PATH))
print("[CONFIG] TARGET              : {}".format(TARGET))
print("[CONFIG] BUILD_TYPE          : {}".format(BUILD_TYPE))
print("[CONFIG] FILES_TO_COPY       : {}".format(FILES_TO_COPY))
print("[CONFIG] DOWNLOADS_SRC       : {}".format(DOWNLOADS_SRC))

# =============================================================================
# Derived paths -- auto-generated from above, do NOT edit
# =============================================================================

# -- Step commands ----------------------------------------------------------
# Each step runs sync_and_build_ok.sh with the corresponding flag.
# cd to SHARE_DIR for sync (new workspace created under WORKSPACE_BASE);
# cd to PROJECT_ROOT for build steps (workspace already exists).
# sh scripts are copied from SHARE_DIR to PROJECT_ROOT by watcher._ensure_sh_executable
# SYNC: workspace does not exist yet, run sh from SHARE_DIR
# ABL/KERNEL/IMG: workspace exists, run sh from PROJECT_ROOT (copied)
_SH_SHARE   = "bash {}/sync_and_build_ok.sh".format(SERVER_SHARE_PATH)
_SH_PROJECT = "bash {}/sync_and_build_ok.sh".format(PROJECT_ROOT)
_TG = "-tg {} -tp {}".format(TARGET, BUILD_TYPE)

SYNC_CMD          = "cd {} && {} -sync {}".format(SERVER_SHARE_PATH, _SH_SHARE, _TG)

BUILD_ABL_CMD     = "cd {} && {} -abl {}".format(PROJECT_ROOT, _SH_PROJECT, _TG)

BUILD_KERNEL_CMD  = "cd {} && {} -ker {}".format(PROJECT_ROOT, _SH_PROJECT, _TG)

BUILD_CMD         = "cd {} && {} -img {}".format(PROJECT_ROOT, _SH_PROJECT, _TG)

# -- Copy images to shared path ----------------------------------------------
CP_CMD     = "bash {}/cp_images.sh {}".format(PROJECT_ROOT, PROJECT_ROOT)
CP_CHOICE        = "0"   # auto-select first candidate; set None for manual input
BUILD_IMG_RETRIES = 3    # max retry attempts for img build on bitbake reconnect

# -- Copy downloads dir after sync -------------------------------------------
# downloads_src is fixed reference project; project_root is updated after sync.
DOWNLOADS_SRC     = _proj["downloads_src"]
CP_DOWNLOAD_FORCE = False   # set True to overwrite existing downloads dir

def CP_DOWNLOAD_CMD(force=None):
    """Return cp_download.sh command. force=None uses CP_DOWNLOAD_FORCE."""
    import config as _c
    _force = force if force is not None else _c.CP_DOWNLOAD_FORCE
    base = "bash {}/cp_download.sh {} {}".format(
        _c.PROJECT_ROOT, _c.DOWNLOADS_SRC, _c.PROJECT_ROOT)
    return (base + " --force") if _force else base

# -- Shared json files -------------------------------------------------------
_WIN             = _Path(WIN_SHARE_PATH)
WIN_TRIGGER_FILE = str(_WIN / "trigger.json")
WIN_STATUS_FILE  = str(_WIN / "status.json")
WIN_CHOICE_FILE  = str(_WIN / "trigger_choice.json")
WIN_PING_FILE    = str(_WIN / "ping.json")

# -- Image directory ---------------------------------------------------------
# cp_images.sh copies to {WIN_SHARE_PATH}/{TARGET}_{TIMESTAMP}/
# IMG_MAP: filename -> fastboot partition name (None = skip)
IMG_MAP = {f: f.replace(".img", "").replace(".elf", "") for f in FILES_TO_COPY}
IMG_MAP["full_update_ext4.zip"] = None   # OTA zip, skip fastboot flash
IMG_MAP["abl.elf"]              = "abl"

# Partitions to flash (ordered). Derived from FILES_TO_COPY, excluding skipped.
FLASH_PARTITIONS = [v for f, v in IMG_MAP.items() if v is not None]

# -- ADB / Fastboot ----------------------------------------------------------
ADB_PATH      = "{}\\adb.exe".format(PLATFORM_TOOLS_DIR)
FASTBOOT_PATH = "{}\\fastboot.exe".format(PLATFORM_TOOLS_DIR)
DEVICE_SERIAL = None

# -- Flash parameters --------------------------------------------------------
FASTBOOT_WAIT_SEC = 15

# -- Log capture -------------------------------------------------------------
LOG_DIR         = "{}\\logs".format(WIN_SHARE_PATH)
LOGCAT_DURATION = 120

ERROR_KEYWORDS = [
    "FATAL EXCEPTION",
    "kernel panic",
    "ANR in",
    "E HWASan",
    "AddressSanitizer",
    "SIGSEGV",
    "SIGABRT",
]

PASS_KEYWORDS = [
    "Boot completed",
    "sys.boot_completed=1",
]

# -- Email notification (via local Outlook) ----------------------------------
NOTIFY_EMAIL = "jiahduan@qti.qualcomm.com"