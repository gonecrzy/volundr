# Environment variables

The repository’s actively consumed variables are listed below. A value with
`secret: yes` must never be compiled into the frontend, included in a project
package, or passed to the CadQuery worker.

| Variable | Service | Required | Default | Secret | Restart |
| --- | --- | --- | --- | --- | --- |
| `VOLUNDR_DATA_DIR` | API/worker/Compose mount | no | `/app/data` in containers | no | yes |
| `VOLUNDR_CAD_WORKSPACE_DIR` | API/worker | no | `${VOLUNDR_DATA_DIR}/jobs` | no | yes |
| `VOLUNDR_CAD_TIMEOUT_SECONDS` | API/worker | no | `60` | no | yes |
| `VOLUNDR_WORKFLOW_STALE_SECONDS` | API | no | `900` | no | yes |
| `VOLUNDR_MAX_SOURCE_BYTES` | API | no | `512000` | no | yes |
| `VOLUNDR_MAX_STL_BYTES` | API | no | `104857600` | no | yes |
| `VOLUNDR_CORS_ORIGINS` | API | no | localhost/127.0.0.1 Vite origins | no | yes |
| `VOLUNDR_AI_PROVIDER` | API | no | `gemini_api` | no | yes |
| `GEMINI_API_KEY` | API only | live Gemini | empty | yes | yes |
| `VOLUNDR_GEMINI_MODEL` | API | no | `gemini-3.5-flash-lite` | no | yes |
| `VOLUNDR_GEMINI_*_MODEL` | API | no | unset; uses general model | no | yes |
| `VOLUNDR_GEMINI_API_BASE_URL` | API | no | Google Generative Language API | no | yes |
| `VOLUNDR_GEMINI_API_TEMPERATURE` | API | no | `0.2` | no | yes |
| `VOLUNDR_GEMINI_API_MAX_OUTPUT_TOKENS` | API | no | `8192` | no | yes |
| `VOLUNDR_GEMINI_API_THINKING_LEVEL` | API | no | `minimal` | no | yes |
| `VOLUNDR_GEMINI_API_MAX_RETRIES` | API | no | `2` | no | yes |
| `VOLUNDR_GEMINI_API_MAX_RETRY_SLEEP_SECONDS` | API | no | `60` | no | yes |
| `VOLUNDR_GEMINI_TIMEOUT_SECONDS` | API | no | `120` | no | yes |
| `VOLUNDR_GEMINI_BINARY` | API | no | `gemini` | no | yes |
| `VOLUNDR_GEMINI_POLICY_PATH` | API | no | unset | no | yes |
| `VOLUNDR_OLLAMA_BASE_URL` | API | no | configured development URL | no | yes |
| `VOLUNDR_OLLAMA_MODEL` | API | no | `qwen2.5-coder:14b` | no | yes |
| `VOLUNDR_OLLAMA_TIMEOUT_SECONDS` | API | no | `300` | no | yes |
| `VOLUNDR_OLLAMA_THINK` | API | no | unset | no | yes |
| `VOLUNDR_GENERATION_MODE` | API | no | `advanced` | no | yes |
| `VOLUNDR_ENABLE_DESIGN_PLANS` | API | no | `true` | no | yes |
| `VOLUNDR_ENABLE_MULTI_OUTPUT` | API | no | `true` | no | yes |
| `VOLUNDR_ENABLE_STRUCTURED_REVISIONS` | API | no | `true` | no | yes |
| `VOLUNDR_CHAT_FIRST` | API | no | `false` in Settings; Compose uses `true` | no | yes |
| `VOLUNDR_WEB_PORT` | Compose | no | `8080` | no | yes |
| `VOLUNDR_API_PORT` | Compose | no | `8000` | no | yes |
| `VOLUNDR_GEMINI_DIR` | Compose | no | `./data/gemini` | no | yes |
| `VITE_VOLUNDR_GENERATION_MODE` | browser build | no | `advanced` | no | rebuild |
| `VITE_VOLUNDR_CHAT_FIRST` | browser build | no | `true` in Compose | no | rebuild |

Testing-only variables such as `VOLUNDR_E2E_PORT`,
`VOLUNDR_E2E_WEB_PORT`, `VOLUNDR_VITE_HOST`, `VOLUNDR_VITE_PORT`,
`VOLUNDR_PLAYWRIGHT_PORT_FILE`, live opt-in flags, and fixture paths are set
by the Playwright/live scripts and are not part of the production browser
environment. No Gemini key is accepted through a `VITE_*` variable.
