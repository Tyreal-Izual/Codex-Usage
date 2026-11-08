import AppKit

let directory = URL(fileURLWithPath: CommandLine.arguments[1])
try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
for size in [16, 32, 128, 256, 512] {
    for scale in [1, 2] {
        let pixels = size * scale
        let image = NSImage(size: NSSize(width: pixels, height: pixels))
        image.lockFocus()
        let context = NSGraphicsContext.current!.cgContext
        context.scaleBy(x: CGFloat(pixels) / 1024, y: CGFloat(pixels) / 1024)
        let background = NSBezierPath(roundedRect: NSRect(x: 80, y: 80, width: 864, height: 864), xRadius: 190, yRadius: 190)
        NSGradient(starting: NSColor(calibratedRed: 0.12, green: 0.29, blue: 0.38, alpha: 1),
                   ending: NSColor(calibratedRed: 0.07, green: 0.12, blue: 0.20, alpha: 1))!.draw(in: background, angle: -90)
        for (index, height) in [230.0, 390.0, 550.0].enumerated() {
            NSColor(calibratedRed: 0.35 + Double(index) * 0.15, green: 0.85, blue: 0.80, alpha: 1).setFill()
            NSBezierPath(roundedRect: NSRect(x: 240 + Double(index) * 190, y: 240, width: 135, height: height), xRadius: 40, yRadius: 40).fill()
        }
        image.unlockFocus()
        let bitmap = NSBitmapImageRep(data: image.tiffRepresentation!)!
        let name = "icon_\(size)x\(size)" + (scale == 2 ? "@2x" : "") + ".png"
        try bitmap.representation(using: .png, properties: [:])!.write(to: directory.appendingPathComponent(name))
    }
}
