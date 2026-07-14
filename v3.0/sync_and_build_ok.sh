#!/bin/bash
# =============================================================================
# sync_and_build_ok.sh
# Build Options: -sync -abl -ker -img
# Param Options: -ws <name>  -tg <target>  -tp <build_type>
# =============================================================================

set -e

# == Load project.json ========================================================
_PROJ_JSON="${SHARE_DIR}/project.json"
if [[ -z "$SHARE_DIR" || ! -f "$_PROJ_JSON" ]]; then
    _SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    _PROJ_JSON="$_SCRIPT_DIR/project.json"
fi
if [[ ! -f "$_PROJ_JSON" ]]; then
    echo "ERROR: project.json not found." >&2; exit 1
fi

DEFAULT_TARGET=$(jq -r .target           "$_PROJ_JSON")
DEFAULT_BUILD_TYPE=$(jq -r .build_type   "$_PROJ_JSON")
DEFAULT_PROJECT_NAME=$(jq -r .project_name "$_PROJ_JSON")
LINT_TOOLS_DIR=$(jq -r .lint_tools_dir   "$_PROJ_JSON")
SYNC_CMD_TMPL=$(jq -r .sync_cmd          "$_PROJ_JSON")
PROJECT_ROOT=$(jq -r .project_root       "$_PROJ_JSON")
WORKSPACE_BASE=$(jq -r .workspace_base   "$_PROJ_JSON")

echo "[CONFIG] project.json   : $_PROJ_JSON"
echo "[CONFIG] TARGET         : $DEFAULT_TARGET"
echo "[CONFIG] BUILD_TYPE     : $DEFAULT_BUILD_TYPE"
echo "[CONFIG] PROJECT_NAME   : $DEFAULT_PROJECT_NAME"
echo "[CONFIG] LINT_TOOLS_DIR : $LINT_TOOLS_DIR"
echo "[CONFIG] PROJECT_ROOT   : $PROJECT_ROOT"
echo "[CONFIG] WORKSPACE_BASE : $WORKSPACE_BASE"

# == Build switches ===========================================================
ENABLE_SYNC=false; ENABLE_ABL_BUILD=false
ENABLE_KERNEL_BUILD=false; ENABLE_APPS_BUILD=false

for ARG in "$@"; do
    case "$ARG" in
        -sync) ENABLE_SYNC=true ;;
        -abl)  ENABLE_ABL_BUILD=true ;;
        -ker)  ENABLE_KERNEL_BUILD=true ;;
        -img)  ENABLE_APPS_BUILD=true ;;
    esac
done

# ---- Param overrides ----
TARGET="$DEFAULT_TARGET"
BUILD_TYPE="$DEFAULT_BUILD_TYPE"
PROJECT_NAME="$DEFAULT_PROJECT_NAME"

while [[ $# -gt 0 ]]; do
    case "$1" in
        -ws) PROJECT_NAME="$2"; shift 2 ;;
        -tg) TARGET="$2";       shift 2 ;;
        -tp) BUILD_TYPE="$2";   shift 2 ;;
        *)   shift ;;
    esac
done

# Expand placeholders: {lint_tools_dir} and {target} using sed
# (bash string replacement cannot handle { } in patterns reliably)
SYNC_CMD=$(echo "$SYNC_CMD_TMPL" | sed "s|{lint_tools_dir}|$LINT_TOOLS_DIR|g; s|{target}|$TARGET|g")

# == Color helpers ============================================================
GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; BLUE='\033[0;34m'; NC='\033[0m'
log_info()  { echo -e "${GREEN}[INFO]${NC}  $1"; }
log_warn()  { echo -e "${YELLOW}[WARN]${NC}  $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }
log_step()  { echo -e "\n${BLUE}========== $1 ==========${NC}"; }

log_info "--------------------------------------------------------------------"
log_info "Target       : $TARGET  |  BuildType : $BUILD_TYPE"
log_info "ProjectName  : $PROJECT_NAME"
log_info "Sync         : $ENABLE_SYNC  |  ABL: $ENABLE_ABL_BUILD  |  Ker: $ENABLE_KERNEL_BUILD  |  IMG: $ENABLE_APPS_BUILD"
log_info "Sync cmd     : $SYNC_CMD"
log_info "--------------------------------------------------------------------"

# == Step 1: Workspace Setup ==================================================
log_step "Step 1: Workspace Setup"

if [ "$ENABLE_SYNC" = true ]; then
    # Create dated workspace dir under WORKSPACE_BASE
    DATE=$(date +%m%d)
    FOLDER_NAME="${PROJECT_NAME}_${DATE}"
    WORKSPACE="${WORKSPACE_BASE}/${FOLDER_NAME}"
    # Append _01/_02/... if already exists
    if [ -d "$WORKSPACE" ]; then
        IDX=1
        while [ -d "${WORKSPACE_BASE}/${FOLDER_NAME}_$(printf "%02d" $IDX)" ]; do
            IDX=$((IDX + 1))
        done
        FOLDER_NAME="${FOLDER_NAME}_$(printf "%02d" $IDX)"
        WORKSPACE="${WORKSPACE_BASE}/${FOLDER_NAME}"
    fi
    mkdir -p "$WORKSPACE"
    log_info "Created workspace : $WORKSPACE"

    # Replace "." in sync_cmd with absolute WORKSPACE path
    SYNC_CMD_ABS=$(echo "$SYNC_CMD" | sed "s| \.| $WORKSPACE|")
    log_info "Sync command      : $SYNC_CMD_ABS"
    log_info "Starting sync..."
    cd "$WORKSPACE"
    eval "$SYNC_CMD_ABS"
    log_info "Sync completed!"

    # Auto-update project_root in project.json
    _TMP="${_PROJ_JSON}.tmp"
    jq --arg r "$WORKSPACE" '.project_root = $r' "$_PROJ_JSON" > "$_TMP" && mv "$_TMP" "$_PROJ_JSON"
    log_info "[CONFIG] project_root updated -> $WORKSPACE"
    PROJECT_ROOT="$WORKSPACE"

else
    WORKSPACE="$PROJECT_ROOT"
    if [ ! -d "$WORKSPACE" ]; then
        log_error "Workspace not found: $WORKSPACE"
        log_error "Hint: run with -sync first, or check project_root in project.json"
        exit 1
    fi
    cd "$WORKSPACE"
    log_warn "Sync skipped, using existing workspace: $WORKSPACE"
fi
log_info "Workspace: $WORKSPACE"

# == Step 2: ABL Build ========================================================
if [ "$ENABLE_ABL_BUILD" = true ]; then
    log_step "Step 2: ABL Build"
    KERNEL_VER=$(ls -d "$WORKSPACE"/src/kernel-* 2>/dev/null | head -1 | xargs basename)
    [[ -z "$KERNEL_VER" ]] && { log_error "No kernel dir in $WORKSPACE/src/"; exit 1; }
    log_info "Kernel: $KERNEL_VER"
    cd "$WORKSPACE/src/${KERNEL_VER}/kernel_platform"
    ./tools/bazel run //soc-repo:${TARGET}-le_${BUILD_TYPE}-defconfig_abl_dist 2>&1 | tee ../build_abl.log
    log_info "ABL build completed!"
else
    log_warn "Step 2: ABL build skipped"
fi

# == Step 3: Kernel Build =====================================================
if [ "$ENABLE_KERNEL_BUILD" = true ]; then
    log_step "Step 3: Kernel Build (${BUILD_TYPE})"
    KERNEL_VER=$(ls -d "$WORKSPACE"/src/kernel-* 2>/dev/null | head -1 | xargs basename)
    [[ -z "$KERNEL_VER" ]] && { log_error "No kernel dir in $WORKSPACE/src/"; exit 1; }
    log_info "Kernel: $KERNEL_VER"
    KERNEL_PLATFORM="$WORKSPACE/src/${KERNEL_VER}/kernel_platform"
    # build_with_bazel.py outputs to kernel_platform/out/... (hardcoded in bazel dist scripts)
    # BUILD_WORKSPACE_DIRECTORY must be set explicitly -- only injected by "bazel run", not build_with_bazel.py
    BAZEL="$KERNEL_PLATFORM/out/msm-kernel-${TARGET}_le-${BUILD_TYPE}_defconfig"
    # bitbake expects: src/kernel-X.XX/out/.../dist  (without kernel_platform/)
    BITBAKE="$WORKSPACE/src/${KERNEL_VER}/out/msm-kernel-${TARGET}_le-${BUILD_TYPE}_defconfig"

	
    cd "$KERNEL_PLATFORM"
    # Inline-inject BUILD_WORKSPACE_DIRECTORY so dist scripts can resolve paths correctly
    BUILD_WORKSPACE_DIRECTORY="$KERNEL_PLATFORM" \
        ./build_with_bazel.py -t ${TARGET}-le ${BUILD_TYPE}-defconfig

    # Verify the key artifact bitbake needs
    UAPI_HDR="$BAZEL/dist/${TARGET}-le_${BUILD_TYPE}-defconfig_kernel-uapi-headers.tar.gz"
    if [[ ! -f "$UAPI_HDR" ]]; then
        log_error "Kernel build artifact missing: $UAPI_HDR"
        log_info "Contents of $BAZEL/dist:"
        ls -la "$BAZEL/dist" 2>/dev/null || true
        exit 1
    fi

    # Copy real files to bitbake expected path (cp -rL follows symlinks)
    log_info "Copying kernel dist to bitbake path: $BITBAKE"
    mkdir -p "$BITBAKE"
    cp -rL "$BAZEL/." "$BITBAKE/"


    log_info "Kernel dist (bazel)  : $BAZEL"
    log_info "Kernel dist (bitbake): $BITBAKE"
    log_info "uapi-headers         : OK"
    log_info "Kernel build completed!"
else
    log_warn "Step 3: Kernel build skipped"
fi

# == Step 4: APPS Image Build =================================================
if [ "$ENABLE_APPS_BUILD" = true ]; then
    log_step "Step 4: APPS Image Build"
    cd "$WORKSPACE"
    log_info "Working directory: $(pwd)"
    MACHINE=${TARGET} DISTRO=qti-distro-fullstack-${BUILD_TYPE} source poky/qti-conf/set_bb_env.sh
    log_info "Building qti-multimedia-image..."
    bitbake qti-multimedia-image
    log_info "APPS image build completed!"
else
    log_warn "Step 4: APPS build skipped"
fi

# == Done =====================================================================
log_step "All Steps Completed Successfully"
log_info "Workspace : $WORKSPACE  |  Target : $TARGET  |  BuildType : $BUILD_TYPE"