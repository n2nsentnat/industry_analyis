# Industry analysis

Fetch job listings from the [Adzuna](https://developer.adzuna.com/) Jobs API, persist them as JSON on disk, merge employers into a **de-duplicated company index**, and optionally run an LLM pass that outputs structured JSON per company: inferred industry, likely current AI use, possible AI opportunities (automation, core business, new products), and areas where AI is a poor fit.

## Repository layout

```text
src/industry_analysis/
  presentation/
    app.py                 # FastAPI `/health` (optional dev server)
  company_analysis/      # Bounded context: job ingest + company enrichment
    domain/                # Entities + pure domain rules
    application/           # Ports, DTOs, path helpers, orchestrators
    infrastructure/      # Adzuna, disk JSON, HTTP retry, OpenAI, settings
    presentation/
      cli.py               # `job-intel` entrypoint (composition root)
```

Console scripts (from `pyproject.toml`):

| Script | Module |
|--------|--------|
| `job-intel` | `industry_analysis.company_analysis.presentation.cli:main` |
| `api` | `industry_analysis.presentation.app:run` |

## Architecture (onion)

Layers are **inside → out** under `src/industry_analysis/company_analysis/`:

| Layer | Path | Role |
|-------|------|------|
| **Domain** | `company_analysis/domain/` | Entities in `models.py`; merging rules in `company_merge.py`. No imports from outer layers. |
| **Application** | `company_analysis/application/` | Outbound **ports** (`ports.py`: `BlobStore`, `JobSearchProvider`, `JsonObjectLlmPort`), run **DTOs** (`dto.py`), relative **paths** (`paths.py`), **orchestrators** (`fetch_orchestrator.py`, `enrich_orchestrator.py`). Depends only on domain and its own abstractions. |
| **Infrastructure** | `company_analysis/infrastructure/` | **Adapters**: Adzuna HTTP client, local JSON blob store, retry helper, Gemini / OpenAI JSON LLM clients, `pydantic-settings` (`infrastructure/config/settings.py`). |
| **Presentation** | `company_analysis/presentation/cli.py` | Wires `.env` → `Settings` → concrete adapters → orchestrators. |

**Dependency direction:** domain ← application; infrastructure implements application ports; presentation references all layers to build the runnable CLI.

## Requirements

- Python **3.13+**
- [uv](https://docs.astral.sh/uv/) (recommended)

## Setup

From the repository root:

```bash
uv sync
```

Create a `.env` file in the project root (`pydantic-settings` loads it when running `job-intel`). Minimum for **fetch**:

```env
APPLICATION_ID=your_adzuna_app_id
APPLICATION_KEY=your_adzuna_app_key
```

Add for **enrich** (default backend is **Gemini**):

```env
GEMINI_API_KEY=your_google_ai_studio_key
```

Optional: use OpenAI instead (`LLM_PROVIDER=openai` plus `OPENAI_API_KEY`).

### Environment variables

| Variable | Purpose |
|----------|---------|
| `APPLICATION_ID` | Adzuna application id (required for fetch) |
| `APPLICATION_KEY` | Adzuna application key (required for fetch) |
| `ADZUNA_COUNTRY` | Country segment in API paths (default: `gb`) |
| `ADZUNA_BASE_URL` | API base URL (default: `https://api.adzuna.com`) |
| `DATA_DIR` | Root for all JSON artifacts (default: `data/job_intel`) |
| `RESULTS_PER_PAGE` | Jobs per request, max **100** (default: `100`) |
| `FETCH_CATEGORY_CONCURRENCY` | Parallel categories during fetch (default: `4`) |
| `HTTP_MAX_CONCURRENCY` | Cap on concurrent outbound HTTP calls (default: `8`) |
| `HTTP_TIMEOUT_S` | Per-request timeout in seconds (default: `60`) |
| `HTTP_MAX_RETRIES` | Retries on 429 / 5xx with backoff (default: `6`) |
| `LLM_PROVIDER` | `gemini` (default) or `openai` — which API `enrich` calls |
| `GEMINI_API_KEY` | [Google AI Studio](https://aistudio.google.com/apikey) key when `LLM_PROVIDER=gemini` |
| `GEMINI_API_BASE` | Gemini REST host (default: `https://generativelanguage.googleapis.com`) |
| `GEMINI_MODEL` | Model id for `generateContent` (default: `gemini-2.0-flash`) |
| `OPENAI_API_KEY` | Bearer token when `LLM_PROVIDER=openai` |
| `OPENAI_BASE_URL` | Chat Completions base URL (default: `https://api.openai.com/v1`) |
| `OPENAI_MODEL` | Model id when using OpenAI (default: `gpt-4o-mini`) |
| `ENRICH_CONCURRENCY` | Parallel enrich tasks (default: `4`) |

Generated data under `DATA_DIR` is listed in `.gitignore` (`data/job_intel/` by default).

## CLI: `job-intel`

After `uv sync`:

```bash
uv run job-intel --help
```

Equivalent module invocation:

```bash
uv run python -m industry_analysis.company_analysis.presentation.cli --help
```

Global option: `--data-dir <path>` overrides `DATA_DIR` for that run.

### `fetch`

- Loads **categories** from Adzuna, then **paginates** each category (`results_per_page` ≤ 100).
- Writes **raw** API payloads per page, updates a **checkpoint** (resume after crash), and updates **`derived/companies_adzuna_<country>.json`** (company de-duplication by normalized display name; job ids skipped if already seen).

```bash
uv run job-intel fetch
uv run job-intel fetch --only-category it-jobs
uv run job-intel fetch --country gb
uv run job-intel fetch --data-dir /path/to/output
uv run job-intel fetch --max-pages-per-category 2   # safety cap; does not mark category completed
```

On failure, the checkpoint records `failed_page` and `last_error` for that category. **Re-run the same command** to retry from `next_page` (see `status`).

### `status`

Prints the checkpoint path, checkpoint JSON, company count, and a short sample list.

```bash
uv run job-intel status
uv run job-intel status --country gb --data-dir ./data/job_intel
```

### `enrich`

Reads the derived companies file, calls the configured LLM with **JSON output**, writes one file per company under `enriched/`. Skips existing outputs unless `--force`.

- **Default:** Google **Gemini** (`LLM_PROVIDER=gemini`, `GEMINI_API_KEY`, `GEMINI_MODEL`). Uses the `generateContent` API with `responseMimeType: application/json`.
- **Alternative:** Set `LLM_PROVIDER=openai` and provide `OPENAI_API_KEY` (Chat Completions + `response_format: json_object`).

```bash
uv run job-intel enrich
uv run job-intel enrich --limit 50
uv run job-intel enrich --force
uv run job-intel enrich --llm openai   # one-off override without editing .env
```

Options: `--provider-id` (default `adzuna`), `--country`, `--limit`, `--force`, `--llm gemini|openai`.

**Enriched document shape:** top level has `enrichment` (keys `Name`, `Industry`, `current_use_of_AI`, `possible_use_of_AI`, `avoid_AI_use`) and `source` (metadata; `model` reflects the active provider’s model id).

## Where data is stored

Relative to `DATA_DIR` (default `data/job_intel`):

| Path | Contents |
|------|----------|
| `checkpoints/fetch_adzuna_<country>.json` | Per-category `next_page`, `completed`, errors |
| `raw_jobs/adzuna/<country>/<category_tag>/page-00001.json` | Raw search API payload per page |
| `derived/companies_adzuna_<country>.json` | Merged unique companies |
| `enriched/adzuna/<country>/<company_key>.json` | LLM output per company |

## Optional HTTP API

```bash
uv run api
```

Health: `http://127.0.0.1:8000/health`.

## Development

```bash
uv run ruff check src
uv run mypy src
```

`mypy` is configured with the **pydantic** plugin in `pyproject.toml` so `BaseSettings` fields populated from the environment type-check correctly.

## Extending the pipeline

- **Another job provider:** match the `JobSearchProvider` protocol in `company_analysis/application/ports.py` (see `AdzunaJobSearchProvider` in `infrastructure/providers/adzuna_job_search.py`), register construction in `presentation/cli.py`.
- **Another store:** implement `BlobStore` in `application/ports.py`, add an adapter under `infrastructure/persistence/`, pass it into `FetchOrchestrator` / `EnrichOrchestrator`.
- **Another LLM backend:** implement `JsonObjectLlmPort` in `application/ports.py`, add a client under `infrastructure/llm/`, and register it in `presentation/cli.py` (`_enrich_llm_client`) alongside `GeminiJsonObjectLlm` / `OpenAiJsonObjectLlm`.
