// Draws the Dock app's icon (a page under a magnifying glass on a rounded square) as a
// 1024 px PNG. Usage: make_icon <out.png>. Run by build_app.sh, which turns it into the .icns.

import AppKit

let size = 1024.0
guard CommandLine.arguments.count == 2,
    let rep = NSBitmapImageRep(
        bitmapDataPlanes: nil, pixelsWide: Int(size), pixelsHigh: Int(size), bitsPerSample: 8,
        samplesPerPixel: 4, hasAlpha: true, isPlanar: false, colorSpaceName: .deviceRGB,
        bytesPerRow: 0, bitsPerPixel: 0)
else {
    FileHandle.standardError.write("usage: make_icon <out.png>\n".data(using: .utf8)!)
    exit(2)
}

func rgb(_ r: Double, _ g: Double, _ b: Double) -> NSColor {
    NSColor(srgbRed: r / 255, green: g / 255, blue: b / 255, alpha: 1)
}
// Coordinates are measured from the top left, as in a drawing; AppKit's y axis points up.
func at(_ x: Double, _ y: Double) -> NSPoint { NSPoint(x: x, y: size - y) }
func disc(_ x: Double, _ y: Double, _ r: Double, _ color: NSColor) {
    color.setFill()
    NSBezierPath(ovalIn: NSRect(x: x - r, y: size - y - r, width: 2 * r, height: 2 * r)).fill()
}
func stroke(_ from: NSPoint, _ to: NSPoint, width: Double, _ color: NSColor) {
    let line = NSBezierPath()
    line.move(to: from)
    line.line(to: to)
    line.lineWidth = width
    line.lineCapStyle = .round
    color.setStroke()
    line.stroke()
}

let paper = rgb(253, 248, 244)
let ink = rgb(196, 101, 64)
let deep = rgb(153, 64, 34)

NSGraphicsContext.current = NSGraphicsContext(bitmapImageRep: rep)

// macOS icon grid: an 824 px rounded square centred on the 1024 px canvas, with a soft shadow.
let tile = NSRect(x: 100, y: 100, width: 824, height: 824)
let shape = NSBezierPath(roundedRect: tile, xRadius: 185, yRadius: 185)
NSGraphicsContext.saveGraphicsState()
let shadow = NSShadow()
shadow.shadowColor = NSColor(white: 0, alpha: 0.28)
shadow.shadowOffset = NSSize(width: 0, height: -10)
shadow.shadowBlurRadius = 24
shadow.set()
rgb(158, 69, 38).setFill()
shape.fill()
NSGraphicsContext.restoreGraphicsState()
NSGradient(starting: rgb(193, 99, 61), ending: rgb(158, 69, 38))!.draw(in: shape, angle: -90)

// The page and its lines of text.
paper.setFill()
NSBezierPath(
    roundedRect: NSRect(x: 307, y: size - 717, width: 328, height: 472), xRadius: 28, yRadius: 28
).fill()
for (y, end) in [(338.0, 573.0), (410.0, 532.0), (482.0, 573.0), (553.0, 470.0)] {
    stroke(at(369, y), at(end, y), width: 22, ink)
}

// The magnifying glass: the handle, then over it a dark rim that cuts into the page, a
// light ring and a dark lens.
stroke(at(700, 678), at(802, 782), width: 46, paper)
disc(635, 613, 143, deep)
disc(635, 613, 123, paper)
disc(635, 613, 82, deep)

NSGraphicsContext.current = nil

let url = URL(fileURLWithPath: CommandLine.arguments[1])
try rep.representation(using: .png, properties: [:])!.write(to: url)
