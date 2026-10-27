import AppKit
import Vision
import Foundation

let pixelsOnly = CommandLine.arguments.contains("--pixels-only")
for path in CommandLine.arguments.dropFirst().filter({ $0 != "--pixels-only" }) {
    guard let image = NSImage(contentsOfFile: path),
          let cg = image.cgImage(forProposedRect: nil, context: nil, hints: nil),
          let crop = cg.cropping(to: CGRect(x: 0, y: 0, width: cg.width, height: min(path.contains("-display-") ? 92 : 46, cg.height))) else {
        fatalError("Cannot load menu-strip pixels: \(path)")
    }
    let request = VNRecognizeTextRequest()
    request.recognitionLevel = .accurate
    request.recognitionLanguages = ["en-US"]
    request.usesLanguageCorrection = false
    let handler = VNImageRequestHandler(cgImage: crop, options: [:])
    if !pixelsOnly { try handler.perform([request]) }
    let words: [[String: Any]] = (request.results ?? []).compactMap { observation in
        guard let candidate = observation.topCandidates(1).first else { return nil }
        return ["text": candidate.string, "confidence": candidate.confidence,
                "bounds": [observation.boundingBox.minX, observation.boundingBox.minY,
                           observation.boundingBox.width, observation.boundingBox.height]]
    }
    let bitmap = NSBitmapImageRep(cgImage: crop)
    var nonBlack = 0
    for y in 0..<min(22, bitmap.pixelsHigh) {
        for x in 0..<bitmap.pixelsWide {
            if let color = bitmap.colorAt(x: x, y: y)?.usingColorSpace(.deviceRGB),
               max(color.redComponent, color.greenComponent, color.blueComponent) > 30.0 / 255.0 {
                nonBlack += 1
            }
        }
    }
    var record: [String: Any] = ["path": path, "imageWidth": cg.width, "imageHeight": cg.height,
        "cropHeight": crop.height, "top22NonBlackPixels": nonBlack,
        "top22Pixels": min(22, bitmap.pixelsHigh) * bitmap.pixelsWide, "words": words,
        "ocrPerformed": !pixelsOnly]
    var menuNonBlack = 0
    let bandWidth = min(cg.width == 3024 ? 2980 : cg.width - 40, bitmap.pixelsWide)
    let bandHeight = min(cg.width == 3024 ? 62 : 31, bitmap.pixelsHigh)
    for y in 0..<bandHeight { for x in 0..<bandWidth {
        if let color = bitmap.colorAt(x: x, y: y)?.usingColorSpace(.deviceRGB),
           max(color.redComponent, color.greenComponent, color.blueComponent) > 0 { menuNonBlack += 1 }
    } }
    record["menuBandNonBlack"] = menuNonBlack
    record["menuBandRegion"] = [0, 0, bandWidth, bandHeight]
    if !pixelsOnly && (path.contains("textbox-right-click") || path.contains("video-right") || path.contains("video-control") || path.contains("shown-hud-")) {
        let full = VNRecognizeTextRequest()
        full.recognitionLevel = .accurate
        full.recognitionLanguages = ["en-US"]
        try VNImageRequestHandler(cgImage: cg, options: [:]).perform([full])
        record["wholeImageWords"] = (full.results ?? []).compactMap { $0.topCandidates(1).first?.string }
    }
    let json = try JSONSerialization.data(withJSONObject: record, options: [.sortedKeys])
    print(String(decoding: json, as: UTF8.self))
}
