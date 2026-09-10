from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router
from app.config import get_settings
from app.database.session import init_db
from app.observability.logging import configure_logging

app = FastAPI(
    title="Distributed Job Orchestrator",
    version="0.1.0",
    description="Reliable asynchronous job processing reference application.",
)
settings = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(router)


@app.on_event("startup")
def startup() -> None:
    configure_logging()
    init_db()


