#!/bin/bash
set -e

# ──────── VARIABLES DEL PROYECTO ────────
PROJECT_ID="robles-ai-identity-project"
REGION="us-central1"
SERVICE_NAME="identity-server"
REPO_NAME="my-repo"
IMAGE_NAME="identity-server"
TAG="latest"
CLOUD_RUN_SA="cloud-run-sa"
CLOUD_RUN_SA_EMAIL="$CLOUD_RUN_SA@$PROJECT_ID.iam.gserviceaccount.com"
DOMAIN="identity-api.robles.ai"
# Cuenta de facturación a vincular al proyecto (necesaria para habilitar APIs
# de pago como Cloud Run / Cloud Build). Puede sobreescribirse por entorno.
BILLING_ACCOUNT_ID="${BILLING_ACCOUNT_ID:-01817C-24FBFE-66BA22}"

echo "📁 Proyecto: $PROJECT_ID"
echo "🧭 Región: $REGION"
echo "📦 Repositorio: $REPO_NAME"
echo "⚙️  Imagen: $IMAGE_NAME:$TAG"
echo "👤 Cuenta de servicio: $CLOUD_RUN_SA_EMAIL"
echo "───────────────────────────────────────────────"

# ──────── BOOTSTRAP DEL PROYECTO GCP (crear si no existe) ────────
# deploy_fresh_gcp.sh crea TODOS los recursos desde cero, incluido el proyecto.
# Si el proyecto no existe, lo crea y lo vincula a la cuenta de facturación.
if gcloud projects describe "$PROJECT_ID" > /dev/null 2>&1; then
  echo "🟢 Proyecto '$PROJECT_ID' ya existe."
else
  echo "🆕 Creando proyecto '$PROJECT_ID'..."
  gcloud projects create "$PROJECT_ID" --name="$PROJECT_ID"
fi
# Vincular facturación (idempotente). Sin billing, enable de APIs de pago falla.
if [ -n "$BILLING_ACCOUNT_ID" ]; then
  CURRENT_BILLING="$(gcloud billing projects describe "$PROJECT_ID" \
    --format='value(billingAccountName)' 2>/dev/null || true)"
  if [ -z "$CURRENT_BILLING" ]; then
    echo "💳 Vinculando facturación '$BILLING_ACCOUNT_ID' al proyecto..."
    gcloud billing projects link "$PROJECT_ID" --billing-account="$BILLING_ACCOUNT_ID"
  else
    echo "🟢 Facturación ya vinculada."
  fi
fi

# ──────── CONFIGURAR PROYECTO ────────
echo "🛠️ Configurando proyecto en gcloud..."
gcloud config set project "$PROJECT_ID"

# ──────── HABILITAR APIS ────────
# El servicio es ahora puro Cloud Run (sin Firebase). Estado async en memoria
# (--max-instances=1) e imágenes intercambiadas como base64 — sin bucket ni
# Firestore. Solo se necesitan las APIs de build + run + registry + secrets.
SERVICES=(
  artifactregistry.googleapis.com
  cloudbuild.googleapis.com
  run.googleapis.com
  secretmanager.googleapis.com
  iam.googleapis.com
  compute.googleapis.com
)
echo "⚙️ Habilitando APIs necesarias..."
for SERVICE in "${SERVICES[@]}"; do
  if gcloud services list --enabled --project="$PROJECT_ID" | grep -q "$SERVICE"; then
    echo "✅ $SERVICE ya está habilitado."
  else
    echo "🔧 Habilitando $SERVICE..."
    gcloud services enable "$SERVICE" --project="$PROJECT_ID"
  fi
done

# ──────── REPOSITORIO ARTIFACT REGISTRY ────────
echo "🔍 Verificando repositorio '$REPO_NAME'..."
if gcloud artifacts repositories list --location="$REGION" --project="$PROJECT_ID" --format="value(name)" 2>/dev/null | grep -q "^$REPO_NAME$"; then
  echo "🟢 Repositorio '$REPO_NAME' ya existe."
else
  echo "📦 [CREANDO] Repositorio '$REPO_NAME'..."
  gcloud artifacts repositories create "$REPO_NAME" \
     --repository-format=docker \
     --location="$REGION" \
     --project="$PROJECT_ID" \
     --description="Docker repo for $SERVICE_NAME"
fi

# ──────── CONSTRUIR IMAGEN DOCKER ────────
echo "🔧 Construyendo imagen Docker y subiendo a Artifact Registry..."
gcloud builds submit --config cloudbuild.yaml --project="$PROJECT_ID" .

# ──────── CUENTA DE SERVICIO ────────
echo "👤 Verificando cuenta de servicio '$CLOUD_RUN_SA_EMAIL'..."
if ! gcloud iam service-accounts describe "$CLOUD_RUN_SA_EMAIL" --project="$PROJECT_ID" > /dev/null 2>&1; then
  echo "🆕 [CREANDO] Cuenta de servicio '$CLOUD_RUN_SA'..."
  gcloud iam service-accounts create "$CLOUD_RUN_SA" --project="$PROJECT_ID" --display-name="Cloud Run Service Account"
  # A newly created SA takes a few seconds to propagate in IAM; without waiting,
  # the first add-iam-policy-binding can fail with "Service account ... does not
  # exist". Poll until it's visible before assigning roles.
  echo "⏳ Esperando propagación de la SA '$CLOUD_RUN_SA_EMAIL'..."
  for _ in $(seq 1 12); do
    gcloud iam service-accounts describe "$CLOUD_RUN_SA_EMAIL" --project="$PROJECT_ID" > /dev/null 2>&1 && break
    sleep 5
  done
  sleep 8
else
  echo "🟢 Cuenta de servicio '$CLOUD_RUN_SA' ya existe."
fi

# ──────── PERMISOS PARA CLOUD RUN ────────
echo "🔒 Verificando permisos en Cloud Run..."
gcloud projects add-iam-policy-binding "$PROJECT_ID" \
  --member="serviceAccount:$CLOUD_RUN_SA_EMAIL" \
  --role="roles/run.invoker" \
  --quiet || true

# ──────── SERVICE ACCOUNT DE CI/CD (GitHub Actions) ────────
# Este script crea los recursos GCP UNA VEZ. Luego los despliegues son por CI/CD
# (push a main → .github/workflows/deploy.yml). SA de CI/CD con permisos mínimos.
CI_SA="github-deployer"
CI_SA_EMAIL="$CI_SA@$PROJECT_ID.iam.gserviceaccount.com"
echo "👤 Verificando cuenta de servicio de CI/CD '$CI_SA_EMAIL'..."
if ! gcloud iam service-accounts describe "$CI_SA_EMAIL" --project="$PROJECT_ID" > /dev/null 2>&1; then
  gcloud iam service-accounts create "$CI_SA" --project="$PROJECT_ID" \
    --display-name="GitHub Actions deployer"
  # A newly created SA takes a few seconds to propagate in IAM. Without this
  # wait, the first add-iam-policy-binding can fail with "Service account ...
  # does not exist". Poll until it's visible before assigning roles.
  echo "⏳ Esperando propagación de la SA '$CI_SA_EMAIL'..."
  for _ in $(seq 1 12); do
    gcloud iam service-accounts describe "$CI_SA_EMAIL" --project="$PROJECT_ID" > /dev/null 2>&1 && break
    sleep 5
  done
  sleep 8
fi
for ROLE in roles/run.admin roles/artifactregistry.writer roles/secretmanager.secretAccessor; do
  gcloud projects add-iam-policy-binding "$PROJECT_ID" \
    --member="serviceAccount:$CI_SA_EMAIL" --role="$ROLE" --quiet || true
done
gcloud iam service-accounts add-iam-policy-binding "$CLOUD_RUN_SA_EMAIL" \
  --project="$PROJECT_ID" \
  --member="serviceAccount:$CI_SA_EMAIL" \
  --role="roles/iam.serviceAccountUser" --quiet || true

echo ""
echo "🔑 SIGUIENTE PASO MANUAL (una sola vez) para activar el CI/CD:"
echo "   1) gcloud iam service-accounts keys create gcp-sa-key.json \\"
echo "        --iam-account=$CI_SA_EMAIL --project=$PROJECT_ID"
echo "   2) gh secret set GCP_SA_KEY --repo jroblesluna/robles.ai-identity-api < gcp-sa-key.json && rm gcp-sa-key.json"
echo "   Tras esto, cada push a main desplegará automáticamente vía Actions."
echo ""

# ──────── DESPLIEGUE EN CLOUD RUN ────────
# --max-instances=1: el estado async del flujo vive en memoria del proceso
# (app/services/store.py). Una sola instancia garantiza que encolar (verify-id),
# procesar (cron) y consultar (get/{id}) toquen el mismo proceso. Sin Firebase.
echo "🚀 Desplegando servicio en Cloud Run..."
gcloud run deploy "$SERVICE_NAME" \
  --project="$PROJECT_ID" \
  --image="$REGION-docker.pkg.dev/$PROJECT_ID/$REPO_NAME/$IMAGE_NAME:$TAG" \
  --region="$REGION" \
  --platform=managed \
  --allow-unauthenticated \
  --service-account="$CLOUD_RUN_SA_EMAIL" \
  --memory=4Gi \
  --max-instances=1 \
  --set-env-vars="^|^ALLOWED_ORIGINS=https://robles.ai,https://www.robles.ai"

echo "🌐 Configurando domain mapping $DOMAIN → $SERVICE_NAME..."
gcloud beta run domain-mappings create \
  --domain="$DOMAIN" \
  --service="$SERVICE_NAME" \
  --region="$REGION" \
  --project="$PROJECT_ID" \
  --platform=managed || echo "ℹ️ Ya está configurado."

echo -e "\n🎉 ✅ ¡Despliegue exitoso de '$SERVICE_NAME' en Cloud Run!"
