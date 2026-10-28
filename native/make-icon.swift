// Renders the SPT Studio icons from the SVG masters in spt/ui/brand:
//   swift native/make-icon.swift <output folder>      (run from the software folder)
// Writes SPT.iconset/ (for iconutil) plus the web icons. Tiny sizes use the simplified
// small mark (bigger eyes, no cheeks) so the ghost still reads at 16 px.
import AppKit

let brand = URL(fileURLWithPath: FileManager.default.currentDirectoryPath).appendingPathComponent("spt/ui/brand")
func svg(_ name: String) -> NSImage {
    guard let image = NSImage(contentsOf: brand.appendingPathComponent(name)) else { fatalError("cannot read \(name)") }
    return image
}
let night = NSColor(srgbRed: 0x1e / 255, green: 0x1b / 255, blue: 0x2e / 255, alpha: 1)

/// Draws into a square bitmap. `inset` leaves the macOS icon margin around the tile.
func png(_ size: Int, _ draw: (CGRect) -> Void) -> Data {
    let rep = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: size, pixelsHigh: size, bitsPerSample: 8,
                               samplesPerPixel: 4, hasAlpha: true, isPlanar: false, colorSpaceName: .deviceRGB,
                               bytesPerRow: 0, bitsPerPixel: 0)!
    NSGraphicsContext.saveGraphicsState()
    NSGraphicsContext.current = NSGraphicsContext(bitmapImageRep: rep)
    NSGraphicsContext.current?.imageInterpolation = .high
    draw(CGRect(x: 0, y: 0, width: size, height: size))
    NSGraphicsContext.restoreGraphicsState()
    return rep.representation(using: .png, properties: [:])!
}
func appIcon(_ size: Int) -> Data {
    png(size) { full in
        // macOS grid: the rounded tile is ~80% of the canvas
        svg(size <= 32 ? "spt-app-icon-small.svg" : "spt-app-icon.svg").draw(in: full.insetBy(dx: full.width * 0.098, dy: full.width * 0.098))
    }
}

let output = URL(fileURLWithPath: CommandLine.arguments.count > 1 ? CommandLine.arguments[1] : ".")
let iconset = output.appendingPathComponent("SPT.iconset")
try FileManager.default.createDirectory(at: iconset, withIntermediateDirectories: true)
for base in [16, 32, 128, 256, 512] {
    try appIcon(base).write(to: iconset.appendingPathComponent("icon_\(base)x\(base).png"))
    try appIcon(base * 2).write(to: iconset.appendingPathComponent("icon_\(base)x\(base)@2x.png"))
}
// Web: browser tab icon (small mark) and the home-screen icon (full bleed, the system rounds it).
try png(32) { svg("spt-symbol-small.svg").draw(in: $0) }.write(to: output.appendingPathComponent("favicon-32.png"))
try png(180) { full in
    night.setFill(); full.fill()
    svg("spt-symbol.svg").draw(in: full.insetBy(dx: full.width * 0.14, dy: full.width * 0.14))
}.write(to: output.appendingPathComponent("apple-touch-icon.png"))
print("ok")
