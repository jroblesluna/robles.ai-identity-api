# robles.ai — Identity Verification API

Facial biometric matching service. Given a **selfie** and a **photo ID**, it
detects the face in each image, compares them, and returns a match decision plus
a similarity score. Powers the live demo at https://robles.ai/try-identity.

- **Framework:** FastAPI (Python 3.10)
- **Face model:** InsightFace `buffalo_l` (pretrained, CPU inference)
- **Datastore:** none — the async request queue lives **in-process** (memory)
- **Storage:** none — images are exchanged as **base64** (nothing persisted)
- **Hosting:** Google Cloud Run — `https://identity-api.robles.ai`
- **Project (GCP):** `robles-ai-identity-project` · region `us-central1`

> **No Firebase.** This service used to depend on Firestore (as a request queue)
> and Firebase Storage (for processed images). Both were removed: the queue is
> now a process-local store (`app/services/store.py`) and images travel as
> base64 in the request/response. The service runs with `--max-instances=1` so
> the single instance owns the whole async flow. No biometric data is persisted
> anywhere — it lives only for the lifetime of the request.

---

## How it works

Verification is **asynchronous**: a request is created, then a separate cron
step processes it, then the client polls for the result. (The async flow is kept
for demo UX — a visible "queue → processing → done" progression — even though it
now runs entirely in memory.)

```
1. POST /recognition/verify-id   → creates an in-memory request (status: pending)
                                    body carries the two images as base64
2. POST /cron/verify-id          → processes pending requests:
     - decodes the base64 selfie + ID images
     - runs InsightFace, compares embeddings (cosine similarity)
     - encodes the processed images back to base64 (data-URIs)
     - POSTs the result to the request's callback URL (if provided)
3. GET  /recognition/get/{id}    → client polls this until status is terminal
                                    (base64 input images are redacted here)
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
| `POST` | `/recognition/verify-id` | Create a verification request. Body: `{ faceImageBase64, cardIdImageBase64, callback }` |
| `GET`  | `/recognition/get/{id}` | Fetch a request by ID (used for polling) |
| `POST` | `/cron/verify-id` | Process pending requests (idempotent; uses an in-process asyncio lock) |

> The `/emotions/*` endpoints were removed.
> Legacy `faceImageUrl` / `cardIdImageUrl` body keys are still accepted for
> backward compatibility, but the demo now sends base64.

---

## Local development

No credentials required — there is no Firebase key or bucket to configure.

```bash
cp .env.example .env          # defaults are fine to start

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
| `ENV` | `local` | Set to `production` to skip `.env` loading |
| `ALLOWED_ORIGINS` | robles.ai + localhost | Extra CORS origins (comma-separated) |
| `API_KEY` | _(empty)_ | If set, all requests must send `X-API-Key`. Empty = auth disabled |
| `ALLOWED_IMAGE_HOSTS` | firebase/GCS hosts | Extra hosts allowed for server-side image fetch (anti-SSRF; only used by the legacy URL fetch helper) |
| `IMAGE_FETCH_TIMEOUT` | `15` | Timeout (s) for downloading images (legacy URL fetch only) |

See `.env.example` for a copy-paste template.

---

## Deployment (CI/CD)

Every push to `main` triggers `.github/workflows/deploy.yml`, which builds the
image with Cloud Build and deploys it to Cloud Run. No manual `gcloud` needed.

### One-time setup (required for the workflow to work)

`deploy_fresh_gcp.sh` provisions the GCP resources once — it **creates the GCP
project if it doesn't exist**, links billing, enables APIs, builds + deploys, and
**creates the `github-deployer` service account** (with the roles needed to
build + deploy). After running it, all that's left is to give GitHub the key:

```bash
# github-deployer already exists (created by deploy_fresh_gcp.sh).
# 1. Create a JSON key for it:
gcloud iam service-accounts keys create key.json \
  --iam-account=github-deployer@robles-ai-identity-project.iam.gserviceaccount.com \
  --project=robles-ai-identity-project
# 2. Store it as the repo secret the workflow uses, then delete the file:
gh secret set GCP_SA_KEY --repo jroblesluna/robles.ai-identity-api < key.json
rm key.json   # do not keep the key on disk (it is gitignored as a safety net)
```

The workflow then deploys on push (and can be triggered manually from the Actions
tab via `workflow_dispatch`). Manual fallback: `update_docker.sh`.

> Security note: a long-lived SA key is the simplest option but not the most
> secure. Consider migrating to Workload Identity Federation (keyless) later:
> swap the `credentials_json` input for `workload_identity_provider`.

### What the deploy sets

- `--max-instances=1` — the async flow state lives in the process; a single
  instance guarantees enqueue / process / poll all hit the same memory.
- `--memory=4Gi` for the InsightFace model.
- `ALLOWED_ORIGINS` env var. No secrets, no bucket, no Firestore.

To enable API-key auth in production, add an `API_KEY` value to the
`--set-env-vars` list in the workflow (and send it from the frontend).

### Deploy scripts

The four API repos (`robles.ai-identity-api`, `robles.ai-rag-api`,
`robles.ai-langchain-api`, `robles.ai-transcription-api`) share the same deploy
scripts, each individualized:

| Script | Purpose |
|--------|---------|
| `deploy_fresh_gcp.sh` | Full first-time provisioning (project, billing, APIs, repo, SAs, deploy, domain) |
| `update_docker.sh` | Code change: rebuild (Kaniko cache) + redeploy — manual fallback |
| `delete_all_gcp_resources.sh` | Tear down all GCP resources |

Day-to-day deploys go through GitHub Actions. See **[AGENTS.md](./AGENTS.md)**
for the full GCP resource inventory and a recreate-from-scratch runbook.

---

## Project layout

```
app/
  main.py                     # FastAPI app, CORS, /cron/verify-id, routers
  api/endpoints/recognition.py# /recognition/verify-id + /get/{id}
  services/
    recognition_service.py    # InsightFace model + comparison + base64 encode/decode
    cron_service.py           # async processing of pending requests
    store.py                  # in-memory request store (replaces Firestore)
  database/config.py          # loads .env in dev (no Firebase)
  utils/
    security.py               # anti-SSRF URL validation + optional API key
    response.py               # success/error response envelopes
    others.py                 # numpy→native type conversion
Dockerfile                    # cached layers: deps → model → app code
docker-compose.yml            # local run matching Cloud Run
.github/workflows/deploy.yml  # CI/CD
```

For deeper architecture, data flow, conventions, the full GCP resource
inventory and a recreate-from-scratch runbook, see **[AGENTS.md](./AGENTS.md)**.
