#!/usr/bin/env bash
# build-app.sh — compile the native WKWebView shell into a real .app bundle you can
# keep in the Dock. Click it -> opens the nathanbot (Jarvis) interface, starting the
# local server itself if needed. Installs to ~/Applications (no admin needed).
set -euo pipefail
R="$(cd "$(dirname "$0")/.." && pwd)"
APP="$HOME/Applications/nathanbot.app"

echo "• compiling native shell…"
swiftc -O "$R/app/main.swift" -o "$R/app/nathanbot"

echo "• generating arc-reactor icon…"
cat > /tmp/nbicon.swift <<'SW'
import Cocoa
let S: CGFloat = 1024
let img = NSImage(size: NSSize(width: S, height: S))
img.lockFocus()
let bg = NSBezierPath(roundedRect: NSRect(x: 0, y: 0, width: S, height: S), xRadius: 205, yRadius: 205)
NSColor(red: 0.035, green: 0.04, blue: 0.055, alpha: 1).setFill(); bg.fill()
let c = CGPoint(x: S/2, y: S/2)
NSColor(red: 0.9, green: 0.68, blue: 0.24, alpha: 0.85).setStroke()
let ring = NSBezierPath(ovalIn: NSRect(x: S*0.25, y: S*0.25, width: S*0.5, height: S*0.5))
ring.lineWidth = 24; ring.stroke()
let grad = NSGradient(colors: [
  NSColor(red: 1, green: 1, blue: 1, alpha: 1),
  NSColor(red: 0.56, green: 0.83, blue: 1, alpha: 1),
  NSColor(red: 0.9, green: 0.68, blue: 0.24, alpha: 1)])!
grad.draw(fromCenter: c, radius: 0, toCenter: c, radius: S*0.205, options: [])
img.unlockFocus()
let rep = NSBitmapImageRep(data: img.tiffRepresentation!)!
try! rep.representation(using: .png, properties: [:])!.write(to: URL(fileURLWithPath: "/tmp/nbicon.png"))
SW
swift /tmp/nbicon.swift
rm -rf /tmp/nb.iconset && mkdir -p /tmp/nb.iconset
for s in 16 32 64 128 256 512 1024; do sips -z $s $s /tmp/nbicon.png --out "/tmp/nb.iconset/icon_${s}x${s}.png" >/dev/null 2>&1; done
cp /tmp/nb.iconset/icon_512x512.png /tmp/nb.iconset/icon_256x256@2x.png
cp /tmp/nb.iconset/icon_1024x1024.png /tmp/nb.iconset/icon_512x512@2x.png
iconutil -c icns /tmp/nb.iconset -o /tmp/nbicon.icns

echo "• assembling bundle…"
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
cp "$R/app/nathanbot" "$APP/Contents/MacOS/nathanbot"
cp /tmp/nbicon.icns "$APP/Contents/Resources/icon.icns"
cat > "$APP/Contents/Info.plist" <<PL
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
 <key>CFBundleName</key><string>nathanbot</string>
 <key>CFBundleDisplayName</key><string>nathanbot</string>
 <key>CFBundleExecutable</key><string>nathanbot</string>
 <key>CFBundleIdentifier</key><string>com.nathanbot.app</string>
 <key>CFBundleIconFile</key><string>icon</string>
 <key>CFBundleVersion</key><string>1.0</string>
 <key>CFBundleShortVersionString</key><string>1.0</string>
 <key>CFBundlePackageType</key><string>APPL</string>
 <key>LSMinimumSystemVersion</key><string>12.0</string>
 <key>NSHighResolutionCapable</key><true/>
 <key>NSMicrophoneUsageDescription</key><string>nathanbot listens for your voice commands so you can talk to it hands-free.</string>
</dict></plist>
PL
# ── sign the bundle so macOS binds the Info.plist + honors mic access ────────
# swiftc emits a linker-signed adhoc Mach-O that leaves Info.plist UNBOUND, so
# macOS never reads NSMicrophoneUsageDescription and never prompts for the mic.
# Re-signing the whole .app seals the bundle and attaches the audio-input
# entitlement, which is what makes getUserMedia in the WKWebView actually work.
cat > /tmp/nb.entitlements <<'ENT'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>com.apple.security.device.audio-input</key><true/>
</dict></plist>
ENT
echo "• signing bundle (adhoc, with mic entitlement)…"
codesign --force --sign - --identifier com.nathanbot.app \
         --entitlements /tmp/nb.entitlements --timestamp=none "$APP"
codesign -dv --entitlements - "$APP" 2>&1 | grep -qi audio-input \
  && echo "  ✓ audio-input entitlement bound" || echo "  ⚠ entitlement not detected"

touch "$APP"   # bump LaunchServices
echo "✓ installed: $APP"
echo "  Quit nathanbot fully and reopen it, then allow the mic when macOS asks."
