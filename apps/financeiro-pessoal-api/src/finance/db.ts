import { readdirSync, readFileSync, mkdirSync } from 'node:fs'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

import Database from 'better-sqlite3'

const migrationsDir = join(dirname(fileURLToPath(import.meta.url)), 'migrations')

export type FinanceDb = Database.Database

export function openFinanceDb(path: string): FinanceDb {
  const resolvedPath = path === ':memory:' ? path : resolve(path)
  if (resolvedPath !== ':memory:') mkdirSync(dirname(resolvedPath), { recursive: true })

  const db = new Database(resolvedPath)
  db.pragma('journal_mode = WAL')
  db.pragma('foreign_keys = ON')
  runMigrations(db)
  return db
}

function runMigrations(db: FinanceDb) {
  db.exec(`
    CREATE TABLE IF NOT EXISTS schema_migrations (
      name       TEXT PRIMARY KEY,
      applied_at TEXT NOT NULL
    )
  `)

  const applied = new Set(db.prepare('SELECT name FROM schema_migrations').all().map((row: any) => row.name))
  const files = readdirSync(migrationsDir).filter(name => name.endsWith('.sql')).sort()

  for (const file of files) {
    if (applied.has(file)) continue
    const sql = readFileSync(join(migrationsDir, file), 'utf8')
    const applyMigration = db.transaction(() => {
      db.exec(sql)
      db.prepare('INSERT INTO schema_migrations (name, applied_at) VALUES (?, ?)').run(file, new Date().toISOString())
    })
    applyMigration()
  }
}
