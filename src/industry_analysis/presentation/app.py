from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from industry_analysis.presentation.job_intel_routes import router as job_intel_router

_root = Path(__file__).resolve().parents[3]
_ui_dist = _root / "web" / "dist"

app = FastAPI(title="Industry analysis API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:5173",
        "http://localhost:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(job_intel_router)


@app.get("/api/info")
async def api_info() -> dict[str, object]:
    """Machine-readable links (same data the HTML landing used to return)."""
    links: dict[str, str] = {
        "health": "/health",
        "openapi": "/openapi.json",
        "docs": "/docs",
        "api_categories": "/api/job-intel/categories",
        "api_aggregates": "/api/job-intel/aggregates?top_n=35",
        "api_companies": "/api/job-intel/companies?limit=40",
        "dev_ui": "http://127.0.0.1:5173/",
    }
    if _ui_dist.is_dir():
        links["built_ui"] = "/ui/"
    return {"service": "industry_analysis", "links": links}


@app.get("/", response_class=HTMLResponse)
async def root() -> str:
    """Browser-visible instructions; charts are on :5173 (Vite) or /ui/ after build."""
    body_class = "built" if _ui_dist.is_dir() else "nobuild"
    path = Path(__file__).resolve().parent / "dashboard_landing.html"
    html = path.read_text(encoding="utf-8")
    return html.replace("__BODY_CLASS__", body_class)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/ui", include_in_schema=False)
async def ui_trailing_slash() -> RedirectResponse:
    """``/ui`` without slash often 404s for static SPA; normalize to ``/ui/``."""
    return RedirectResponse(url="/ui/", status_code=307)


if _ui_dist.is_dir():
    app.mount("/ui", StaticFiles(directory=str(_ui_dist), html=True), name="job_intel_ui")


def run() -> None:
    import uvicorn

    uvicorn.run(
        "industry_analysis.presentation.app:app",
        host="127.0.0.1",
        port=8000,
        reload=True,
    )
