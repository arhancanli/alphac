#!/usr/bin/env swift

import AppKit
import Foundation
import PDFKit

let arguments = CommandLine.arguments
guard arguments.count == 4 else {
    fputs("usage: render_selected_pdf_pages.swift PDF OUTPUT_DIR PAGE_LIST\n", stderr)
    exit(2)
}

let pdf = URL(fileURLWithPath: arguments[1])
let output = URL(fileURLWithPath: arguments[2], isDirectory: true)
let requestedPages = arguments[3].split(separator: ",").compactMap { Int($0) }
guard !requestedPages.isEmpty, let document = PDFDocument(url: pdf) else {
    fputs("could not open PDF or parse page list\n", stderr)
    exit(2)
}

try FileManager.default.createDirectory(at: output, withIntermediateDirectories: true)

for pageNumber in requestedPages {
    let index = pageNumber - 1
    guard index >= 0, index < document.pageCount, let page = document.page(at: index) else {
        fputs("page \(pageNumber) is outside 1...\(document.pageCount)\n", stderr)
        exit(2)
    }
    let bounds = page.bounds(for: .mediaBox)
    let scale: CGFloat = 2.5
    let size = NSSize(width: bounds.width * scale, height: bounds.height * scale)
    let image = NSImage(size: size)
    image.lockFocus()
    NSColor.white.setFill()
    NSRect(origin: .zero, size: size).fill()
    guard let context = NSGraphicsContext.current?.cgContext else {
        image.unlockFocus()
        fputs("could not create graphics context\n", stderr)
        exit(1)
    }
    context.saveGState()
    context.scaleBy(x: scale, y: scale)
    page.draw(with: .mediaBox, to: context)
    context.restoreGState()
    image.unlockFocus()

    guard let tiff = image.tiffRepresentation,
          let bitmap = NSBitmapImageRep(data: tiff),
          let png = bitmap.representation(using: .png, properties: [:]) else {
        fputs("could not encode page \(pageNumber)\n", stderr)
        exit(1)
    }
    let path = output.appendingPathComponent(String(format: "page-%03d.png", pageNumber))
    try png.write(to: path)
}

print("rendered \(requestedPages.count) selected pages")
