# Deployment & Local Development

## Local development

1. Copy the env template and put your Firebase key in the project root:
   ```bash
   cp .env.example .env
   # place firebase_key.json in the project root (gitignored)
   ```
2. Run the server with Docker (matches the Cloud Run image):
   ```bash
   docker compose up --build
   ```
   API available at http://localhost:8080

   Or run without Docker (needs Python 3.10 + deps installed):
   ```bash
   pip install -r requirements.txt
   uvicorn app.main:app --host 0.0.0.0 --port 8080 --reload
   ```

3. Smoke test:
   ```bash
   curl http://localhost:8080/                       # {"message": "Hello, ..."}
   ```

## CI/CD — automatic deploy on push to `main`

Every push to `main` triggers `.github/workflows/deploy.yml`, which builds the
image with Cloud Build and deploys it to Cloud Run. No manual `gcloud` needed.

### One-time setup (required for the workflow to work)

The workflow authenticates to GCP with a service-account key stored as a GitHub
secret. Create it once:

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
> secure. Consider migrating to **Workload Identity Federation** (keyless) later;
> swap the `credentials_json` input for `workload_identity_provider`.

### Build caching — code pushes don't reinstall deps or re-download the model

The Dockerfile is layered so that day-to-day code changes build fast:

1. `COPY requirements.txt` + `pip install`  → dependency layer
2. Pre-download InsightFace `buffalo_l`      → model layer
3. `COPY . /app`                             → application layer

Layers 1 and 2 are only rebuilt when `requirements.txt` changes. When you push
**code-only** changes, Cloud Build reuses the cached dependency and model layers
and only rebuilds the small app layer. The pretrained model is baked into the
image at build time, so it is never re-downloaded on push and production
cold-starts are fast.

> Note: Cloud Build reuses cache across builds via the `:latest` tag it also
> pushes. The first build (or any change to `requirements.txt`) is slow because
> it installs everything and downloads the model once; subsequent code pushes
> are quick.

### What the deploy preserves

- Secret mounted at `/secrets/FIREBASE_KEY` pinned to version `:1` (avoids the
  Secret Manager access cost from `latest`).
- `--max-instances=2` to cap compute cost.
- `STORAGE_BUCKET_NAME` and `ALLOWED_ORIGINS` env vars.

To enable API-key auth in production, add an `API_KEY` value to the
`--set-env-vars` list in the workflow (and send it from the frontend).

## Legacy scripts

`deploy_fresh_gcp.sh` (full first-time provisioning) and `update_docker.sh`
(manual redeploy) still work for manual/bootstrap use, but day-to-day deploys
now go through GitHub Actions.
