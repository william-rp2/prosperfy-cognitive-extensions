// CONSOLE-001: runtime-only storage for the Homolog test bearer credential.
//
// This value must NEVER be sourced from import.meta.env / VITE_* build-time
// vars: Vite statically inlines referenced import.meta.env.KEY expressions
// into the production bundle, so a build-time secret would be readable by
// anyone via view-source/devtools. Instead the credential is typed into the
// Console UI at runtime (see components/TestSessionPanel.tsx) and kept only
// in this tab's sessionStorage — cleared when the tab closes, never written
// to disk, never part of the build output.

const CREDENTIAL_STORAGE_KEY = 'cognitive-console.test-credential'

function isStorageAvailable(): boolean {
  return typeof window !== 'undefined' && typeof window.sessionStorage !== 'undefined'
}

export function getSessionCredential(): string {
  if (!isStorageAvailable()) return ''
  try {
    return window.sessionStorage.getItem(CREDENTIAL_STORAGE_KEY)?.trim() || ''
  } catch {
    // sessionStorage can throw (e.g. blocked storage, private mode edge cases)
    return ''
  }
}

export function setSessionCredential(value: string): void {
  if (!isStorageAvailable()) return
  const trimmed = value.trim()
  try {
    if (trimmed) {
      window.sessionStorage.setItem(CREDENTIAL_STORAGE_KEY, trimmed)
    } else {
      window.sessionStorage.removeItem(CREDENTIAL_STORAGE_KEY)
    }
  } catch {
    // best-effort; credential simply won't persist for this tab
  }
}

export function clearSessionCredential(): void {
  setSessionCredential('')
}
