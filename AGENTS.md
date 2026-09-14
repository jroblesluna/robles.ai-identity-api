# AGENTS.md — Context for AI agents & new contributors

This file gives an agent (or a new engineer) enough context to work on this repo
in a **single session** without re-discovering everything. Read it before making
changes.

---

## 1. What this service is

The **identity verification API** for robles.ai. It performs facial biometric
matching: compare a selfie against a photo ID and decide if they are the same
person. It backs the public demo at `https://robles.ai/try-identity` (frontend
lives in the separate `robles.ai` repo, page `src/pages/TryIdentity.tsx`).

- FastAPI · Python 3.10 · InsightFace `buffalo_l` (CPU) · Firestore · Firebase Storage
- Deployed on **Google Cloud Run**, project `identityverifierapp`, region `us-central1`
- Public URL: `https://identity-api.robles.ai` (Cloud Run domain mapping + CNAME to `ghs.googlehosted.com`)

## 2. The model — important conceptual note

There is **no training** anywhere. `buffalo_l` is a **pretrained** InsightFace
pack (SCRFD detector + ArcFace ResNet-50 embeddings + 3D landmarks). The code
only does **inference**: extract a 512-d embedding per face and compare.

- Match logic: **cosine similarity** of the two embeddings; `match = similarity > 0.35`.
- The response field is called `distance` but stores a **similarity** (higher = more alike). Frontend shows it as `distance * 100` %.
- The model is downloaded by InsightFace on first use. The Dockerfile now
  **bakes it into the image at build time** (a dedicated cached layer), so it is
  not re-downloaded on code pushes and cold-starts are fast.

If anyone says "reprocess/retrain the model" — there is nothing to retrain. What
used to feel slow was **dependency install** + first-run model download, both
now handled by Docker layer caching.

## 3. Request flow (asynchronous)

```
Client (TryIdentity.tsx)
  │  uploads selfie + ID to Firebase Storage, gets public URLs
  ▼
POST /recognition/verify-id  {faceImageUrl, cardIdImageUrl, callback}
  │  → creates Firestore doc in collection "request", status="pending"
  ▼
POST /cron/verify-id   (triggered by the frontend right after)
  │  → run_cron_verify_id(): finds pending docs, for each:
  │      1. read_image_from_url() both images
  │      2. compare_verify_faces() with InsightFace
  │      3. upload_image_cv2() the 4 result images to Storage
  │      4. POST result to the doc's callback URL
  │      5. update status → completed / completed_with_errors / failed
  ▼
GET /recognition/get/{id}   (frontend polls every 3s until terminal status)
```

Status lifecycle: `pending → started → partially_completed → completed`
(`failed` / `completed_with_errors` on problems).

Result `output` contains: `result_match` (bool), `distance` (similarity), and 4
image URLs: `FaceImageCV2`, `CardImageCV2`, `FaceLandMarksImage`,
`CardLandMarksImage`.

## 4. Data stores

- **Firestore** — collection `request` (one doc per verification). Also
  `cronLocks/taskLock` (see cron locking below).
- **Firebase Storage** — bucket `identityverifierapp.firebasestorage.app`.
  Processed images go under `images/`. Frontend uploads go under `demo-uploads/`.
  ⚠️ Images are **never deleted** → the bucket grows forever. This once caused a
  `storage/quota-exceeded` outage. Consider a lifecycle rule to expire old objects.

## 5. Auth to GCP / credentials

- `app/database/config.py::get_firebase_key_path()` resolves the service-account
  key: uses `/secrets/FIREBASE_KEY` if present (Cloud Run secret mount), else
  `FIREBASE_KEY_PATH` env / local `firebase_key.json`.
- On Cloud Run the secret is mounted **pinned to version `:1`** (not `latest`).
  Using `latest` caused ~$3.48/mo in Secret Manager access charges; pinning fixed it.
- `firebase_key.json` is gitignored — never commit it. It comes from the Firebase
  Admin SDK SA (`firebase-adminsdk-fbsvc@…`): Firebase console → Project settings
  → Service accounts → Generate new private key.

### Secrets — two different things (don't confuse them)
- **`FIREBASE_KEY`** — the only **GCP Secret Manager** secret. The Firebase SA
  JSON. Mounted at `/secrets/FIREBASE_KEY:1` on Cloud Run.
- **`GCP_SA_KEY`** — a **GitHub Actions** secret (not in GCP). Key for the
  `github-deployer` SA that lets CI/CD deploy. Set via `gh secret set`.

Full GCP inventory + recreate-from-scratch runbook: see **INFRASTRUCTURE.md**.

## 6. Security posture (added 2026-09)

`app/utils/security.py` centralizes two protections:

- **Anti-SSRF** (`validate_image_url`): before the server fetches any user-supplied
  image URL, it checks scheme is http(s), host is in an allowlist (Firebase/GCS by
  default, extend via `ALLOWED_IMAGE_HOSTS`), and the host does **not** resolve to
  a private/loopback/link-local IP. Prevents fetching cloud metadata / internal
  services. `requests.get` now also has `IMAGE_FETCH_TIMEOUT`.
- **Optional API key** (`require_api_key`): a router dependency. **No-op unless
  `API_KEY` env is set**, so the current keyless frontend keeps working. When set,
  requests must send `X-API-Key`. Note: a key in a public frontend is not secret —
  it's rate-limiting hygiene, not real auth.

CORS is restricted (`main.py`) to robles.ai + localhost, extendable via
`ALLOWED_ORIGINS`. Do **not** revert to `allow_origins=["*"]` with credentials.

Still open (needs frontend coordination): real auth, and signed/expiring URLs
for the biometric images (currently public Storage URLs with a token, no expiry —
a privacy concern for face/ID data).

## 7. Cron locking

`/cron/verify-id` uses a Firestore lock doc `cronLocks/taskLock`. It stores
`locked` + `locked_at`. A lock older than `CRON_LOCK_STALE_SECONDS` (default 600)
is treated as stale and reclaimed — this prevents a crashed run from wedging the
cron forever. There is no Cloud Scheduler; the cron is triggered by the frontend
`fetch` after creating a request.

## 8. Build & deploy

- **Dockerfile** has 3 cache-friendly layers, in order:
  1. `requirements.txt` + `pip install`  (deps)
  2. pre-download InsightFace `buffalo_l` (model)
  3. `COPY . /app`                        (app code)
  Code-only pushes reuse layers 1–2, so builds stay fast. Only changing
  `requirements.txt` rebuilds deps + model.
- **CI/CD**: `.github/workflows/deploy.yml` runs on push to `main` → Cloud Build
  builds the image (tags `:$GITHUB_SHA` and `:latest`) → `gcloud run deploy`.
  Requires the `GCP_SA_KEY` GitHub secret (setup in DEPLOYMENT.md).
- Deploy flags fixed by the workflow: `--memory=4Gi`, `--max-instances=2`,
  `STORAGE_BUCKET_NAME` + `ALLOWED_ORIGINS` env, secret `FIREBASE_KEY:1`.
- Legacy scripts: `deploy_fresh_gcp.sh` (full provisioning), `update_docker.sh`
  (manual redeploy). Kept for bootstrap; day-to-day uses the workflow.

## 9. Conventions & gotchas

- **dlib / face_recognition are dead code.** The service migrated to InsightFace;
  all `face_recognition` usage is commented out. The Dockerfile no longer compiles
  dlib. `dlib-precompiled/` stays in the repo but is `.dockerignore`d.
- **Emotions was removed.** It used `py-feat` → pulled `torch` + full CUDA (~4 GB)
  into a CPU-only image. Code is in `_archived/emotions/`. If reviving, deploy it
  as a **separate** service, don't add it back here.
- `output` field `distance` = similarity, not distance (naming is misleading).
- `conect_to_firestoreDataBase` has a typo in its name — kept for compatibility;
  don't rename without updating all call sites.
- Responses use envelopes from `utils/response.py`: `{success, code, message, data}`.
- No formal test suite. Validate `utils/security.py` logic with a lightweight
  script + a venv with just `fastapi` (the full deps are heavy).

## 10. Related repos

- **Frontend**: `robles.ai` repo → `src/pages/TryIdentity.tsx` calls this API and
  uploads images to Firebase Storage. i18n keys under `try-identity` in
  `src/i18n/locales/{en,es}/translation.json`.

## 11. Change log (high level)

- **2026-09**: Removed emotions/py-feat; slimmed Dockerfile (no dlib), 3-layer
  caching + baked model; added anti-SSRF + optional API key + tightened CORS;
  cron lock TTL; GitHub Actions CI/CD; docker-compose + docs (README, AGENTS,
  DEPLOYMENT, INFRASTRUCTURE). Migrated GCP billing to a US account; pinned
  FIREBASE_KEY secret to `:1`; capped `--max-instances=2`.
