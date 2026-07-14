# =============================================================================
# sync_code.py -- Trigger remote code sync via watcher
#
# Usage:
#   python sync_code.py
#
# What it does:
#   1. Ping watcher to confirm it is alive
#   2. Write trigger.json with SYNC_CMD (sync_and_build_ok.sh -sync)
#   3. Tail watcher.log in real time
#   4. Poll status.json until done / error
#   5. After sync completes, project.json project_root is auto-updated
#      by the sh script; config is reloaded so all subsequent steps
#      (cp_download, build_abl, build_kernel, build) use the new PROJECT_ROOT
# =============================================================================

import sys
import importlib
import config
from watcher_client import run_trigger


def _reload_config():
    """
    Reload config after sync so PROJECT_ROOT and all derived commands
    reflect the new workspace written back by sync_and_build_ok.sh.
    """
    old_root = config.PROJECT_ROOT

    importlib.reload(config)

    new_root = config.PROJECT_ROOT
    print("[SYNC] project_root : {} -> {}".format(old_root, new_root))
    print("[SYNC] BUILD_CMD    : {}".format(config.BUILD_CMD))
    print("[SYNC] CP_CMD       : {}".format(config.CP_CMD))

    # Reload dependent modules so they pick up new config.* values
    for mod_name in ["cp_download", "build_abl", "build_kernel", "build"]:
        mod = sys.modules.get(mod_name)
        if mod is not None:
            importlib.reload(mod)


def trigger_sync():
    print("=" * 60)
    print("  Remote Code Sync")
    print("=" * 60)
    ok = run_trigger(
        label = "SYNC",
        cmd   = config.SYNC_CMD,
    )
    if ok:
        print("[SYNC] Sync completed. Reloading config ...")
        _reload_config()
    return ok


if __name__ == "__main__":
    ok = trigger_sync()
    sys.exit(0 if ok else 1)