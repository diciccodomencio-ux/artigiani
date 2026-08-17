from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from app.database import init_db, test_database_connection
from app.routes import router
from app.config import settings
from fastapi.staticfiles import StaticFiles

app = FastAPI(
    title="ArtigianAI API",
    version="0.3.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in settings.cors_origins.split(",") if origin.strip()],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)

# serve uploaded files
uploads_path = settings.uploads_dir
uploads_path.mkdir(parents=True, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=str(uploads_path)), name="uploads")


@app.on_event("startup")
def startup_event() -> None:
    if not test_database_connection():
        raise RuntimeError("Connessione al database non riuscita")

    init_db()


@app.get("/")
def home() -> dict[str, str]:
    return {
        "app": "ArtigianAI",
        "status": "online",
    }


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/database-check")
def database_check() -> dict[str, str]:
    if not test_database_connection():
        raise HTTPException(
            status_code=503,
            detail="Connessione al database non riuscita",
        )

    return {"database": "connected"}