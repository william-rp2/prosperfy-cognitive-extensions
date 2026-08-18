import { beforeEach, describe, expect, it } from 'vitest'
import { clearSessionCredential, getSessionCredential, setSessionCredential } from './session'

const STORAGE_KEY = 'cognitive-console.test-credential'

describe('session credential storage (CONSOLE-001)', () => {
  beforeEach(() => {
    window.sessionStorage.clear()
  })

  it('returns empty string when nothing is stored', () => {
    expect(getSessionCredential()).toBe('')
  })

  it('stores and retrieves a trimmed credential from sessionStorage only', () => {
    setSessionCredential('  my-bearer-token  ')
    expect(getSessionCredential()).toBe('my-bearer-token')
    expect(window.sessionStorage.getItem(STORAGE_KEY)).toBe('my-bearer-token')
  })

  it('never touches localStorage', () => {
    setSessionCredential('my-bearer-token')
    expect(window.localStorage.getItem(STORAGE_KEY)).toBeNull()
  })

  it('clearing with an empty string removes the stored value', () => {
    setSessionCredential('token')
    setSessionCredential('')
    expect(getSessionCredential()).toBe('')
    expect(window.sessionStorage.getItem(STORAGE_KEY)).toBeNull()
  })

  it('clearSessionCredential removes the stored value', () => {
    setSessionCredential('token')
    clearSessionCredential()
    expect(getSessionCredential()).toBe('')
  })
})
