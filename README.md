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

Every push to `main` triggers `.github/workflows/deploy.yml`, which builds the
image with Cloud Build and deploys it to Cloud Run. No manual `gcloud` needed.

### One-time setup (required for the workflow to work)

The workflow authenticates to GCP with a service-account key stored as the
GitHub secret `GCP_SA_KEY`. Create it once:

```bash
# 1. Create a deployer service account
gcloud iam service-accounts create github-deployer \
  --project=identityverifierapp \
  --display-name="GitHub Actions deployer"

SA="github-deployer@identityverifierapp.iam.gserviceaccount.com"

# 2. Grant the roles needed to build + deploy
for ROLE in roles/run.admin roles/cloudbuild.builds.editor \
            roles/artifactregistry.writer roles/iam.serviceAccountUser \
            roles/storage.admin; do
  gcloud projects add-iam-policy-binding identityverifierapp \
    --member="serviceAccount:$SA" --role="$ROLE"
done

# 3. Create a key and add it to GitHub secrets as GCP_SA_KEY
gcloud iam service-accounts keys create key.json --iam-account="$SA"
gh secret set GCP_SA_KEY --repo jroblesluna/robles.ai-identity-api < key.json
rm key.json   # do not keep the key on disk
```

> Security note: a long-lived SA key is the simplest option but not the most
> secure. Consider migrating to Workload Identity Federation (keyless) later:
> swap the `credentials_json` input for `workload_identity_provider`.

### Build caching — code pushes don't reinstall deps or re-download the model

The Dockerfile is layered so day-to-day code changes build fast:

1. `COPY requirements.txt` + `pip install`  → dependency layer
2. Pre-download InsightFace `buffalo_l`      → model layer
3. `COPY . /app`                             → application layer

Layers 1–2 are only rebuilt when `requirements.txt` changes. A code-only push
reuses the cached dependency + model layers and only rebuilds the small app
layer. The pretrained model is baked into the image at build time, so it is
never re-downloaded on push and production cold-starts are fast. (Cloud Build
reuses cache across builds via the `:latest` tag it also pushes. The first build
— or any `requirements.txt` change — is slow; subsequent code pushes are quick.)

### What the deploy preserves

- Secret mounted at `/secrets/FIREBASE_KEY` pinned to version `:1` (avoids the
  Secret Manager access cost from `latest`).
- `--max-instances=2` to cap compute cost.
- `STORAGE_BUCKET_NAME` and `ALLOWED_ORIGINS` env vars.

To enable API-key auth in production, add an `API_KEY` value to the
`--set-env-vars` list in the workflow (and send it from the frontend).

### Legacy / bootstrap scripts

`deploy_fresh_gcp.sh` (full first-time provisioning) and `update_docker.sh`
(manual redeploy) still work for manual/bootstrap use, but day-to-day deploys
go through GitHub Actions. See **[AGENTS.md](./AGENTS.md)** for the full GCP
resource inventory and a recreate-from-scratch runbook.

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

For deeper architecture, data flow, conventions, the full GCP resource
inventory and a recreate-from-scratch runbook, see **[AGENTS.md](./AGENTS.md)**.
