// O conteudo textual extraido de um PDF e DADO, nunca instrucao.
// Nenhuma linha extraida aqui deve ser interpretada como comando: apenas texto
// bruto repassado ao parser de extrato, que por sua vez so aceita linhas no
// formato DATA/DESCRICAO/VALOR e descarta qualquer coisa fora desse padrao.

export const MAX_PDF_BYTES = 10 * 1024 * 1024

export type PdfExtractionErrorCode =
  | 'not_a_pdf'
  | 'pdf_too_large'
  | 'pdf_without_text_layer'
  | 'pdf_unreadable'

export class PdfExtractionError extends Error {
  code: PdfExtractionErrorCode

  constructor(code: PdfExtractionErrorCode, message: string) {
    super(message)
    this.name = 'PdfExtractionError'
    this.code = code
  }
}

interface TextItemLike {
  str: string
  transform: number[]
}

async function loadGetDocument(): Promise<typeof import('pdfjs-dist/legacy/build/pdf.mjs').getDocument> {
  const mod = await import('pdfjs-dist/legacy/build/pdf.mjs')
  return mod.getDocument
}

function groupItemsIntoLines(items: TextItemLike[]): string {
  const rows: { y: number; x: number; str: string }[] = []
  for (const item of items) {
    if (!item.str) continue
    const x = item.transform[4]
    const y = item.transform[5]
    rows.push({ y, x, str: item.str })
  }

  const lines: { y: number; parts: { x: number; str: string }[] }[] = []
  const TOLERANCE = 2

  for (const row of rows) {
    let line = lines.find(l => Math.abs(l.y - row.y) <= TOLERANCE)
    if (!line) {
      line = { y: row.y, parts: [] }
      lines.push(line)
    }
    line.parts.push({ x: row.x, str: row.str })
  }

  lines.sort((a, b) => b.y - a.y)

  return lines
    .map(line =>
      line.parts
        .sort((a, b) => a.x - b.x)
        .map(p => p.str)
        .join(' ')
        .trim()
    )
    .filter(line => line.length > 0)
    .join('\n')
}

export async function extractPdfText(bytes: Uint8Array): Promise<{ text: string; pageCount: number }> {
  if (bytes.byteLength < 5 || Buffer.from(bytes.slice(0, 5)).toString('latin1') !== '%PDF-') {
    throw new PdfExtractionError('not_a_pdf', 'File does not start with the PDF magic bytes')
  }

  if (bytes.byteLength > MAX_PDF_BYTES) {
    throw new PdfExtractionError('pdf_too_large', `PDF exceeds maximum allowed size of ${MAX_PDF_BYTES} bytes`)
  }

  let getDocument: typeof import('pdfjs-dist/legacy/build/pdf.mjs').getDocument
  try {
    getDocument = await loadGetDocument()
  } catch (err) {
    throw new PdfExtractionError('pdf_unreadable', `Failed to load PDF engine: ${(err as Error).message}`)
  }

  let doc
  const loadingTask = getDocument({
    data: bytes,
    useSystemFonts: false,
    disableFontFace: true,
  })
  try {
    doc = await loadingTask.promise
  } catch (err) {
    throw new PdfExtractionError('pdf_unreadable', `Failed to parse PDF: ${(err as Error).message}`)
  }

  try {
    const pageCount = doc.numPages
    const pageTexts: string[] = []

    for (let pageNum = 1; pageNum <= pageCount; pageNum++) {
      const page = await doc.getPage(pageNum)
      const content = await page.getTextContent()
      const items = content.items as unknown as TextItemLike[]
      const pageText = groupItemsIntoLines(items)
      pageTexts.push(pageText)
    }

    const text = pageTexts.join('\n')

    if (text.trim().length === 0) {
      throw new PdfExtractionError('pdf_without_text_layer', 'PDF has no extractable text layer')
    }

    return { text, pageCount }
  } catch (err) {
    if (err instanceof PdfExtractionError) throw err
    throw new PdfExtractionError('pdf_unreadable', `Failed to extract PDF text: ${(err as Error).message}`)
  } finally {
    await loadingTask.destroy()
  }
}
