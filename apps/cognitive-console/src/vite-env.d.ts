/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_COGNITIVE_ENV?: string
  readonly VITE_COGNITIVE_API_BASE_URL?: string
  readonly VITE_COGNITIVE_TEST_TENANT?: string
  readonly VITE_COGNITIVE_TEST_ACTOR?: string
  readonly VITE_COGNITIVE_TEST_CREDENTIAL?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}

declare module '*.css' {
  const content: string
  export default content
}
