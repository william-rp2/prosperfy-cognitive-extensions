#!/usr/bin/env node
/**
 * F2A.1 — Historical transaction reprocess CLI.
 *
 * Re-runs persisted Pluggy transactions through the official classification pipeline
 * (normalizer + ClassificationService + idempotent clarifications).
 *
 * Does NOT touch source transaction rows, sync cursors, or Pluggy API.
 */

import { loadConfig } from '../config.js'
import { AccountsRepository } from '../finance/accountsRepository.js'
import { CategoriesRepository } from '../finance/categoriesRepository.js'
import { CategoryOverridesRepository } from '../finance/categoryOverridesRepository.js'
import { ClarificationsRepository } from '../finance/clarificationsRepository.js'
import { ClassificationService } from '../finance/classificationService.js'
import { openFinanceDb } from '../finance/db.js'
import { EnrichmentRepository } from '../finance/enrichmentRepository.js'
import { TransactionReprocessService } from '../finance/transactionReprocessService.js'
import { TransactionsRepository } from '../finance/transactionsRepository.js'

function printUsage() {
  console.error(`Usage:
  npm run finance:reprocess -- --all [--dry-run]
  npm run finance:reprocess -- --transaction-id <pluggy_tx_id> [--dry-run]

Options:
  --all                 Reprocess every persisted transaction
  --transaction-id ID   Reprocess a single transaction
  --dry-run             Compute metrics only; no writes

Safety:
  Blocked when PLUGGY_ENV=production unless FINANCE_REPROCESS_ALLOW=1
  See docs/finance-reprocess.md`)
}

function parseArgs(argv: string[]) {
  const dryRun = argv.includes('--dry-run')
  const all = argv.includes('--all')
  const txIdx = argv.indexOf('--transaction-id')
  const pluggyTransactionId = txIdx >= 0 ? argv[txIdx + 1] : undefined

  if (!all && !pluggyTransactionId) {
    printUsage()
    process.exit(1)
  }
  if (all && pluggyTransactionId) {
    console.error('Use --all OR --transaction-id, not both.')
    process.exit(1)
  }

  return { dryRun, all, pluggyTransactionId }
}

async function main() {
  const { dryRun, all, pluggyTransactionId } = parseArgs(process.argv.slice(2))
  const config = loadConfig()

  if (config.PLUGGY_ENV === 'production' && process.env.FINANCE_REPROCESS_ALLOW !== '1') {
    console.error(
      'Refusing to run: PLUGGY_ENV=production. Set FINANCE_REPROCESS_ALLOW=1 only with explicit owner authorization.',
    )
    process.exit(1)
  }

  const db = openFinanceDb(config.FINANCE_DB_PATH)
  try {
    const transactions = new TransactionsRepository(db)
    const accounts = new AccountsRepository(db)
    const enrichment = new EnrichmentRepository(db)
    const clarifications = new ClarificationsRepository(db)
    const classification = new ClassificationService(
      enrichment,
      clarifications,
      new CategoriesRepository(db),
      new CategoryOverridesRepository(db),
      accounts,
    )

    const service = new TransactionReprocessService(
      db,
      transactions,
      accounts,
      enrichment,
      clarifications,
      classification,
    )

    const metrics = service.run({
      dryRun,
      pluggyTransactionId: all ? undefined : pluggyTransactionId,
    })

    console.log(JSON.stringify(metrics, null, 2))
    process.exit(metrics.failed > 0 ? 2 : 0)
  } finally {
    db.close()
  }
}

main().catch(error => {
  console.error(error instanceof Error ? error.message : error)
  process.exit(1)
})
