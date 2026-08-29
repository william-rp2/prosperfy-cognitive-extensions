import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import { CategoriesRepository } from './categoriesRepository.js'
import { openFinanceDb, type FinanceDb } from './db.js'

let db: FinanceDb
let repo: CategoriesRepository

beforeEach(() => {
  db = openFinanceDb(':memory:')
  repo = new CategoriesRepository(db)
})

afterEach(() => {
  db.close()
})

describe('CategoriesRepository', () => {
  it('comes pre-seeded with a stable set of categories (migration 002)', () => {
    const all = repo.listAll()
    expect(all.length).toBeGreaterThanOrEqual(12)
    expect(all.some(category => category.name === 'Alimentação')).toBe(true)
  })

  it('findByName resolves an exact case-insensitive match', () => {
    const matches = repo.findByName('alimentação')
    expect(matches).toHaveLength(1)
    expect(matches[0].id).toBe('cat_alimentacao')
  })

  it('findByName returns every substring match when there is no exact hit (caller must treat 2+ as ambiguous)', () => {
    const created1 = repo.create('Assinatura Streaming', 'expense')
    const created2 = repo.create('Assinatura Academia', 'expense')
    const matches = repo.findByName('assinatura')
    const ids = matches.map(category => category.id)
    expect(ids).toEqual(expect.arrayContaining([created1.id, created2.id]))
    expect(matches.length).toBeGreaterThanOrEqual(2)
  })

  it('findByName returns empty array for no match', () => {
    expect(repo.findByName('categoria-que-nao-existe-xyz')).toEqual([])
  })

  it('create persists a new category with a stable cat_ prefixed id', () => {
    const created = repo.create('Pet', 'expense')
    expect(created.id).toMatch(/^cat_/)
    expect(repo.getById(created.id)?.name).toBe('Pet')
  })
})
