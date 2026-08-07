# Environment variables

Volundr has typed application defaults. A normal deployment should need only
ports, a data root, provider selection, the provider’s default model, and the
credential for a live provider. The root `.env.example` is intentionally not a
dump of every internal default.

## Minimal production-like configuration

The smallest standard Gemini API deployment is:

```dotenv
VOLUNDR_WEB_PORT=8080
VOLUNDR_API_BIND_ADDRESS=127.0.0.1
VOLUNDR_API_PORT=8000
VOLUNDR_DATA_DIR=./data
VOLUNDR_AI_PROVIDER=gemini_api
GEMINI_API_KEY=replace-with-a-secret
VOLUNDR_GEMINI_MODEL=gemini-3.5-flash-lite
```

The API key is read only by `volundr-api`. It is never compiled into the
frontend or passed to the CadQuery worker. Same-origin Compose deployment does
not require a CORS override. `VOLUNDR_CORS_ORIGINS` remains available for a
separate frontend origin.

The API host binding defaults to loopback. Browser requests use nginx as the
normal boundary; nginx removes client identity and authorization headers and
sets the fixed server-owned `volundr-single-user` actor. For isolated local
development only, set `VOLUNDR_VALIDATED_API_DIRECT_ACCESS_ENABLED=true` and
send `X-Volundr-Direct-Access: true`; the API still uses the fixed actor and
never trusts a caller-selected actor or bearer value.

## Precedence and compatibility

Typed defaults are the baseline. `VOLUNDR_GEMINI_MODEL` selects the normal
provider model. `VOLUNDR_GEMINI_POLICY_PATH`, when supplied, may contain a
`[model_policy.models]` and/or `[model_policy.generation]` TOML table and
overrides built-in Gemini stage and generation defaults. Legacy stage-model and
generation-tuning variables are read only as compatibility overrides when the
policy file does not supply the same value; Volundr emits a deprecation warning
for non-default compatibility values. A policy-file value therefore wins over
an old environment override.

The policy file contains no credentials. Its format is:

```toml
[model_policy.models]
requirements = "gemini-3.5-flash-lite"
design_plan = "gemini-3.5-flash-lite"
geometry = "gemini-3.5-flash-lite"
geometry_repair = "gemini-3.5-flash-lite"
revision_planning = "gemini-3.5-flash-lite"
component_revision = "gemini-3.5-flash-lite"

[model_policy.generation]
temperature = 0.2
max_output_tokens = 8192
thinking_level = "minimal"
max_retries = 2
max_retry_sleep_seconds = 60
```

The existing Gemini CLI tool-policy TOML can continue to contain its `rule`
entries; the Volundr model-policy section is optional and is ignored by the
CLI when absent.

## Full supported inventory

`Supported` means the variable is intentionally accepted by current runtime,
Compose, or test tooling. `Example` means it is shown in the normal root
`.env.example`.

| Variable | Consumer | Current default | Classification | Supported | Example | Replacement, derivation, or deprecation |
| --- | --- | --- | --- | --- | --- | --- |
| `VOLUNDR_WEB_PORT` | Compose | `8080` | common deployment setting | yes | yes | Host port for nginx. |
| `VOLUNDR_API_BIND_ADDRESS` | Compose | `127.0.0.1` | security deployment setting | yes | yes | Host bind address for FastAPI; keep loopback unless direct access is intentionally controlled. |
| `VOLUNDR_API_PORT` | Compose | `8000` | common deployment setting | yes | yes | Host port for FastAPI on the configured bind address. |
| `VOLUNDR_DATA_DIR` | API, worker, Compose | `/app/data` in containers; `./data` in example | common deployment setting | yes | yes | Authoritative data root; child paths derive from it. |
| `VOLUNDR_CAD_WORKSPACE_DIR` | API, worker, live harness | `${VOLUNDR_DATA_DIR}/jobs` | advanced operational override | yes | no | Explicit override retained for split/container and live layouts; otherwise derived. |
| `VOLUNDR_CAD_TIMEOUT_SECONDS` | API, worker | `60` | advanced operational override | yes | no | Typed CAD execution default. |
| `VOLUNDR_WORKFLOW_STALE_SECONDS` | API | `900` | advanced operational override | yes | no | Typed stale-run recovery default. |
| `VOLUNDR_CORS_ORIGINS` | API | localhost Vite origins | advanced operational override | yes | no | Set only for a separately hosted frontend. |
| `VOLUNDR_MAX_SOURCE_BYTES` | API | `512000` | advanced operational override | yes | no | Typed source safety limit. |
| `VOLUNDR_MAX_STL_BYTES` | API | `104857600` | advanced operational override | yes | no | Typed artifact safety limit. |
| `VOLUNDR_DEVELOPER_TOOLS_ENABLED` | API and Compose | `false` | advanced developer deployment setting | yes | no | Backend-authoritative switch for live debug batches; never expose credentials or rely on frontend hiding. |
| `VOLUNDR_VALIDATED_API_DIRECT_ACCESS_ENABLED` | API and Compose | `false` | local-development security override | yes | commented | Allows direct loopback API requests only with `X-Volundr-Direct-Access: true`; all requests still resolve to the fixed single-user actor. |
| `VOLUNDR_AI_PROVIDER` | API | `gemini_api` | common deployment setting | yes | yes | Provider-aware startup and request validation; `gemini_cli` is an explicit experimental API-container transport for the executable-CadQuery flow. |
| `GEMINI_API_KEY` | API | unset | required secret | yes | yes | Required only when live Gemini API requests are made. |
| `VOLUNDR_GEMINI_API_KEY` | API | unset | deprecated compatibility variable | yes | no | Alias for `GEMINI_API_KEY`; migrate to the unprefixed secret. |
| `VOLUNDR_GEMINI_MODEL` | API | `gemini-3.5-flash-lite` | provider-specific setting | yes | yes | General/default Gemini model; stage policy falls back to it. |
| `VOLUNDR_GEMINI_REQUIREMENTS_MODEL` | API | unset | deprecated compatibility variable | yes | no | Move to `[model_policy.models].requirements`. |
| `VOLUNDR_GEMINI_DESIGN_PLAN_MODEL` | API | unset | deprecated compatibility variable | yes | no | Move to `[model_policy.models].design_plan`. |
| `VOLUNDR_GEMINI_GEOMETRY_MODEL` | API and comparison scripts | unset | deprecated compatibility variable | yes | no | Move to `[model_policy.models].geometry`. |
| `VOLUNDR_GEMINI_GEOMETRY_REPAIR_MODEL` | API | unset | deprecated compatibility variable | yes | no | Move to `[model_policy.models].geometry_repair`. |
| `VOLUNDR_GEMINI_REVISION_PLANNING_MODEL` | API | unset | deprecated compatibility variable | yes | no | Move to `[model_policy.models].revision_planning`. |
| `VOLUNDR_GEMINI_COMPONENT_REVISION_MODEL` | API | unset | deprecated compatibility variable | yes | no | Move to `[model_policy.models].component_revision`. |
| `VOLUNDR_GEMINI_POLICY_PATH` | API and Gemini CLI | unset | advanced operational override | yes | commented | Optional policy file; no credentials. |
| `VOLUNDR_GEMINI_TIMEOUT_SECONDS` | API and Gemini CLI | `120` | advanced operational override | yes | commented | Provider request/process timeout. |
| `VOLUNDR_GEMINI_BINARY` | Gemini CLI | `gemini` | provider-specific setting | yes | no | Advanced CLI executable override. |
| `VOLUNDR_GEMINI_API_BASE_URL` | Gemini API | Google Generative Language endpoint | provider-specific setting | yes | no | Optional proxy/testing endpoint; standard endpoint is a code default. |
| `VOLUNDR_GEMINI_API_TEMPERATURE` | API | `0.2` | deprecated compatibility variable | yes | no | Move to `[model_policy.generation].temperature`. |
| `VOLUNDR_GEMINI_API_MAX_OUTPUT_TOKENS` | API | `8192` | deprecated compatibility variable | yes | no | Move to `[model_policy.generation].max_output_tokens`. |
| `VOLUNDR_GEMINI_API_THINKING_LEVEL` | API | `minimal` | deprecated compatibility variable | yes | no | Move to `[model_policy.generation].thinking_level`. |
| `VOLUNDR_GEMINI_API_MAX_RETRIES` | API | `2` | deprecated compatibility variable | yes | no | Move to `[model_policy.generation].max_retries`. |
| `VOLUNDR_GEMINI_API_MAX_RETRY_SLEEP_SECONDS` | API | `60` | deprecated compatibility variable | yes | no | Move to `[model_policy.generation].max_retry_sleep_seconds`. |
| `VOLUNDR_GEMINI_DIR` | Compose | `${VOLUNDR_DATA_DIR}/gemini` | deprecated compatibility variable | yes | no | Derived Gemini CLI profile mount; explicit override retained for existing deployments. |
| `VOLUNDR_OLLAMA_BASE_URL` | Ollama provider | `http://127.0.0.1:11434` | provider-specific setting | yes | commented | Used only when `VOLUNDR_AI_PROVIDER=ollama`; set an explicit host URL for a separate Ollama service. |
| `VOLUNDR_OLLAMA_MODEL` | Ollama provider | `qwen2.5-coder:14b` | provider-specific setting | yes | commented | Used only in Ollama mode. |
| `VOLUNDR_OLLAMA_TIMEOUT_SECONDS` | Ollama provider | `300` | provider-specific setting | yes | no | Used only in Ollama mode. |
| `VOLUNDR_OLLAMA_CONNECT_TIMEOUT_SECONDS` | Ollama provider | `15` | advanced Ollama readiness setting | yes | no | Connection budget; failures are classified separately from generation timeouts. |
| `VOLUNDR_OLLAMA_FIRST_TOKEN_TIMEOUT_SECONDS` | Ollama provider | `300` | advanced Ollama readiness setting | yes | no | Maximum wait for the first streamed token. |
| `VOLUNDR_OLLAMA_GENERATION_IDLE_TIMEOUT_SECONDS` | Ollama provider | `300` | advanced Ollama readiness setting | yes | no | Maximum idle gap between streamed tokens. |
| `VOLUNDR_OLLAMA_TOTAL_GENERATION_TIMEOUT_SECONDS` | Ollama provider | `1800` | advanced Ollama readiness setting | yes | no | Hard total generation budget. |
| `VOLUNDR_OLLAMA_STREAM` | Ollama provider | `true` | advanced Ollama readiness setting | yes | no | Enables incremental NDJSON handling and bounded timeout taxonomy. |
| `VOLUNDR_OLLAMA_THINK` | Ollama provider | unset | provider-specific setting | yes | commented | Used only in Ollama mode. |
| `VOLUNDR_SNAPSHOTS_ENABLED` | API snapshot service | `true` | advanced operational override | yes | commented | Main snapshot switch. |
| `VOLUNDR_SNAPSHOT_IMAGE_WIDTH` | API snapshot service | `768` | advanced operational override | yes | no | Typed range-checked default. |
| `VOLUNDR_SNAPSHOT_IMAGE_HEIGHT` | API snapshot service | `768` | advanced operational override | yes | no | Typed range-checked default. |
| `VOLUNDR_SNAPSHOT_TIMEOUT_SECONDS` | API snapshot service | `30` | advanced operational override | yes | no | Typed timeout default. |
| `VOLUNDR_SNAPSHOT_MAX_WHOLE_DESIGN_VIEWS` | API snapshot service | `5` | advanced operational override | yes | no | Typed maximum. |
| `VOLUNDR_SNAPSHOT_MAX_COMPONENTS` | API snapshot service | `24` | advanced operational override | yes | no | Typed maximum. |
| `VOLUNDR_SNAPSHOT_SECTION_ENABLED` | API snapshot service | `true` | advanced operational override | yes | no | Typed section-snapshot default. |
| `VOLUNDR_SNAPSHOT_BACKGROUND` | API snapshot service | `neutral_light` | advanced operational override | yes | no | Typed neutral background default. |
| `VITE_VOLUNDR_CHAT_FIRST` | frontend build and E2E harness | `true` in Docker; `false` for local source dev | test-only/debug setting | yes | no | Maintained staged UI remains available only for developer/test runs; not a backend lifecycle switch. |
| `VITE_VOLUNDR_GENERATION_MODE` | — | — | obsolete feature flag | no | no | Removed; advanced workflow is established behavior. |
| `VOLUNDR_GENERATION_MODE` | — | — | obsolete feature flag | no | no | Removed; no production reads remain. |
| `VOLUNDR_ENABLE_DESIGN_PLANS` | — | — | obsolete feature flag | no | no | Removed; Design Plans are established workflow behavior. |
| `VOLUNDR_ENABLE_MULTI_OUTPUT` | — | — | obsolete feature flag | no | no | Removed; multi-output behavior is established. |
| `VOLUNDR_ENABLE_STRUCTURED_REVISIONS` | — | — | obsolete feature flag | no | no | Removed; structured revisions are established. |
| `VOLUNDR_CHAT_FIRST` | — | — | obsolete feature flag | no | no | Removed; frontend debug selection is the only maintained mode switch. |
| `VOLUNDR_E2E_PORT` | fixture backend and Vite proxy | `8000` | test-only setting | yes | no | Playwright fixture API port. |
| `VOLUNDR_E2E_API_PORT` | port allocator | `0` | test-only setting | yes | no | Optional allocator input. |
| `VOLUNDR_E2E_WEB_PORT` | port allocator | `0` | test-only setting | yes | no | Optional allocator input. |
| `VOLUNDR_E2E_DATA_DIR` | fixture backend | temporary fixture directory | test-only setting | yes | no | Isolated deterministic fixture state. |
| `VOLUNDR_E2E_CLEANUP` | fixture backend | unset | test-only setting | yes | no | Fixture cleanup switch. |
| `VOLUNDR_E2E_VIEWPORT_WIDTH` | Playwright | browser default | test-only setting | yes | no | Scenario viewport override. |
| `VOLUNDR_E2E_VIEWPORT_HEIGHT` | Playwright | browser default | test-only setting | yes | no | Scenario viewport override. |
| `VOLUNDR_RUN_LIVE_E2E` | live Playwright harness | unset | test-only setting | yes | no | Explicit opt-in for real provider/worker tests. |
| `VOLUNDR_KEEP_LIVE_DATA` | live harness | unset | test-only setting | yes | no | Preserve disposable live data for diagnosis. |
| `VOLUNDR_LIVE_ENV_FILE` | live API wrapper | required by live wrapper | test-only setting | yes | no | Backend-only live environment file path. |
| `VOLUNDR_LIVE_DATA_DIR` | live API wrapper | temporary directory | test-only setting | yes | no | Isolated live state root. |
| `VOLUNDR_LIVE_API_PORT` | live Playwright | `0` | test-only setting | yes | no | Dynamically allocated API port. |
| `VOLUNDR_LIVE_WEB_PORT` | live Playwright | `0` | test-only setting | yes | no | Dynamically allocated web port. |
| `VOLUNDR_VITE_HOST` | Vite harness | `127.0.0.1` | test-only setting | yes | no | Explicit loopback bind. |
| `VOLUNDR_VITE_PORT` | Vite harness | `5173` | test-only setting | yes | no | Harness web port input. |
| `VOLUNDR_PLAYWRIGHT_PORT_FILE` | Playwright port allocator | temp-directory file | test-only setting | yes | no | Isolated deterministic/live port lease file. |
| `VOLUNDR_WORKER_HEALTH_PATH` | CadQuery worker | `/tmp/.worker-health.json` | advanced operational override | yes | no | Worker health-file location, mostly useful to tests and containers. |

## Derived paths and secrets

Unless explicitly overridden, the API workspace is
`{VOLUNDR_DATA_DIR}/jobs`. Compose mounts the host
`{VOLUNDR_DATA_DIR}/jobs` into the worker, which sets its internal data root to
`/work` and therefore derives `/work/jobs`. Gemini CLI state is mounted from
`{VOLUNDR_DATA_DIR}/gemini` by default. Project artifacts, exports, databases,
and workflow bundles remain under the existing data-root convention; there are
no normal environment variables for each child directory.

The worker receives neither `GEMINI_API_KEY` nor Gemini CLI profile data. No
`VITE_*` variable may contain a provider credential or backend operational
setting.

## Advanced overrides

The complete supported advanced set is the operational, provider, snapshot,
compatibility, and test-only inventory above. In normal deployment prefer the
typed defaults. Add only an override needed for a proxy, provider choice,
resource limit, snapshot operation, separate frontend origin, or an isolated
test run.

`VOLUNDR_DEVELOPER_TOOLS_ENABLED` is an advanced developer deployment setting,
not part of the minimal `.env.example`. It defaults to `false`. Set it only on
an intentionally isolated evaluation deployment when live debug-batch APIs and
the matching developer controls are required. The backend rejects every debug
batch operation while it is disabled; frontend visibility is not an
authorization boundary.

Removed rollout flags are intentionally not accepted as application settings.
Unknown `VOLUNDR_*` values are ignored by Pydantic settings for deployment
compatibility, but they no longer alter product behavior.
