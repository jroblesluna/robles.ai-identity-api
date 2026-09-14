# robles.ai — Identity Verification API

Facial biometric matching service. Given a **selfie** and a **photo ID**, it
detects the face in each image, compares them, and returns a match decision plus
a similarity score. Powers the live demo at https://robles.ai/try-identity.

- **Framework:** FastAPI (Python 3.10)
- **Face model:** InsightFace `buffalo_l` (pretrained, CPU inference)
- **Datastore:** Firestore (request records)
- **Storage:** Firebase Storage (processed result images)
- **Hosting:** Google Cloud Run — `https://identity-api.robles.ai`
- **Project (GCP):** `identityverifierapp` · region `us-central1`

---

## How it works

Verification is **asynchronous**: a request is created, then a separate cron
step processes it, then the client polls for the result.

```
1. POST /recognition/verify-id   → creates a Firestore "request" (status: pending)
2. POST /cron/verify-id          → processes pending requests:
     - downloads faceImageUrl + cardIdImageUrl
     - runs InsightFace, compares embeddings (cosine similarity)
     - uploads processed images to Firebase Storage
     - POSTs the result to the request's callback URL
3. GET  /recognition/get/{id}    → client polls this until status is terminal
```

Request status lifecycle: `pending → started → partially_completed →
completed` (or `completed_with_errors` / `failed`).

The match decision uses **cosine similarity** between the two face embeddings;
`match = similarity > 0.35`. (The field is named `distance` in the response but
holds a similarity: higher = more alike.)

---

## Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET`  | `/` | Health check |
| `POST` | `/recognition/verify-id` | Create a verification request. Body: `{ faceImageUrl, cardIdImageUrl, callback }` |
| `GET`  | `/recognition/get/{id}` | Fetch a request by ID (used for polling) |
| `POST` | `/cron/verify-id` | Process pending requests (idempotent; uses a Firestore lock) |

> The `/emotions/*` endpoints were removed — see `_archived/emotions/`.

---

## Local development

Requires a `firebase_key.json` (service-account key) in the project root — it is
gitignored and never committed.

```bash
cp .env.example .env          # defaults are fine to start
# put firebase_key.json in the project root

# Option A — Docker (matches Cloud Run):
docker compose up --build     # → http://localhost:8080

# Option B — native (faster iteration):
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8080 --reload
```

Smoke test:
```bash
curl http://localhost:8080/          # {"message": "Hello, from Identity Identifier Server"}
```

> Note: the Docker image installs InsightFace + OpenCV and bakes in the model,
> so the **first** build is slow. Native runs are quicker for code iteration.

---

## Configuration (environment variables)

| Variable | Default | Purpose |
|----------|---------|---------|
| `STORAGE_BUCKET_NAME` | — (required) | Firebase Storage bucket for processed images |
| `FIREBASE_KEY_PATH` | `firebase_key.json` | Local path to the SA key (ignored on Cloud Run, which mounts `/secrets/FIREBASE_KEY`) |
| `ENV` | `local` | Set to `production` to skip `.env` loading |
| `ALLOWED_ORIGINS` | robles.ai + localhost | Extra CORS origins (comma-separated) |
| `API_KEY` | _(empty)_ | If set, all requests must send `X-API-Key`. Empty = auth disabled |
| `ALLOWED_IMAGE_HOSTS` | firebase/GCS hosts | Extra hosts allowed for server-side image fetch (anti-SSRF) |
| `IMAGE_FETCH_TIMEOUT` | `15` | Timeout (s) for downloading images |
| `CRON_LOCK_STALE_SECONDS` | `600` | Age after which a stuck cron lock is reclaimed |

See `.env.example` for a copy-paste template.

---

## Deployment (CI/CD)

Push to `main` → GitHub Actions builds with Cloud Build and deploys to Cloud Run
automatically. See **[DEPLOYMENT.md](./DEPLOYMENT.md)** for the full setup,
including the one-time `GCP_SA_KEY` secret and how build caching keeps code
pushes fast.

Manual/bootstrap scripts still exist: `deploy_fresh_gcp.sh` (first-time
provisioning) and `update_docker.sh` (manual redeploy).

---

## Project layout

```
app/
  main.py                     # FastAPI app, CORS, /cron/verify-id, routers
  api/endpoints/recognition.py# /recognition/verify-id + /get/{id}
  services/
    recognition_service.py    # InsightFace model + face comparison
    cron_service.py           # async processing of pending requests
    database_service.py       # upload processed images to Firebase Storage
  database/config.py          # Firestore + Storage clients, key resolution
  utils/
    security.py               # anti-SSRF URL validation + optional API key
    response.py               # success/error response envelopes
    others.py                 # numpy→native type conversion
_archived/emotions/           # removed emotions module (see its README)
Dockerfile                    # 3 cached layers: deps → model → app code
docker-compose.yml            # local run matching Cloud Run
.github/workflows/deploy.yml  # CI/CD
```

For deeper architecture, data flow, conventions and known issues, see
**[AGENTS.md](./AGENTS.md)**. For the full GCP resource inventory and a
recreate-from-scratch runbook, see **[INFRASTRUCTURE.md](./INFRASTRUCTURE.md)**.
