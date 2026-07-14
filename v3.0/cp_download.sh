#!/bin/bash
# =============================================================================
# cp_download.sh -- Copy downloads dir from source project to new workspace
#
# Usage:
#   bash cp_download.sh                      # use project.json values
#   bash cp_download.sh <dst_workspace>      # override dst (project_root)
#   bash cp_download.sh <src_downloads> <dst_workspace>  # override both
#
# Reads from project.json:
#   downloads_src  -- source downloads dir (fixed reference project)
#   project_root   -- destination workspace (updated after sync)
# =============================================================================

set -e

# == Load project.json ========================================================
_PROJ_JSON="${SHARE_DIR}/project.json"
if [[ -z "$SHARE_DIR" || ! -f "$_PROJ_JSON" ]]; then
    _SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    _PROJ_JSON="$_SCRIPT_DIR/project.json"
fi
if [[ ! -f "$_PROJ_JSON" ]]; then
    echo "ERROR: project.json not found." >&2
    echo "       Set SHARE_DIR env var or place project.json next to this script." >&2
    exit 1
fi

DOWNLOADS_SRC=$(jq -r .downloads_src "$_PROJ_JSON")
PROJECT_ROOT=$(jq -r .project_root   "$_PROJ_JSON")

echo "[CONFIG] project.json  : $_PROJ_JSON"
echo "[CONFIG] downloads_src : $DOWNLOADS_SRC"
echo "[CONFIG] project_root  : $PROJECT_ROOT"

# == Apply argument overrides =================================================
# Flags: --force  (force overwrite even if dst exists)
# $1 = dst_workspace (optional)
# $1 $2 = src_downloads dst_workspace (optional)
FORCE=0
ARGS=()
for arg in "$@"; do
    if [[ "$arg" == "--force" ]]; then
        FORCE=1
    else
        ARGS+=("$arg")
    fi
done

if [[ ${#ARGS[@]} -eq 2 ]]; then
    DOWNLOADS_SRC="${ARGS[0]}"
    PROJECT_ROOT="${ARGS[1]}"
    echo "[CONFIG] Override: downloads_src=$DOWNLOADS_SRC  project_root=$PROJECT_ROOT"
elif [[ ${#ARGS[@]} -eq 1 ]]; then
    PROJECT_ROOT="${ARGS[0]}"
    echo "[CONFIG] Override: project_root=$PROJECT_ROOT"
fi

DOWNLOADS_DST="${PROJECT_ROOT}/downloads"

# == Color helpers ============================================================
GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; BLUE='\033[0;34m'; NC='\033[0m'
log_info()  { echo -e "${GREEN}[INFO]${NC}  $1"; }
log_warn()  { echo -e "${YELLOW}[WARN]${NC}  $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }
log_step()  { echo -e "\n${BLUE}========== $1 ==========${NC}"; }

# == Validate =================================================================
log_step "Copy Downloads"
log_info "Source : $DOWNLOADS_SRC"
log_info "Dest   : $DOWNLOADS_DST"

if [[ ! -d "$DOWNLOADS_SRC" ]]; then
    log_error "Source downloads dir not found: $DOWNLOADS_SRC"
    exit 1
fi

if [[ ! -d "$PROJECT_ROOT" ]]; then
    log_error "Destination workspace not found: $PROJECT_ROOT"
    exit 1
fi

if [[ -d "$DOWNLOADS_DST" ]]; then
    if [[ $FORCE -eq 1 ]]; then
        log_warn "Destination already exists: $DOWNLOADS_DST"
        log_warn "--force specified: removing existing destination ..."
        rm -rf "$DOWNLOADS_DST"
        log_info "Removed: $DOWNLOADS_DST"
    else
        log_warn "Destination already exists: $DOWNLOADS_DST"
        log_warn "Skipping copy to avoid overwrite. Use --force to overwrite."
        exit 0
    fi
fi

# == Copy =====================================================================
SRC_SIZE=$(du -sh "$DOWNLOADS_SRC" 2>/dev/null | cut -f1)
log_info "Source size : ${SRC_SIZE:-unknown}"
log_info "Copying (hard-link where possible with cp -al) ..."

# Try hard-link first (same filesystem, instant); fall back to regular copy
if cp -al "$DOWNLOADS_SRC" "$DOWNLOADS_DST" 2>/dev/null; then
    log_info "Hard-link copy completed: $DOWNLOADS_DST"
else
    log_warn "Hard-link failed (cross-device?), falling back to regular copy ..."
    cp -a "$DOWNLOADS_SRC" "$DOWNLOADS_DST"
    log_info "Regular copy completed: $DOWNLOADS_DST"
fi

DST_SIZE=$(du -sh "$DOWNLOADS_DST" 2>/dev/null | cut -f1)
log_info "Dest size   : ${DST_SIZE:-unknown}"
log_info "Done: $DOWNLOADS_DST"