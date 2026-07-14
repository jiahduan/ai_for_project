import sys
import config
from watcher_client import run_trigger


def trigger_build_abl():
    print("=" * 60)
    print("  Remote ABL Build")
    print("=" * 60)
    _root = config.PROJECT_ROOT
    _cmd  = config.BUILD_ABL_CMD
    print("[ABL] project_root : {}".format(_root))
    print("[ABL] cmd          : {}".format(_cmd))
    return run_trigger(
        label        = "ABL",
        cmd          = _cmd,
        project_root = _root,
    )


if __name__ == "__main__":
    ok = trigger_build_abl()
    sys.exit(0 if ok else 1)
