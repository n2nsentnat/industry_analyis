# Industry analysis

Fetch job listings from the [Adzuna](https://developer.adzuna.com/) Jobs API **for one job category** using the **category tag** you pass on the CLI (`--category`). Optionally place **`categories.json`** under `DATA_DIR` if you want to pass a **human-readable label** instead of the tag. Output lives under **`DATA_DIR/<category_tag>/`** (raw pages, checkpoint, company index, then flat LLM JSON per company: `Name`, `Industry`, `current_use_of_AI`, `possible_use_of_AI`, `avoid_AI_use`).

## Repository layout

```text
src/industry_analysis/
  presentation/
    app.py                 # FastAPI `/health` (optional dev server)
  company_analysis/      # Bounded context: job ingest + company enrichment
    domain/                # Entities + pure domain rules
    application/           # Ports, DTOs, path helpers, orchestrators
    infrastructure/      # Adzuna, disk JSON, HTTP retry, Ollama / Gemini / OpenAI LLM, settings
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
| **Application** | `company_analysis/application/` | **Ports** (`ports.py`), **DTOs** (`dto.py`), **paths** (`paths.py`), **category catalog** (`categories_catalog.py`), **shared LLM prompt** (`company_prompt.py`), **orchestrators** (`fetch_orchestrator.py`, `enrich_orchestrator.py`). |
| **Infrastructure** | `company_analysis/infrastructure/` | **Adapters**: Adzuna HTTP client, local JSON blob store, retry helper, Ollama / Gemini / OpenAI LLM clients, `pydantic-settings` (`infrastructure/config/settings.py`). |
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

Create a `.env` file in the project root (`pydantic-settings` loads it when running `job-intel`). Minimum for **fetch** (Adzuna + LLM for per-company insights) with the **default local Ollama** backend:

```env
APPLICATION_ID=your_adzuna_app_id
APPLICATION_KEY=your_adzuna_app_key
```

Run **[Ollama](https://ollama.com/)** locally (`ollama serve`), then pull a model (defaults match `OLLAMA_MODEL`, e.g. `ollama pull llama3.2`).

For **Google Gemini**, set `LLM_PROVIDER=gemini` and `GEMINI_API_KEY`. For **OpenAI**, set `LLM_PROVIDER=openai`, `OPENAI_API_KEY`, and optionally `OPENAI_BASE_URL` / `OPENAI_MODEL`.

### Environment variables

| Variable | Purpose |
|----------|---------|
| `APPLICATION_ID` | Adzuna application id (required for fetch) |
| `APPLICATION_KEY` | Adzuna application key (required for fetch) |
| `ADZUNA_COUNTRY` | Country segment in API paths (default: `gb`) |
| `ADZUNA_BASE_URL` | API **host** only (default: `https://api.adzuna.com`). Do not include `/v1/api` — the client adds `/v1/api/jobs/...`. |
| `DATA_DIR` | Root for all JSON artifacts (default: `data/job_intel`) |
| `RESULTS_PER_PAGE` | Jobs per request, max **100** (default: `100`) |
| `FETCH_CATEGORY_CONCURRENCY` | Parallel categories during fetch (default: `4`) |
| `HTTP_MAX_CONCURRENCY` | Cap on concurrent outbound HTTP calls (default: `8`) |
| `HTTP_TIMEOUT_S` | Per-request timeout in seconds (default: `60`) |
| `HTTP_MAX_RETRIES` | Retries on 429 / 5xx with backoff (default: `6`) |
| `LLM_PROVIDER` | `ollama` (**default**, local), `gemini`, or `openai` — which backend **fetch** (insights) and **enrich** use |
| `OLLAMA_BASE_URL` | Ollama HTTP root (default: `http://127.0.0.1:11434`; no path suffix) |
| `OLLAMA_MODEL` | Ollama model id (default: `llama3.2`; run `ollama pull <name>` first) |
| `OLLAMA_TIMEOUT_S` | **Read** timeout per `/api/chat` in seconds (default **300**; local inference often exceeds `HTTP_TIMEOUT_S`) |
| `GEMINI_API_KEY` | [Google AI Studio](https://aistudio.google.com/apikey) key when `LLM_PROVIDER=gemini` |
| `GEMINI_API_BASE` | Gemini REST host (default: `https://generativelanguage.googleapis.com`) |
| `GEMINI_MODEL` | Model id only, e.g. `gemini-2.0-flash` (default). Not a path — wrong values like `gemini/gemini-2.0-flash` are normalized automatically. |
| `OPENAI_API_KEY` | Bearer token when `LLM_PROVIDER=openai` |
| `OPENAI_BASE_URL` | Chat Completions base URL (default: `https://api.openai.com/v1`) |
| `OPENAI_MODEL` | Model id when using OpenAI (default: `gpt-4o-mini`) |
| `GEMINI_MIN_REQUEST_INTERVAL_S` | Seconds between Gemini calls on one client (default **1.0**); serializes traffic to reduce **429** |
| `GEMINI_MAX_RETRIES` | Retries per Gemini request on 429/5xx (default **10**) |
| `ENRICH_CONCURRENCY` | Parallel enrich tasks (default: `4`; Gemini calls also serialize per process to limit 429s) |

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

**Requires `--category`:** the Adzuna **category tag** (e.g. `accounting-finance-jobs`), unless you maintain **`DATA_DIR/categories.json`** — then you may pass an **exact label** (case-insensitive) from that file and it will be resolved to a tag.

The CLI **does not call** Adzuna’s **`/categories`** endpoint; only **`/search`** is used for job pages.

1. Loads **`categories.json`** from disk **if present** (optional). If the file is missing or empty, `--category` is treated as the **tag** verbatim.
2. Paginates that category (up to **`RESULTS_PER_PAGE`** or **`--items-per-page`**, max 100 per request).
3. Writes under **`DATA_DIR/<category_tag>/`**:
   - `checkpoint.json` — resume cursor for this category  
   - `raw/page-00001.json` — raw Adzuna search payloads  
   - `companies_index.json` — merged unique companies from those ads  
4. After jobs are up to date for this run, writes **`insights/<company_key>.json`** per company — **only** the keys `Name`, `Industry`, `current_use_of_AI`, `possible_use_of_AI`, `avoid_AI_use` (no wrapper object). Existing insight files are skipped unless **`--force-insights`**.

`fetch` uses the same LLM configuration as **`enrich`** (`LLM_PROVIDER`, `OLLAMA_*`, `GEMINI_*`, or `OPENAI_*`).

**Structured JSON:** **Ollama** uses native **`/api/chat`** with a JSON-schema **`format`**; **Gemini** uses **`responseSchema`** + **`responseMimeType: application/json`**; **OpenAI** uses **`response_format: json_schema`** with **`strict: true`**. All paths still validate with **`CompanyEnrichment`** (Pydantic) before anything is written to disk. Use a recent Ollama release for schema-constrained **`format`**.

**Optional `categories.json` shape:**

```json
{
  "categories": [
    { "tag": "accounting-finance-jobs", "label": "Accounting & Finance Jobs" }
  ]
}
```

```bash
uv run job-intel fetch --category accounting-finance-jobs
uv run job-intel fetch --category "Accounting & Finance Jobs"
uv run job-intel fetch --category it-jobs --country gb --data-dir /path/to/output
uv run job-intel fetch --category it-jobs --pages 5 --items-per-page 50
uv run job-intel fetch --category it-jobs --force-insights
```

- **`--pages` `N`:** fetch at most **N** result pages for this category (then stop without marking the category completed). Same as legacy **`--max-pages-per-category`** (do not pass both).
- **`--items-per-page` `N`:** Adzuna **`results_per_page`** for each request (**1–100**; default comes from **`RESULTS_PER_PAGE`** in settings / `.env`).

On HTTP failure, the scoped **checkpoint** records `failed_page` and `last_error`. **Re-run the same command** (same `--category` and `DATA_DIR`) to resume.

### `status`

- Without **`--category`:** prints `categories.json` path and count, then **legacy** global checkpoint / companies paths (for older workflows).
- With **`--category`:** resolves tag/label like `fetch`, then prints scoped **`checkpoint.json`**, **`companies_index.json`** summary, and a short company sample (no Adzuna HTTP calls).

```bash
uv run job-intel status
uv run job-intel status --category accounting-finance-jobs
```

### `enrich` (legacy global index)

Reads **`derived/companies_adzuna_<country>.json`** (the old global merge path), writes **`enriched/...`** with a wrapper object (`enrichment` + `source`). The **`fetch`** command above is the primary path now (per-category folder + flat `insights/` JSON).

- **Default LLM:** local **Ollama** (`LLM_PROVIDER=ollama`, `OLLAMA_MODEL`, `ollama serve`).
- **Alternatives:** `LLM_PROVIDER=gemini` + `GEMINI_API_KEY`, or `LLM_PROVIDER=openai` + `OPENAI_API_KEY`.

```bash
uv run job-intel enrich
uv run job-intel enrich --limit 50
uv run job-intel enrich --force
uv run job-intel enrich --llm openai   # one-off override without editing .env
uv run job-intel enrich --llm gemini
```

Options: `--provider-id` (default `adzuna`), `--country`, `--limit`, `--force`, `--llm ollama|gemini|openai`.

**Enriched document shape:** top level has `enrichment` (keys `Name`, `Industry`, `current_use_of_AI`, `possible_use_of_AI`, `avoid_AI_use`) and `source` (metadata; `model` reflects the active provider’s model id).

## Where data is stored

Relative to `DATA_DIR` (default `data/job_intel`):

| Path | Contents |
|------|----------|
| `categories.json` | Optional local map `{ "categories": [ { "tag", "label" }, ... ] }` for **label → tag** lookup only (never fetched from Adzuna by this app) |
| `<category_tag>/checkpoint.json` | Resume state for that category’s job pagination |
| `<category_tag>/raw/page-00001.json` | Raw Adzuna search API payload per page |
| `<category_tag>/companies_index.json` | Merged unique companies for ads seen in that category |
| `<category_tag>/insights/<company_key>.json` | Flat LLM output: `Name`, `Industry`, `current_use_of_AI`, `possible_use_of_AI`, `avoid_AI_use` |

Legacy (optional **`job-intel enrich`** only):

| Path | Contents |
|------|----------|
| `checkpoints/fetch_adzuna_<country>.json` | Old global fetch checkpoint |
| `derived/companies_adzuna_<country>.json` | Old global company index |
| `enriched/adzuna/<country>/<company_key>.json` | Wrapped `enrichment` + `source` |

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
- **Another LLM backend:** implement `JsonObjectLlmPort` in `application/ports.py`, add a client under `infrastructure/llm/`, and register it in `presentation/cli.py` (`_enrich_llm_client`) alongside `OllamaJsonObjectLlm` / `GeminiJsonObjectLlm` / `OpenAiJsonObjectLlm`.
