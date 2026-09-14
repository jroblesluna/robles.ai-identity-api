# INFRASTRUCTURE.md — GCP resources & disaster-recovery runbook

Complete inventory of the Google Cloud resources this service depends on, and
the exact order to recreate everything from scratch. Verified against the live
project on 2026-09-13.

> The legacy `deploy_fresh_gcp.sh` automates part of this but assumes APIs,
> Firestore and the Storage bucket already exist. This document fills those gaps.

---

## Project

| Item | Value |
|------|-------|
| GCP project ID | `identityverifierapp` |
| Region | `us-central1` |
| Billing | **Blaze (pay-as-you-go)** — required for Cloud Storage. Currently on the US billing account `01817C-24FBFE-66BA22`. Keep a budget + alerts (~$5/mo). |
| Public URL | `https://identity-api.robles.ai` |

## Cost expectation

At rest the project costs **~$0/month**: Cloud Run scales to zero and stays in
the free tier; Firestore/Storage are within free quotas; Secret Manager is
minimal (single secret, pinned version); Artifact Registry is a few cents for
the image. Real cost only appears under sustained traffic (capped by
`--max-instances=2`). **Set a billing budget with alerts** — Blaze is
pay-as-you-go, not free-forever.

CI/CD adds Cloud Build usage (free tier: 120 build-min/day — not exceeded here)
and stores one image per commit in Artifact Registry (see cleanup policy below).

---

## Resource inventory (live)

### Enabled APIs (relevant)
```
run.googleapis.com                 firestore.googleapis.com
secretmanager.googleapis.com       artifactregistry.googleapis.com
cloudbuild.googleapis.com          firebasestorage.googleapis.com
storage.googleapis.com             iam.googleapis.com
firebase.googleapis.com
```

### Cloud Run
- Service: **`identity-server`** (region `us-central1`)
- URL: `https://identity-server-3aji2fngoq-uc.a.run.app`
- Config: memory `4Gi`, `--max-instances=2`, `--allow-unauthenticated`
- Env: `STORAGE_BUCKET_NAME`, `ALLOWED_ORIGINS`
- Secret mount: `/secrets/FIREBASE_KEY` ← `FIREBASE_KEY:1`
- Runs as service account `cloud-run-sa@identityverifierapp.iam.gserviceaccount.com`
- Domain mapping: `identity-api.robles.ai` → `identity-server`
  (DNS: CNAME `identity-api` → `ghs.googlehosted.com.` in the robles.ai DNS provider)

### Service accounts
| Email | Role/use |
|-------|----------|
| `cloud-run-sa@identityverifierapp.iam.gserviceaccount.com` | Runtime SA for Cloud Run; has `secretmanager.secretAccessor` on FIREBASE_KEY and `run.invoker` |
| `firebase-adminsdk-fbsvc@identityverifierapp.iam.gserviceaccount.com` | Firebase Admin SDK SA — source of the `firebase_key.json` credential |
| `105527807738-compute@developer.gserviceaccount.com` | Default compute SA |
| `github-deployer@…` (to create) | CI/CD deployer — see DEPLOYMENT.md |

### Secret Manager
- **`FIREBASE_KEY`** — the only secret. Holds the Firebase service-account JSON
  (Firestore + Storage access). Cloud Run mounts version **`:1`** (do not use
  `latest` — it caused ~$3.48/mo in access charges).
- The GitHub `GCP_SA_KEY` secret is a **GitHub** secret (CI/CD auth), NOT a GCP
  Secret Manager secret. Different thing, different place.

### Firestore
- Native mode. Collections:
  - `request` — one document per verification (status, input, output)
  - `cronLocks/taskLock` — lock doc for `/cron/verify-id`

### Firebase Storage
- Bucket: **`identityverifierapp.firebasestorage.app`**
- Prefixes: `demo-uploads/` (frontend uploads), `images/` (processed results)
- ⚠️ No lifecycle rule yet → objects accumulate. Add expiration to avoid growth
  and a repeat of the past `storage/quota-exceeded` incident.

### Artifact Registry (Docker repos in `us-central1`)
| Repo | Used by |
|------|---------|
| `my-repo` | **identity-server** image (this service) |
| `rag-api-repo` | RAG API (other project/service) |
| `cloud-run-source-deploy` | leftover from console deploys (mostly empty) |

---

## Recreate from scratch (ordered runbook)

Run in this order in a fresh/empty project. Requires `gcloud` + Blaze billing
linked and the Firebase Admin `firebase_key.json` available.

```bash
PROJECT_ID=identityverifierapp
REGION=us-central1

# 1. Enable APIs
gcloud services enable \
  run.googleapis.com firestore.googleapis.com secretmanager.googleapis.com \
  artifactregistry.googleapis.com cloudbuild.googleapis.com \
  firebasestorage.googleapis.com storage.googleapis.com iam.googleapis.com \
  --project=$PROJECT_ID

# 2. Firestore (Native mode) — one-time
gcloud firestore databases create --location=$REGION --project=$PROJECT_ID

# 3. Firebase Storage bucket — via Firebase console (Storage → Get started),
#    requires Blaze. Bucket name: identityverifierapp.firebasestorage.app

# 4. Firebase Admin key (firebase_key.json)
#    Firebase console → Project settings → Service accounts → Generate new
#    private key. Save as firebase_key.json in the project root (gitignored).

# 5. Everything else (Artifact Registry repo, cloud-run-sa, secret, IAM,
#    Cloud Run deploy, domain mapping) is handled by:
./deploy_fresh_gcp.sh

# 6. DNS: in the robles.ai DNS provider create:
#    CNAME  identity-api  →  ghs.googlehosted.com.
#    Wait for propagation; Cloud Run provisions the TLS cert automatically.

# 7. CI/CD: create github-deployer SA + GCP_SA_KEY secret (see DEPLOYMENT.md)
```

After step 5, verify:
```bash
gcloud run services describe identity-server --region=$REGION --project=$PROJECT_ID \
  --format="value(status.url)"
curl https://identity-api.robles.ai/    # after DNS + cert
```

---

## Maintenance

### Artifact Registry cleanup (recommended)
CI/CD pushes one image per commit (`:$GITHUB_SHA`). Add a cleanup policy so old
images don't accumulate:
```bash
gcloud artifacts repositories set-cleanup-policies my-repo \
  --project=identityverifierapp --location=us-central1 \
  --policy=<policy.json>   # keep e.g. the 5 most recent versions
```

### Storage lifecycle (recommended)
Expire demo/processed images after N days:
```bash
gcloud storage buckets update gs://identityverifierapp.firebasestorage.app \
  --lifecycle-file=lifecycle.json   # e.g. delete objects older than 7 days
```

### Billing budget (recommended)
Console → Billing → Budgets & alerts → budget ~$5/mo with alerts at 50/90/100%.
