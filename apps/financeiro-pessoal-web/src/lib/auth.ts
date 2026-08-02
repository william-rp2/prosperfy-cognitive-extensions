const AUTH_STORAGE_KEY = 'prosperfy.financeiro.auth.v1'
const SESSION_STORAGE_KEY = 'prosperfy.financeiro.session.v1'
const PBKDF2_ITERATIONS = 250_000

interface StoredAuthRecord {
  username: string
  salt: string
  iv: string
  ciphertext: string
  createdAt: string
}

export interface AuthSession {
  username: string
  loginAt: string
}

const encoder = new TextEncoder()
const decoder = new TextDecoder()

function bytesToBase64(bytes: Uint8Array): string {
  let binary = ''
  bytes.forEach(byte => {
    binary += String.fromCharCode(byte)
  })
  return btoa(binary)
}

function base64ToBytes(value: string): Uint8Array {
  const binary = atob(value)
  const bytes = new Uint8Array(binary.length)
  for (let index = 0; index < binary.length; index += 1) {
    bytes[index] = binary.charCodeAt(index)
  }
  return bytes
}

function toArrayBuffer(bytes: Uint8Array): ArrayBuffer {
  return bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength) as ArrayBuffer
}

async function deriveKey(password: string, salt: Uint8Array): Promise<CryptoKey> {
  const keyMaterial = await crypto.subtle.importKey(
    'raw',
    encoder.encode(password),
    'PBKDF2',
    false,
    ['deriveKey'],
  )

  return crypto.subtle.deriveKey(
    {
      name: 'PBKDF2',
      salt: toArrayBuffer(salt),
      iterations: PBKDF2_ITERATIONS,
      hash: 'SHA-256',
    },
    keyMaterial,
    { name: 'AES-GCM', length: 256 },
    false,
    ['encrypt', 'decrypt'],
  )
}

async function encryptJson(payload: unknown, password: string) {
  const salt = crypto.getRandomValues(new Uint8Array(16))
  const iv = crypto.getRandomValues(new Uint8Array(12))
  const key = await deriveKey(password, salt)
  const ciphertext = await crypto.subtle.encrypt(
    { name: 'AES-GCM', iv: toArrayBuffer(iv) },
    key,
    encoder.encode(JSON.stringify(payload)),
  )

  return {
    salt: bytesToBase64(salt),
    iv: bytesToBase64(iv),
    ciphertext: bytesToBase64(new Uint8Array(ciphertext)),
  }
}

async function decryptJson<T>(record: StoredAuthRecord, password: string): Promise<T> {
  const salt = base64ToBytes(record.salt)
  const iv = base64ToBytes(record.iv)
  const key = await deriveKey(password, salt)
  const plaintext = await crypto.subtle.decrypt(
    { name: 'AES-GCM', iv: toArrayBuffer(iv) },
    key,
    toArrayBuffer(base64ToBytes(record.ciphertext)),
  )

  return JSON.parse(decoder.decode(plaintext)) as T
}

export function getStoredAuthRecord(): StoredAuthRecord | null {
  const raw = localStorage.getItem(AUTH_STORAGE_KEY)
  if (!raw) return null

  try {
    return JSON.parse(raw) as StoredAuthRecord
  } catch {
    localStorage.removeItem(AUTH_STORAGE_KEY)
    return null
  }
}

export function getCurrentSession(): AuthSession | null {
  const raw = sessionStorage.getItem(SESSION_STORAGE_KEY)
  if (!raw) return null

  try {
    return JSON.parse(raw) as AuthSession
  } catch {
    sessionStorage.removeItem(SESSION_STORAGE_KEY)
    return null
  }
}

export async function authenticate(username: string, password: string): Promise<AuthSession> {
  const normalizedUsername = username.trim().toLowerCase()
  if (!normalizedUsername || !password) {
    throw new Error('Informe usuário e senha.')
  }

  const existing = getStoredAuthRecord()
  if (!existing) {
    const encrypted = await encryptJson(
      {
        marker: 'prosperfy-financeiro-local-user',
        username: normalizedUsername,
        createdAt: new Date().toISOString(),
      },
      password,
    )
    const record: StoredAuthRecord = {
      username: normalizedUsername,
      createdAt: new Date().toISOString(),
      ...encrypted,
    }
    localStorage.setItem(AUTH_STORAGE_KEY, JSON.stringify(record))
  } else {
    if (existing.username !== normalizedUsername) {
      throw new Error('Usuário não encontrado neste navegador.')
    }

    try {
      const payload = await decryptJson<{ marker: string; username: string }>(existing, password)
      if (payload.marker !== 'prosperfy-financeiro-local-user') {
        throw new Error('Registro local inválido.')
      }
    } catch {
      throw new Error('Senha inválida ou registro local corrompido.')
    }
  }

  const session: AuthSession = {
    username: normalizedUsername,
    loginAt: new Date().toISOString(),
  }
  sessionStorage.setItem(SESSION_STORAGE_KEY, JSON.stringify(session))
  return session
}

export function logout() {
  sessionStorage.removeItem(SESSION_STORAGE_KEY)
}

export function resetLocalCredentials() {
  localStorage.removeItem(AUTH_STORAGE_KEY)
  sessionStorage.removeItem(SESSION_STORAGE_KEY)
}
