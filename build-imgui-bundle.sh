#!/bin/sh
# Build the deamat callback patch against imgui_bundle v1.92.0 and its gitlinks.
# Usage: sh build-imgui-bundle.sh [output-directory]
# Set DEAMAT_IMGUI_BUILD_DIR to reuse a different checkout/build cache.
set -eu
root=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
out=${1:-"$root/dist"}
work=${DEAMAT_IMGUI_BUILD_DIR:-"$root/.cache/deamat-imgui-bundle"}
revision=45da61745fc24c5ded350ea35e834dc9d73525fc
mkdir -p "$out" "$work"
out=$(CDPATH= cd -- "$out" && pwd)
work=$(CDPATH= cd -- "$work" && pwd)
if [ ! -d "$work/source/.git" ]; then
    git init "$work/source"
fi
if ! git -C "$work/source" cat-file -e "$revision^{commit}" 2>/dev/null; then
    git -C "$work/source" fetch --depth 1 https://github.com/pthom/imgui_bundle.git "$revision"
fi
if ! git -C "$work/source" rev-parse --verify HEAD >/dev/null 2>&1; then
    git -C "$work/source" checkout --detach "$revision"
fi
if [ "$(git -C "$work/source" rev-parse HEAD)" != "$revision" ]; then
    echo "Unexpected revision in $work/source; use a fresh DEAMAT_IMGUI_BUILD_DIR" >&2
    exit 1
fi
git -C "$work/source" submodule update --init --recursive --depth 1
patch_id=$(sha256sum "$root/imgui-bundle-deamat.patch")
patch_id=${patch_id%% *}
if [ ! -f "$work/patch-$patch_id" ]; then
    git -C "$work/source" apply "$root/imgui-bundle-deamat.patch"
    touch "$work/patch-$patch_id"
fi
SKBUILD_BUILD_DIR="$work/build" uv build --wheel \
    --build-constraints "$root/imgui-bundle-build-constraints.txt" \
    --out-dir "$out" "$work/source"
printf '\nPatched wheel written to %s (version 1.92.0+deamat.1).\n' "$out"
