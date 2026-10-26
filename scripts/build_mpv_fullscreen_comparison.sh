#!/usr/bin/env bash
# Diagnostic source builds only; the app's normal archive acquisition is unchanged.
set -euo pipefail

repository_root=$(cd "$(dirname "$0")/.." && pwd)
comparison_root=${1:?Usage: build_mpv_fullscreen_comparison.sh OUTPUT_DIRECTORY}
mkdir -p "$comparison_root"
comparison_root=$(cd "$comparison_root" && pwd)
source_revision=3aecc359bb815475dc50909ba06b40d8a1a26dad

sw_vers > "$comparison_root/host.txt"
xcrun swiftc --version > "$comparison_root/swift-version.txt"
xcrun clang --version > "$comparison_root/clang-version.txt"
xcrun --show-sdk-path > "$comparison_root/sdk-path.txt"
brew config > "$comparison_root/homebrew-config.txt"
brew list --versions > "$comparison_root/homebrew-versions.txt"
cp "$repository_root/patches/mpv-fullscreen-owner.patch" "$comparison_root/source.patch"
shasum -a 256 "$comparison_root/source.patch" > "$comparison_root/source-patch.sha256"

git clone --no-checkout https://github.com/mpv-player/mpv.git "$comparison_root/source"
git -C "$comparison_root/source" checkout --detach "$source_revision"
git -C "$comparison_root/source" rev-parse HEAD > "$comparison_root/source-revision.txt"
test "$(cat "$comparison_root/source-revision.txt")" = "$source_revision"

for variant in original patched; do
    source_directory="$comparison_root/source-$variant"
    git -C "$comparison_root/source" worktree add --detach "$source_directory" "$source_revision"
    if [[ "$variant" == patched ]]; then
        git -C "$source_directory" apply --check "$comparison_root/source.patch"
        git -C "$source_directory" apply "$comparison_root/source.patch"
        git -C "$source_directory" diff --exit-code -- . ':!video/out/mac/window.swift'
        git -C "$source_directory" diff > "$comparison_root/patched-source.diff"
    else
        git -C "$source_directory" diff --exit-code
    fi

    (
        cd "$source_directory"
        # Flags follow the pinned upstream ci/build-macos.sh and build-common.sh.
        # Omit meson install: the bundle is made from the build directory.
        export CFLAGS="${CFLAGS:-} -U_FORTIFY_SOURCE -D_FORTIFY_SOURCE=3"
        PKG_CONFIG_PATH="$(brew --prefix libarchive)/lib/pkgconfig/" CC=clang CXX=clang++ \
        meson setup build --werror -Dlibmpv=true -Dtests=true \
            -Dobjc_args='-Wno-error=deprecated -Wno-error=deprecated-declarations' \
            -Dc_args='' \
            -D{caca,cdda,dvda,dvdnav,gl,iconv,lcms2,libarchive,libbluray,lua,jpeg}=enabled \
            -D{plain-gl,rubberband,sixel,vapoursynth,zimg,zlib}=enabled \
            -D{cocoa,coreaudio,gl-cocoa,videotoolbox-gl,videotoolbox-pl}=enabled \
            -D{swift-build,macos-cocoa-cb,macos-media-player,macos-touchbar,vulkan}=enabled \
            -Dswift-flags=''
        meson compile -C build -j4
        ./build/mpv --no-config --version > "$comparison_root/$variant-version.txt"
        meson introspect build --buildoptions > "$comparison_root/$variant-buildoptions.json"
        meson introspect build --dependencies > "$comparison_root/$variant-dependencies.json"
        meson test -C build --print-errorlogs
        meson compile -C build macos-bundle
        codesign --verify --deep --strict build/mpv.app
        tar -czf "$comparison_root/rebuilt-$variant-mpv.tar.gz" -C build mpv.app
    ) 2>&1 | tee "$comparison_root/$variant-build.log"
done

shasum -a 256 "$comparison_root"/rebuilt-*-mpv.tar.gz > "$comparison_root/archive-sha256.txt"
