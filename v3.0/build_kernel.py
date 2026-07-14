import sys
import config
from watcher_client import run_trigger


def trigger_build_kernel():
    print("=" * 60)
    print("  Remote Kernel Build")
    print("=" * 60)
    _root = config.PROJECT_ROOT
    _cmd  = config.BUILD_KERNEL_CMD
    print("[KERNEL] project_root : {}".format(_root))
    print("[KERNEL] cmd          : {}".format(_cmd))
    return run_trigger(
        label        = "KERNEL",
        cmd          = _cmd,
        project_root = _root,
    )


if __name__ == "__main__":
    ok = trigger_build_kernel()
    sys.exit(0 if ok else 1)
