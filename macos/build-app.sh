#!/bin/bash
# Builds dist/OpenPictalis.app: a native window around the local server.
# Requires Xcode command line tools (swiftc) and python3 at runtime.
set -euo pipefail
cd "$(dirname "$0")/.."
APP=dist/OpenPictalis.app
VERSION=$(python3 -c "import openpictalis; print(openpictalis.__version__)")
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources/app" .build/swift-cache
swiftc -O -module-cache-path .build/swift-cache macos/OpenPictalis.swift -o "$APP/Contents/MacOS/OpenPictalis" -framework AppKit -framework WebKit
rsync -a --exclude __pycache__ openpictalis "$APP/Contents/Resources/app/"
mkdir -p "$APP/Contents/Resources/licenses"
cp LICENSE THIRD_PARTY_NOTICES.md "$APP/Contents/Resources/licenses/"
cp macos/AppIcon.icns "$APP/Contents/Resources/AppIcon.icns"
cat > "$APP/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>CFBundleExecutable</key><string>OpenPictalis</string>
  <key>CFBundleIdentifier</key><string>org.openpictalis.app</string>
  <key>CFBundleName</key><string>OpenPictalis</string>
  <key>CFBundleDisplayName</key><string>OpenPictalis</string>
  <key>CFBundleIconFile</key><string>AppIcon</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>${VERSION}</string>
  <key>CFBundleVersion</key><string>${VERSION}</string>
  <key>LSMinimumSystemVersion</key><string>13.0</string>
  <key>NSHighResolutionCapable</key><true/>
  <key>NSAppTransportSecurity</key><dict><key>NSAllowsLocalNetworking</key><true/></dict>
</dict></plist>
PLIST
codesign --force --deep --sign - "$APP"
echo "Built $APP ($VERSION)"
