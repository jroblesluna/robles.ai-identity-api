import os
from datetime import datetime, timezone

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from app.api.endpoints import recognition
from app.services.cron_service import run_cron_verify_id
from app.database.config import conect_to_firestoreDataBase
from fastapi.middleware.cors import CORSMiddleware


app = FastAPI()

# ── CORS ────────────────────────────────────────────────────────────────────
# Restrict to known frontends. Override/extend via ALLOWED_ORIGINS env var
# (comma-separated). Avoids the insecure "*" + allow_credentials combination.
_DEFAULT_ORIGINS = [
    "https://robles.ai",
    "https://www.robles.ai",
    "http://localhost:5173",
    "http://localhost:8080",
]
_extra_origins = [o.strip() for o in os.getenv("ALLOWED_ORIGINS", "").split(",") if o.strip()]
_allowed_origins = _DEFAULT_ORIGINS + _extra_origins

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "X-API-Key"],
)

# Montar carpeta de archivos estáticos
app.mount("/static", StaticFiles(directory="static"), name="static")

# Ruta explícita para el favicon
@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    return FileResponse("static/favicon.png")

db = conect_to_firestoreDataBase()

#routes
@app.get("/")
def read_root():
    return {"message": "Hello, from Identity Identifier Server"}

# Recognition routes
app.include_router(recognition.router, prefix="/recognition", tags=["recognition"])



# URL not found exception
@app.exception_handler(404)
async def not_found_handler(request: Request, exc):
    return JSONResponse(
        status_code=404,
        content={
            "message": "The path was not found. Check the URL or consult the documentation."
        }
    )
    
LOCK_DOC_PATH = ('cronLocks', 'taskLock')
# If a lock is older than this, assume the previous run crashed and reclaim it.
LOCK_STALE_SECONDS = int(os.getenv("CRON_LOCK_STALE_SECONDS", "600"))


@app.post("/cron/verify-id")
async def cron_verify_id():
    lock_ref = db.collection(LOCK_DOC_PATH[0]).document(LOCK_DOC_PATH[1])
    try:
        lock_doc = lock_ref.get()

        if lock_doc.exists and lock_doc.to_dict().get("locked", False):
            locked_at = lock_doc.to_dict().get("locked_at")
            # Reclaim a stale lock left behind by a crashed run.
            is_stale = False
            if locked_at is not None:
                age = (datetime.now(timezone.utc) - locked_at).total_seconds()
                is_stale = age > LOCK_STALE_SECONDS
            if not is_stale:
                return {"message": "Task already running."}
            print("Lock obsoleto detectado; reclamando.")

        lock_ref.set({"locked": True, "locked_at": datetime.now(timezone.utc)})
        print("Tarea cron iniciada.")

        await run_cron_verify_id()

        lock_ref.set({"locked": False, "locked_at": None})
        print("Tarea cron completada.")

        return {"message": "Cron task completed."}
    except Exception as e:
        print(f"Error en cron_verify_id: {e}")
        lock_ref.set({"locked": False, "locked_at": None})
        return {"message": str(e)}
