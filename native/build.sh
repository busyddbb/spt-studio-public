#!/bin/zsh
set -euo pipefail

native_dir="${0:A:h}"
# SPT_OUT: where to build (default native/build/SPT.app).
# SPT_BUNDLE_ID: keep an existing app's identity (its logins and settings); default is a fresh one.
# SPT_FIXED_ROOT=1: remember this folder's path, for an app installed in ~/Applications on this Mac.
bundle_dir="${SPT_OUT:-$native_dir/build/SPT.app}"
mkdir -p "$bundle_dir/Contents/MacOS" "$bundle_dir/Contents/Resources"

sources=()
for name in MediaDesk NativeWorkspaceStore NativeWorkspaceViews NativeWorkDetail NativePublishingView \
    NativeDraftEditor NativeAccountEditor PublishingWorkspace RednoteUpload RednoteSessionVault PublishingQueue MetricsReader; do
  sources+=("$native_dir/$name.swift")
done
# Universal binary (Apple silicon + Intel). Intermediate files go to one fixed folder in the
# system temp area that every build reuses (about 700 MB), so builds never pile up copies.
scratch="${${TMPDIR:-/tmp}%/}/spt-native-build"
mkdir -p "$scratch"
for arch in arm64 x86_64; do
  xcrun swiftc -O -whole-module-optimization -parse-as-library \
    -module-cache-path "$scratch/ModuleCache" \
    -target "$arch-apple-macosx12.0" \
    -framework AppKit -framework WebKit -framework UniformTypeIdentifiers -framework Security -framework LocalAuthentication -framework SwiftUI -framework AVKit \
    "${sources[@]}" \
    -o "$scratch/MediaDesk-$arch"
done
xcrun lipo -create "$scratch/MediaDesk-arm64" "$scratch/MediaDesk-x86_64" -output "$bundle_dir/Contents/MacOS/MediaDesk"

cat > "$bundle_dir/Contents/Info.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>CFBundleExecutable</key><string>MediaDesk</string>
  <key>CFBundleIdentifier</key><string>local.spt.studio</string>
  <key>CFBundleName</key><string>SPT</string>
  <key>CFBundleDisplayName</key><string>SPT</string>
  <key>CFBundleIconFile</key><string>SPT</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleVersion</key><string>9</string>
  <key>CFBundleShortVersionString</key><string>0.8.1</string>
  <key>LSMinimumSystemVersion</key><string>12.0</string>
  <key>NSPrincipalClass</key><string>NSApplication</string>
  <key>NSHighResolutionCapable</key><true/>
  <key>NSDesktopFolderUsageDescription</key><string>读取 SPT 文件夹里的资料与您选择的本地素材。</string>
  <key>NSAppTransportSecurity</key><dict>
    <key>NSAllowsLocalNetworking</key><true/>
  </dict>
</dict></plist>
PLIST

/usr/bin/plutil -replace CFBundleIdentifier -string "${SPT_BUNDLE_ID:-local.spt.studio}" "$bundle_dir/Contents/Info.plist"
if [[ "${SPT_FIXED_ROOT:-}" == 1 ]]; then
  /usr/bin/plutil -replace MediaDeskWorkspaceRoot -string "${native_dir:h}" "$bundle_dir/Contents/Info.plist"
fi
cp "$native_dir/SPT.icns" "$bundle_dir/Contents/Resources/SPT.icns"
cp "$native_dir/PublishingQueueDOM.js" "$bundle_dir/Contents/Resources/PublishingQueueDOM.js"
cp "$native_dir/MetricsReaderDOM.js" "$bundle_dir/Contents/Resources/MetricsReaderDOM.js"
# No fixed folder path: the app finds the SPT folder from its own location, so copies work on other Macs.
/usr/bin/plutil -lint "$bundle_dir/Contents/Info.plist"
/usr/bin/codesign --force --sign "${SPT_SIGN_IDENTITY:--}" "$bundle_dir"
/usr/bin/codesign --verify --strict "$bundle_dir"
print -r -- "$bundle_dir"
