/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_COGNITIVE_ENV?: string
  readonly VITE_COGNITIVE_API_BASE_URL?: string
  readonly VITE_COGNITIVE_TEST_TENANT?: string
  readonly VITE_COGNITIVE_TEST_ACTOR?: string
  // VITE_COGNITIVE_TEST_CREDENTIAL is intentionally NOT declared here.
  // See src/config/session.ts (CONSOLE-001): the test bearer credential must
  // never be read from a build-time env var, or it gets inlined into the
  // production JS bundle. It is entered at runtime and kept in
  // sessionStorage only.
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}

declare module '*.css' {
  const content: string
  export default content
}
