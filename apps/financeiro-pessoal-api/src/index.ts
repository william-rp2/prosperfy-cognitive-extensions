import { loadConfig } from './config.js'
import { createApp } from './server.js'

const config = loadConfig()
const app = createApp({ config })

try {
  await app.listen({ host: config.HOST, port: config.PORT })
} catch (error) {
  app.log.error(error)
  process.exit(1)
}
