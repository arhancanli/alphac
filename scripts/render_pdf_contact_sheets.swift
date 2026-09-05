#!/usr/bin/env swift

import AppKit
import Foundation
import PDFKit

let arguments = CommandLine.arguments
guard arguments.count == 3 else {
    fputs("usage: render_pdf_contact_sheets.swift PDF_ROOT OUTPUT_DIR\n", stderr)
    exit(2)
}

let fileManager = FileManager.default
let pdfRoot = URL(fileURLWithPath: arguments[1], isDirectory: true)
let outputRoot = URL(fileURLWithPath: arguments[2], isDirectory: true)
try fileManager.createDirectory(at: outputRoot, withIntermediateDirectories: true)

let enumerator = fileManager.enumerator(
    at: pdfRoot,
    includingPropertiesForKeys: [.isRegularFileKey],
    options: [.skipsHiddenFiles]
)
var pages: [(label: String, image: NSImage)] = []

while let url = enumerator?.nextObject() as? URL {
    guard url.lastPathComponent == "paper.pdf", let document = PDFDocument(url: url) else {
        continue
    }
    let bundle = url.deletingLastPathComponent().deletingLastPathComponent().lastPathComponent
    for index in 0..<document.pageCount {
        guard let page = document.page(at: index) else { continue }
        let bounds = page.bounds(for: .mediaBox)
        let scale: CGFloat = 1.35
        let pixelSize = NSSize(width: bounds.width * scale, height: bounds.height * scale)
        let image = NSImage(size: pixelSize)
        image.lockFocus()
        NSColor.white.setFill()
        NSRect(origin: .zero, size: pixelSize).fill()
        guard let context = NSGraphicsContext.current?.cgContext else {
            image.unlockFocus()
            continue
        }
        context.saveGState()
        context.scaleBy(x: scale, y: scale)
        page.draw(with: .mediaBox, to: context)
        context.restoreGState()
        image.unlockFocus()
        pages.append(("\(bundle)  ·  page \(index + 1)/\(document.pageCount)", image))
    }
}

pages.sort { lhs, rhs in lhs.label.localizedStandardCompare(rhs.label) == .orderedAscending }

let columns = 4
let rows = 4
let cellWidth: CGFloat = 340
let cellHeight: CGFloat = 500
let labelHeight: CGFloat = 22
let sheetSize = NSSize(width: CGFloat(columns) * cellWidth, height: CGFloat(rows) * cellHeight)
let labelAttributes: [NSAttributedString.Key: Any] = [
    .font: NSFont.monospacedSystemFont(ofSize: 10, weight: .semibold),
    .foregroundColor: NSColor(calibratedWhite: 0.16, alpha: 1),
]

for sheetIndex in 0..<Int(ceil(Double(pages.count) / Double(columns * rows))) {
    let image = NSImage(size: sheetSize)
    image.lockFocus()
    NSColor(calibratedWhite: 0.82, alpha: 1).setFill()
    NSRect(origin: .zero, size: sheetSize).fill()

    for slot in 0..<(columns * rows) {
        let pageIndex = sheetIndex * columns * rows + slot
        guard pageIndex < pages.count else { break }
        let column = slot % columns
        let row = slot / columns
        let cellX = CGFloat(column) * cellWidth
        let cellY = sheetSize.height - CGFloat(row + 1) * cellHeight
        let record = pages[pageIndex]
        record.label.draw(
            at: NSPoint(x: cellX + 8, y: cellY + cellHeight - 17),
            withAttributes: labelAttributes
        )
        let available = NSSize(width: cellWidth - 16, height: cellHeight - labelHeight - 12)
        let ratio = min(available.width / record.image.size.width,
                        available.height / record.image.size.height)
        let drawSize = NSSize(width: record.image.size.width * ratio,
                              height: record.image.size.height * ratio)
        let drawRect = NSRect(
            x: cellX + (cellWidth - drawSize.width) / 2,
            y: cellY + 7,
            width: drawSize.width,
            height: drawSize.height
        )
        record.image.draw(in: drawRect)
    }

    image.unlockFocus()
    guard let tiff = image.tiffRepresentation,
          let bitmap = NSBitmapImageRep(data: tiff),
          let png = bitmap.representation(using: .png, properties: [:]) else {
        fputs("failed to encode sheet \(sheetIndex + 1)\n", stderr)
        exit(1)
    }
    let output = outputRoot.appendingPathComponent(
        String(format: "all-pages-%02d.png", sheetIndex + 1)
    )
    try png.write(to: output)
}

print("rendered \(pages.count) pages into \(Int(ceil(Double(pages.count) / 16.0))) sheets")
