#!/bin/bash
# =============================================================================
# cp_images.sh -- Copy built images to shared directory
#
# Usage:
#   bash cp_images.sh <project_root>
#
# Reads from project.json (via SHARE_DIR env):
#   server_share_path  -- destination base dir
#   files_to_copy      -- list of image filenames to copy
#
# Searches under <project_root> for:
#   tmp-glibc/deploy/images/*/qti-multimedia-image/
#
# If multiple candidates found:
#   - Uses CP_CHOICE env var if set (0-based index)
#   - Otherwise prompts user
# =============================================================================

set -e

SEARCH_ROOT="${1:-$PWD}"

# == Load project.json ========================================================
_PROJ_JSON="${SHARE_DIR}/project.json"
if [[ -z "$SHARE_DIR" || ! -f "$_PROJ_JSON" ]]; then
    _SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    _PROJ_JSON="$_SCRIPT_DIR/project.json"
fi
if [[ ! -f "$_PROJ_JSON" ]]; then
    echo "ERROR: project.json not found." >&2
    exit 1
fi

SHARE_DIR=$(jq -r .server_share_path "$_PROJ_JSON")
mapfile -t FILES_TO_COPY < <(jq -r ".files_to_copy[]" "$_PROJ_JSON")

echo "[CONFIG] Loaded project.json : $_PROJ_JSON"
echo "[CONFIG] SHARE_DIR           : $SHARE_DIR"
echo "[CONFIG] FILES_TO_COPY       : ${FILES_TO_COPY[*]}"
echo "[CONFIG] SEARCH_ROOT         : $SEARCH_ROOT"
echo "--------------------------------------------------------------------------"

# == Find candidate image dirs ================================================
FOUND_DIRS=()
while IFS= read -r tmp_dir; do
    img_dir="$tmp_dir/deploy/images"
    [[ -d "$img_dir" ]] || continue
    for target_dir in "$img_dir"/*/; do
        qti_dir="${target_dir}qti-multimedia-image"
        [[ -d "$qti_dir" ]] && FOUND_DIRS+=("$qti_dir")
    done
done < <(find "$SEARCH_ROOT" -maxdepth 6 -type d -name "tmp-glibc" 2>/dev/null)

if [[ ${#FOUND_DIRS[@]} -eq 0 ]]; then
    echo "ERROR: No tmp-glibc/deploy/images/*/qti-multimedia-image dir found under $SEARCH_ROOT"
    exit 1
fi

# == Select source dir ========================================================
if [[ ${#FOUND_DIRS[@]} -gt 1 ]]; then
    echo "INFO: Multiple candidate dirs found:"
    for i in "${!FOUND_DIRS[@]}"; do
        target=$(basename "$(dirname "${FOUND_DIRS[$i]}")")
        rel_path="${FOUND_DIRS[$i]#$SEARCH_ROOT/}"
        printf "  [%d] [%-8s] %s\n" "$i" "$target" "$rel_path"
    done
    echo ""

    # Use CP_CHOICE env var if set, otherwise prompt
    if [[ -n "$CP_CHOICE" ]]; then
        SEL="$CP_CHOICE"
        echo "INFO: Auto-selecting [$SEL] from CP_CHOICE env var."
    else
        read -rp "Select [0-$((${#FOUND_DIRS[@]}-1))]: " SEL
    fi

    if ! [[ "$SEL" =~ ^[0-9]+$ ]] || [[ $SEL -ge ${#FOUND_DIRS[@]} ]]; then
        echo "ERROR: Invalid selection: '$SEL'"
        exit 1
    fi
    SRC_DIR="${FOUND_DIRS[$SEL]}"
else
    SRC_DIR="${FOUND_DIRS[0]}"
fi

# == Prepare destination ======================================================
TARGET_NAME=$(basename "$(dirname "$SRC_DIR")")
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
DEST_DIR="$SHARE_DIR/${TARGET_NAME}_${TIMESTAMP}"

echo "INFO: Source dir : $SRC_DIR"
echo "INFO: Target     : $TARGET_NAME"
echo "INFO: Dest dir   : $DEST_DIR"
echo "--------------------------------------------------------------------------"

mkdir -p "$DEST_DIR" || { echo "ERROR: Failed to create dest dir"; exit 1; }
echo "LOG: mkdir DEST_DIR OK: $DEST_DIR"

GREEN='\033[0;32m'
RED='\033[0;31m'
NC='\033[0m'

# == Copy files ===============================================================
copy_file() {
    local src="$1" dst="$2" idx="$3" total="$4"
    local fname size_bytes size_hr
    fname=$(basename "$src")
    size_bytes=$(stat -c%s "$src" 2>/dev/null || echo 0)
    size_hr=$(numfmt --to=iec --suffix=B "$size_bytes" 2>/dev/null || echo "${size_bytes}B")

    printf "  [%d/%d] %-28s %s\n" "$idx" "$total" "$fname" "$size_hr"
    echo "LOG: cp start: $src -> $dst/$fname"

    local err rc
    err=$(cp "$src" "$dst/$fname" 2>&1)
    rc=$?
    echo "LOG: cp rc=$rc fname=$fname err=${err:-none}"
    return $rc
}

COPY_LIST=()
MISSING=()

# abl: try abl.elf first, then abl.bin
echo "LOG: checking abl in $SRC_DIR"
for abl in abl.elf abl.bin; do
    if [[ -f "$SRC_DIR/$abl" ]]; then
        COPY_LIST+=("$abl")
        echo "LOG: found abl: $abl"
        break
    fi
done
[[ ${#COPY_LIST[@]} -eq 0 ]] && MISSING+=("abl.elf/abl.bin") && echo "LOG: abl NOT found"

echo "LOG: checking FILES_TO_COPY in $SRC_DIR"
for f in "${FILES_TO_COPY[@]}"; do
    [[ "$f" == "abl.elf" || "$f" == "abl.bin" ]] && continue
    if [[ -f "$SRC_DIR/$f" ]]; then
        COPY_LIST+=("$f")
        echo "LOG: found: $f"
    else
        MISSING+=("$f")
        echo "LOG: missing: $f"
    fi
done

TOTAL=${#COPY_LIST[@]}
COPIED=0
echo "LOG: COPY_LIST total=$TOTAL: ${COPY_LIST[*]}"
echo "LOG: MISSING: ${MISSING[*]:-none}"

for f in "${COPY_LIST[@]}"; do
    COPIED=$((COPIED + 1))
    echo "LOG: loop COPIED=$COPIED f=$f"
    copy_file "$SRC_DIR/$f" "$DEST_DIR" "$COPIED" "$TOTAL"
    if [[ $? -eq 0 ]]; then
        printf "         ${GREEN}[OK]   %s${NC}\n" "$f"
    else
        printf "         ${RED}[FAIL] %s${NC}\n" "$f"
        exit 1
    fi
done
echo "LOG: copy loop done COPIED=$COPIED"

for f in "${MISSING[@]}"; do
    printf "  ${RED}[--]   %s (not found, skipped)${NC}\n" "$f"
done

echo "--------------------------------------------------------------------------"
echo "Done: copied $COPIED file(s) to $DEST_DIR"