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

- FastAPI · Python 3.10 · InsightFace `buffalo_l` (CPU) · **no external datastore**
- Deployed on **Google Cloud Run**, project `robles-ai-identity-project`, region `us-central1`
- Public URL: `https://identity-api.robles.ai` (Cloud Run domain mapping + CNAME to `ghs.googlehosted.com`)

> **No Firebase.** This service previously used Firestore (request queue) and
> Firebase Storage (processed images). Both were **removed** (2026-09). The queue
> is now a process-local store (`app/services/store.py`) and images travel as
> **base64** in the request/response — nothing is persisted. The service runs
> `--max-instances=1` so a single instance owns the whole async flow. This makes
> identity a pure Cloud Run service, homogeneous with rag-api / langchain-api,
> and improves privacy (no biometric data stored anywhere).

## 2. The model — important conceptual note

There is **no training** anywhere. `buffalo_l` is a **pretrained** InsightFace
pack (SCRFD detector + ArcFace ResNet-50 embeddings + 3D landmarks). The code
only does **inference**: extract a 512-d embedding per face and compare.

- Match logic: **cosine similarity** of the two embeddings; `match = similarity > 0.35`.
- The response field is called `distance` but stores a **similarity** (higher = more alike). Frontend shows it as `distance * 100` %.
- The model is baked into the Docker image at build time (a dedicated cached
  layer), so it is not re-downloaded on code pushes and cold-starts are fast.

If anyone says "reprocess/retrain the model" — there is nothing to retrain. What
used to feel slow was **dependency install** + first-run model download, both
now handled by Docker layer caching.

## 3. Request flow (asynchronous, in-memory)

```
Client (TryIdentity.tsx)
  │  converts selfie + ID to base64 (canvas, downscaled) — no upload anywhere
  ▼
POST /recognition/verify-id  {faceImageBase64, cardIdImageBase64, callback}
  │  → store.create_request(): in-memory doc, status="pending"
  ▼
POST /cron/verify-id   (triggered by the frontend right after)
  │  → run_cron_verify_id(): store.list_pending(), for each:
  │      1. decode_base64_to_cv2() both images
  │      2. compare_verify_faces() with InsightFace
  │      3. encode_cv2_to_base64() the 4 result images (data-URIs)
  │      4. POST result to the doc's callback URL (if provided)
  │      5. update status → completed / completed_with_errors / failed
  ▼
GET /recognition/get/{id}   (frontend polls every 3s until terminal status)
      → base64 INPUT images are redacted in the response (kept out of the log)
```

Status lifecycle: `pending → started → partially_completed → completed`
(`failed` / `completed_with_errors` on problems).

Result `output` contains: `result_match` (bool), `distance` (similarity), and 4
base64 data-URIs: `FaceImageCV2`, `CardImageCV2`, `FaceLandMarksImage`,
`CardLandMarksImage`. The frontend renders these directly in `<img src>`.

## 4. Data stores

- **None external.** The request queue is `app/services/store.py`: a process-local
  `dict` guarded by a `threading.Lock`, plus an `asyncio.Lock` (`cron_lock`) to
  serialize cron runs. `update_request` supports dotted keys (`data.output.x`) to
  mimic the previous Firestore update shape.
- State is **not durable** — it lives only for the instance's lifetime. That's
  intended for a demo (requests resolve in seconds; no history needed). Requires
  `--max-instances=1` so enqueue / process / poll hit the same instance.

## 5. Auth to GCP / credentials

There is **no Firebase key and no GCP Secret Manager secret** anymore. The only
credential is the CI/CD one:

- **`GCP_SA_KEY`** — a **GitHub Actions** secret (not in GCP). JSON key for the
  `github-deployer` SA that lets CI/CD build + deploy. Set via `gh secret set`
  (see README → Deployment). `key.json` / `gcp-sa-key.json` are gitignored.

## 6. Security posture

`app/utils/security.py` centralizes two protections:

- **Anti-SSRF** (`validate_image_url`): guards the legacy `read_image_from_url`
  helper (kept but no longer on the main path, since inputs are base64 now). If
  URL-based fetching is re-enabled, it checks scheme, host allowlist, and blocks
  private/loopback IPs.
- **Optional API key** (`require_api_key`): a router dependency. **No-op unless
  `API_KEY` env is set**, so the current keyless frontend keeps working. When set,
  requests must send `X-API-Key`. Note: a key in a public frontend is not secret —
  it's rate-limiting hygiene, not real auth.

CORS is restricted (`main.py`) to robles.ai + localhost, extendable via
`ALLOWED_ORIGINS`. Do **not** revert to `allow_origins=["*"]` with credentials.

## 7. Cron locking

`/cron/verify-id` serializes with the in-process `store.cron_lock`
(`asyncio.Lock`). If a run is already in progress it returns
`"Task already running."`. With `--max-instances=1` this single lock is enough —
no distributed lock needed (the old Firestore `cronLocks/taskLock` was removed).
There is no Cloud Scheduler; the cron is triggered by the frontend `fetch` after
creating a request.

## 8. Build & deploy

- **Dockerfile** has cache-friendly layers, in order:
  1. `requirements.txt` + `pip install`  (deps)
  2. pre-download InsightFace `buffalo_l` (model)
  3. `COPY . /app`                        (app code)
  Code-only pushes reuse layers 1–2, so builds stay fast.
- **CI/CD**: `.github/workflows/deploy.yml` runs on push to `main` → Cloud Build
  builds the image (tags `:$GITHUB_SHA` and `:latest`) → `gcloud run deploy`.
  Requires the `GCP_SA_KEY` GitHub secret (setup steps in README → Deployment).
  Until that secret exists, the workflow runs but fails at the "Authenticate to
  Google Cloud" step — expected.
- Deploy flags fixed by the workflow: `--memory=4Gi`, `--max-instances=1`,
  `--allow-unauthenticated`, `ALLOWED_ORIGINS` env. **No secrets, no bucket.**
- Note: unlike rag/langchain (Kaniko via `cloudbuild.yaml`), the identity
  **workflow** builds with a direct `--tag` — its image (InsightFace + baked
  buffalo_l) is large enough that pulling a cache is slower than a rebuild. The
  `cloudbuild.yaml` (Kaniko) still exists and is used by `update_docker.sh`.
- Manual scripts — shared set/names across the four API repos
  (`robles.ai-identity-api`, `robles.ai-rag-api`, `robles.ai-langchain-api`,
  `robles.ai-transcription-api`), each individualized to its project. Non-interactive, pass `--project` explicitly:
  - `deploy_fresh_gcp.sh` — full first-time provisioning: **creates the GCP
    project if missing + links billing**, enables APIs, Artifact Registry,
    runtime SA + `github-deployer` CI/CD SA + IAM, build, deploy, domain mapping.
  - `update_docker.sh` — code changes: rebuild the image (Kaniko cache), redeploy.
    Manual fallback to CI/CD.
  - `delete_all_gcp_resources.sh` — teardown (Cloud Run, repo, SAs, domain).

## 9. Conventions & gotchas

- **dlib / face_recognition are dead code.** The service migrated to InsightFace;
  all `face_recognition` usage is commented out. Note: `insightface` compiles a
  native wheel, so the Dockerfile installs `build-essential` + `g++`.
- **Emotions was removed** (2026-09-13). Endpoints `/emotions/*` used `py-feat`,
  which pulled `torch` + the full NVIDIA CUDA stack (~4 GB) into this CPU-only
  image. If revived, deploy it as a **separate** Cloud Run service — do NOT add
  it back here.
- `output` field `distance` = similarity, not distance (naming is misleading).
- Images are exchanged as base64. Input images are **redacted** in
  `GET /get/{id}` responses (`_serialize` in `recognition.py`); the frontend
  additionally truncates the base64 OUTPUT images in its on-screen log
  (`redactForLog`), while still rendering them in the result grid.
- Responses use envelopes from `utils/response.py`: `{success, code, message, data}`.
  Nesting the frontend relies on: response `data` = the request doc, so
  `data.data.status`, `data.data.success`, `data.data.data.output.*`.
- No formal test suite. Validate `utils/security.py` / `store.py` logic with a
  lightweight script + a venv with just `fastapi` (the full deps are heavy).

## 10. Related repos

- **Frontend**: `robles.ai` repo → `src/pages/TryIdentity.tsx` calls this API and
  sends images as base64. i18n keys under `try-identity` in
  `src/i18n/locales/{en,es}/translation.json`. (Note: `TryMedical.tsx` still uses
  Firebase Storage via `src/lib/firebaseConfig.ts` — a different demo, out of
  scope here.)
- **Sibling APIs**: `robles.ai-rag-api`, `robles.ai-langchain-api`,
  `robles.ai-transcription-api` — same GCP region, same deploy-script pattern,
  same `cloud-run-sa` / `github-deployer` SA naming.

## 12. GCP resource inventory (disaster recovery)

| Item | Value |
|------|-------|
| GCP project ID | `robles-ai-identity-project` |
| Region | `us-central1` |
| Billing | Pay-as-you-go on US billing account `01817C-24FBFE-66BA22`. Keep a budget + alerts (~$5/mo). |
| Public URL | `https://identity-api.robles.ai` |

**Cost expectation:** at rest ~$0/mo (Cloud Run scales to zero + free tier;
Artifact Registry a few cents for the image). Real cost only under sustained
traffic (capped by `--max-instances=1`).

**Enabled APIs (relevant):** `run`, `artifactregistry`, `cloudbuild`,
`secretmanager`, `iam`, `compute` (all `.googleapis.com`). No Firestore /
Firebase Storage APIs needed anymore.

**Cloud Run:** service `identity-server`, memory `4Gi`, `--max-instances=1`,
`--allow-unauthenticated`, env `ALLOWED_ORIGINS`, runs as
`cloud-run-sa@robles-ai-identity-project.iam.gserviceaccount.com`. Domain mapping
`identity-api.robles.ai → identity-server` (DNS: CNAME `identity-api →
ghs.googlehosted.com.`).

**Service accounts:**
| Email | Use |
|-------|-----|
| `cloud-run-sa@…` | Runtime SA (`run.invoker`) |
| `github-deployer@…` | CI/CD deployer (create per README → Deployment) |

**Secret Manager:** none required by the service anymore.

**Artifact Registry (us-central1):** `identity-api-repo` (identity-server image).

**TLS / domain:** `robles.ai` must stay **verified in Google Search Console**
(TXT `google-site-verification=...` in DNS) AND the CNAME must resolve, or the
managed certificate won't auto-renew. A lapsed verification once let the cert
expire (`ERR_CERT_DATE_INVALID`) — keep both DNS records in place.

## 13. Recreate from scratch (ordered runbook)

`deploy_fresh_gcp.sh` now bootstraps everything (including creating the GCP
project and linking billing). No Firebase setup, no manual console steps.

```bash
# 0. Authenticate gcloud (interactive, on your machine):
gcloud auth login

# 1. Provision everything (creates project + billing + APIs + repo + SAs +
#    build + deploy + domain mapping). Idempotent.
./deploy_fresh_gcp.sh

# 2. DNS: CNAME identity-api → ghs.googlehosted.com.  (+ keep the Search Console
#    TXT verification record). Cloud Run provisions the TLS cert automatically.

# 3. CI/CD: create the github-deployer key + GCP_SA_KEY secret (README → Deployment)
```

Verify: `curl https://identity-api.robles.ai/` after DNS + cert.

## 14. Maintenance (recommended)

- **Artifact Registry cleanup** — CI/CD pushes one image per commit; add a
  cleanup policy to keep only the N most recent:
  `gcloud artifacts repositories set-cleanup-policies identity-api-repo --location=us-central1 --policy=<policy.json>`
- **Billing budget** — Console → Billing → Budgets & alerts → ~$5/mo, alerts at 50/90/100%.

## 11. Change log (high level)

- **2026-09 (later)**: **Removed Firebase entirely** (Firestore + Storage). Async
  queue moved in-process (`store.py`), images exchanged as base64, `--max-instances=1`.
  Deleted `database_service.py`, `env.py`, `rotate_secret.sh`, `updateLocked.js`;
  dropped `google-cloud-firestore` + `firebase-admin` from requirements. Renamed
  GCP project `identityverifierapp → robles-ai-identity-project`; `deploy_fresh_gcp.sh`
  now bootstraps the project + billing. Now homogeneous with rag/langchain.
- **2026-09**: Removed emotions/py-feat; slimmed Dockerfile (no dlib), layer
  caching + baked model; added anti-SSRF + optional API key + tightened CORS;
  GitHub Actions CI/CD; docker-compose. Consolidated docs into README + AGENTS.
