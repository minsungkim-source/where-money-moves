// 글자를 투명 PNG로 렌더링한다. PIL에 libraqm이 없어 태국어 모음·성조 기호가 점선 원으로 깨지기 때문에,
// 글자 모양 잡기는 macOS CoreText에 맡기고 PIL은 합성만 한다.
//
//   swift tools/text_png.swift specs.json
//   specs.json: [{"text": "...", "size": 34, "bold": false, "color": "e8f2ee", "out": "/path/a.png"}, ...]
import AppKit

let args = CommandLine.arguments
guard args.count > 1, let data = FileManager.default.contents(atPath: args[1]),
      let specs = try? JSONSerialization.jsonObject(with: data) as? [[String: Any]] else {
    FileHandle.standardError.write("usage: text_png.swift specs.json\n".data(using: .utf8)!)
    exit(1)
}

func color(_ hex: String) -> NSColor {
    let v = UInt32(hex, radix: 16) ?? 0xffffff
    return NSColor(srgbRed: CGFloat((v >> 16) & 0xff) / 255, green: CGFloat((v >> 8) & 0xff) / 255,
                   blue: CGFloat(v & 0xff) / 255, alpha: 1)
}

for spec in specs {
    let text = spec["text"] as? String ?? ""
    let size = CGFloat(spec["size"] as? Double ?? 32)
    let bold = spec["bold"] as? Bool ?? false
    let name = bold ? "Thonburi-Bold" : "Thonburi"
    let font = NSFont(name: name, size: size) ?? NSFont.systemFont(ofSize: size, weight: bold ? .bold : .regular)
    let attr = NSAttributedString(string: text, attributes: [.font: font, .foregroundColor: color(spec["color"] as? String ?? "ffffff")])
    let bounds = attr.boundingRect(with: NSSize(width: 4000, height: 1000), options: [.usesLineFragmentOrigin, .usesFontLeading])
    let w = Int(ceil(bounds.width)) + 4, h = Int(ceil(bounds.height)) + 4
    guard let rep = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: w, pixelsHigh: h, bitsPerSample: 8,
                                     samplesPerPixel: 4, hasAlpha: true, isPlanar: false,
                                     colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 0) else { exit(2) }
    NSGraphicsContext.saveGraphicsState()
    NSGraphicsContext.current = NSGraphicsContext(bitmapImageRep: rep)
    attr.draw(with: NSRect(x: 2, y: 2, width: bounds.width, height: bounds.height), options: [.usesLineFragmentOrigin, .usesFontLeading])
    NSGraphicsContext.restoreGraphicsState()
    let out = spec["out"] as? String ?? "out.png"
    try? rep.representation(using: .png, properties: [:])?.write(to: URL(fileURLWithPath: out))
}
