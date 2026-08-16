import { loadConfig } from './config.js'
import { createApp } from './server.js'

const config = loadConfig()
const app = createApp({ config })

// Without this, killing/restarting the process (Ctrl+C, tsx watch on file save, tsx
// watch's own SIGUSR2 restart signal) skips Fastify's onClose hooks entirely, so the
// better-sqlite3 handle never gets closed — that leaves a native Statement object alive
// when V8 tears down the isolate, which crashes the process with a native assertion
// failure on Windows ("RemoveEnvironmentCleanupHook ... env != nullptr").
let shuttingDown = false
async function shutdown(signal: NodeJS.Signals) {
  if (shuttingDown) return
  shuttingDown = true
  app.log.info({ signal }, 'shutting down')
  await app.close()
  process.exit(0)
}
process.on('SIGINT', () => void shutdown('SIGINT'))
process.on('SIGTERM', () => void shutdown('SIGTERM'))
process.on('SIGUSR2', () => void shutdown('SIGUSR2')) // tsx/nodemon watch-mode restart

try {
  await app.listen({ host: config.HOST, port: config.PORT })
} catch (error) {
  app.log.error(error)
  process.exit(1)
}
