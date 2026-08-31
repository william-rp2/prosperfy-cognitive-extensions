// Test-only helpers that build real PDF byte streams (not strings pretending to be PDFs), so the
// extractor is exercised against the same binary structure it will see in production.

function escapePdfText(text: string): string {
  return text.replace(/\\/g, '\\\\').replace(/\(/g, '\\(').replace(/\)/g, '\\)')
}

function buildPdf(objects: string[], catalogObjNum: number): Uint8Array {
  const header = '%PDF-1.4\n'
  const chunks: string[] = [header]
  const offsets: number[] = []
  let cursor = Buffer.byteLength(header, 'latin1')

  for (const obj of objects) {
    offsets.push(cursor)
    chunks.push(obj)
    cursor += Buffer.byteLength(obj, 'latin1')
  }

  const xrefOffset = cursor
  const count = objects.length + 1
  let xref = `xref\n0 ${count}\n0000000000 65535 f \n`
  for (const offset of offsets) {
    xref += `${String(offset).padStart(10, '0')} 00000 n \n`
  }
  chunks.push(xref)

  const trailer = `trailer\n<< /Size ${count} /Root ${catalogObjNum} 0 R >>\nstartxref\n${xrefOffset}\n%%EOF`
  chunks.push(trailer)

  return new Uint8Array(Buffer.from(chunks.join(''), 'latin1'))
}

/**
 * Build a real, minimal single-page PDF whose text layer renders the given lines, one per row,
 * using the standard Helvetica font (Type1, no embedded font file needed).
 */
export function makeStatementPdf(lines: readonly string[]): Uint8Array {
  const fontObjNum = 5
  let content = ''
  let y = 750
  for (const line of lines) {
    content += `BT /F1 10 Tf 40 ${y} Td (${escapePdfText(line)}) Tj ET\n`
    y -= 16
  }
  const contentBytes = Buffer.byteLength(content, 'latin1')

  const objects = [
    `1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n`,
    `2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n`,
    `3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 ${fontObjNum} 0 R >> >> >>\nendobj\n`,
    `4 0 obj\n<< /Length ${contentBytes} >>\nstream\n${content}endstream\nendobj\n`,
    `5 0 obj\n<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>\nendobj\n`,
  ]

  return buildPdf(objects, 1)
}

/** A minimal valid PDF with a page but no text-drawing operators at all. */
export function makeTextlessPdf(): Uint8Array {
  const content = ''
  const objects = [
    `1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n`,
    `2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n`,
    `3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << >> >> >>\nendobj\n`,
    `4 0 obj\n<< /Length ${Buffer.byteLength(content, 'latin1')} >>\nstream\n${content}endstream\nendobj\n`,
  ]

  return buildPdf(objects, 1)
}

/** Bytes for a small valid PNG — used to prove non-PDF uploads are rejected by magic-byte sniffing. */
export function makeNonPdfBytes(): Uint8Array {
  // Minimal PNG signature + IHDR/IEND chunks (1x1 transparent pixel).
  const base64 =
    'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII='
  return new Uint8Array(Buffer.from(base64, 'base64'))
}
