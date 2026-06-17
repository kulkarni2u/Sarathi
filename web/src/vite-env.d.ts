/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_SARATHI_API_BASE_URL?: string;
  readonly VITE_SARATHI_API_TOKEN?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
