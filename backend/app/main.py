from fastapi import FastAPI

app = FastAPI(
    title="Distributed Job Orchestrator",
    version="0.1.0",
    description="Reliable asynchronous job processing reference application.",
)


@app.get("/health", tags=["system"])
def health() -> dict[str, str]:
    """Report that the HTTP process is alive."""

    return {"status": "ok"}
