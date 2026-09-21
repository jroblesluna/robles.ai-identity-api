#!/bin/bash
set -e

# Poda del Artifact Registry — homologado en los cuatro repos de APIs.
#
# Hace dos cosas, ambas idempotentes:
#   1. Registra la cleanup policy del repositorio (conserva las $KEEP versiones
#      más recientes de cada paquete y borra el resto pasados 3 días). Artifact
#      Registry la evalúa en su propio ciclo (~diario), así que queda como red
#      de seguridad aunque nadie vuelva a correr este script.
#   2. Poda AHORA: borra las versiones que exceden las $KEEP más recientes, para
#      que cada despliegue deje el registro limpio sin esperar ese ciclo.
#
# Se invoca desde deploy_fresh_gcp.sh, update_docker.sh y el workflow de CI/CD.
# También a mano:  bash prune_registry.sh      (o  KEEP=5 bash prune_registry.sh)
#
# Ojo: conserva las $KEEP versiones más recientes por paquete. Si hiciste
# rollback a una revisión de Cloud Run más antigua que eso, su imagen entraría
# en la poda y esa revisión no podría escalar. Subí KEEP si necesitás más
# ventana. Los borrados nunca abortan el despliegue: solo avisan.

PROJECT_ID="${PROJECT_ID:-robles-ai-identity-project}"
REGION="${REGION:-us-central1}"
REPO_NAME="${REPO_NAME:-identity-api-repo}"
KEEP="${KEEP:-3}"

REPO_PATH="$REGION-docker.pkg.dev/$PROJECT_ID/$REPO_NAME"
echo "🧹 Podando $REPO_PATH (se conservan las $KEEP versiones más recientes)..."

# ── 1. Cleanup policy (red de seguridad que aplica Artifact Registry) ────────
POLICY_FILE="$(mktemp)"
trap 'rm -f "$POLICY_FILE"' EXIT
cat > "$POLICY_FILE" <<POLICY
[
  {"name":"conservar-recientes","action":{"type":"Keep"},
   "mostRecentVersions":{"keepCount":$KEEP}},
  {"name":"borrar-antiguas","action":{"type":"Delete"},
   "condition":{"olderThan":"3d"}}
]
POLICY
if gcloud artifacts repositories set-cleanup-policies "$REPO_NAME" \
     --project="$PROJECT_ID" --location="$REGION" --policy="$POLICY_FILE" > /dev/null 2>&1; then
  echo "   ✅ cleanup policy registrada (keep=$KEEP, delete >3d)"
else
  echo "   ⚠️  no se pudo registrar la cleanup policy (¿permiso artifactregistry.repositories.update?)"
fi

# ── 2. Poda inmediata ───────────────────────────────────────────────────────
gcloud artifacts docker images list "$REPO_PATH" --project="$PROJECT_ID" \
  --format="value(package)" 2>/dev/null | sort -u | while IFS= read -r PKG; do
  [ -z "$PKG" ] && continue
  OLD=$(gcloud artifacts docker images list "$PKG" --project="$PROJECT_ID" \
          --sort-by="~CREATE_TIME" --format="value(version)" 2>/dev/null | tail -n +$((KEEP + 1)))
  if [ -z "$OLD" ]; then
    echo "   • $(basename "$PKG"): nada que podar"
    continue
  fi
  echo "$OLD" | while IFS= read -r DIGEST; do
    [ -z "$DIGEST" ] && continue
    if gcloud artifacts docker images delete "$PKG@$DIGEST" \
         --project="$PROJECT_ID" --delete-tags --quiet > /dev/null 2>&1; then
      echo "   🗑  $(basename "$PKG")@${DIGEST:0:19}…"
    else
      echo "   ⚠️  no se pudo borrar $(basename "$PKG")@${DIGEST:0:19}…"
    fi
  done
done

echo "✅ Registry podado."
