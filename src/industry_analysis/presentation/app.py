import uvicorn
from fastapi import FastAPI

app = FastAPI()


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


def run() -> None:
    uvicorn.run(
        "industry_analysis.presentation.app:app",
        host="127.0.0.1",
        port=8000,
        reload=True,
    )
