import os

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from app.api.endpoints import recognition
from app.services.cron_service import run_cron_verify_id
from app.services import store
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


@app.post("/cron/verify-id")
async def cron_verify_id():
    # Serialize cron runs in-process (was a Firestore lock). With
    # --max-instances=1 this single lock guarantees pending requests are not
    # processed twice. If a run is already in progress, skip.
    if store.cron_lock.locked():
        return {"message": "Task already running."}
    async with store.cron_lock:
        try:
            print("Cron task started.")
            await run_cron_verify_id()
            print("Cron task completed.")
            return {"message": "Cron task completed."}
        except Exception as e:
            print(f"Error in cron_verify_id: {e}")
            return {"message": str(e)}
