import { readdirSync, readFileSync, statSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'

// CONSOLE-001: Vite only inlines import.meta.env.KEY expressions it can
// statically see referenced in source at build time. As long as no source
// file *references* VITE_COGNITIVE_TEST_CREDENTIAL in actual code (comments
// don't count — they never reach the bundle), the credential can never end
// up inlined into the production JS bundle, regardless of what a deploy
// pipeline sets in the build environment. This test walks the whole src/
// tree and fails the build if that invariant is ever violated by a future
// change.

const __dirname = dirname(fileURLToPath(import.meta.url))
const SRC_DIR = __dirname
const FORBIDDEN_PATTERNS = [
  'VITE_COGNITIVE_TEST_CREDENTIAL',
  'testCredential', // legacy field name that used to live on consoleConfig
]

// Strips // line comments and /* */ block comments so documentation that
// *talks about* the forbidden pattern (explaining why it must not be used)
// doesn't trip the check — only actual code references do.
function stripComments(source: string): string {
  return source
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .split('\n')
    .map((line) => line.replace(/\/\/.*/, '')) // no $ anchor: CRLF line endings leave a trailing \r that a `.*$` match can't cross
    .join('\n')
}

function listSourceFiles(dir: string): string[] {
  const entries = readdirSync(dir)
  const files: string[] = []
  for (const entry of entries) {
    const full = join(dir, entry)
    const stat = statSync(full)
    if (stat.isDirectory()) {
      files.push(...listSourceFiles(full))
    } else if (/\.(ts|tsx)$/.test(entry) && !entry.endsWith('.test.ts')) {
      files.push(full)
    }
  }
  return files
}

describe('build safety: no test credential is ever build-time-inlined', () => {
  it('no source file references a build-time credential env var or the old field name (outside comments)', () => {
    const offenders: string[] = []
    for (const file of listSourceFiles(SRC_DIR)) {
      const code = stripComments(readFileSync(file, 'utf-8'))
      for (const pattern of FORBIDDEN_PATTERNS) {
        if (code.includes(pattern)) {
          offenders.push(`${file}: contains "${pattern}"`)
        }
      }
    }
    expect(offenders).toEqual([])
  })

  it('config/session.ts is the only place credential storage is implemented, and it never touches import.meta.env or localStorage', () => {
    const sessionFile = join(SRC_DIR, 'config', 'session.ts')
    const code = stripComments(readFileSync(sessionFile, 'utf-8'))
    expect(code).toContain('sessionStorage')
    expect(code).not.toContain('import.meta.env')
    expect(code).not.toContain('localStorage')
  })
})
