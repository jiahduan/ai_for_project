import sys
import config
from watcher_client import run_script


def trigger_cp_download(force=None):
    print("=" * 60)
    print("  Copy Downloads Dir to New Workspace")
    print("=" * 60)
    # Snapshot PROJECT_ROOT at call time so cmd and project_root are consistent
    _root = config.PROJECT_ROOT
    _cmd  = config.CP_DOWNLOAD_CMD(force=force)
    print("[CP_DL] project_root : {}".format(_root))
    print("[CP_DL] cmd          : {}".format(_cmd))
    return run_script(
        label        = "CP_DL",
        cmd          = _cmd,
        project_root = _root,
    )


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--force", action="store_true",
                   help="Overwrite existing downloads dir")
    args = p.parse_args()
    ok = trigger_cp_download(force=True if args.force else None)
    sys.exit(0 if ok else 1)
