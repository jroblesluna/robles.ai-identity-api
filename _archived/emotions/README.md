# Emotions module — archived

This code (endpoints `/emotions/get-image-emotions` and `/emotions/get-video-emotions`)
was **removed from the identity API** on 2026-09-13.

## Why it was separated

The emotions detection used `py-feat`, which pulls in `torch` plus the full
NVIDIA CUDA stack (~4 GB). This CPU-only identity service never used any of it,
so it bloated the Docker image and made builds very slow. The identity API only
needs InsightFace for face matching.

## What was removed

- `app/api/endpoints/emotions.py`  → moved here as `emotions.py`
- `app/services/emotions_service.py` → moved here as `emotions_service.py`
- The `emotions` import and router registration in `app/main.py`
- `py-feat` from `requirements.txt`

## How to re-enable (as its own service)

If emotions is needed, deploy it as a **separate** Cloud Run service with its
own repo/requirements (`py-feat`, `torch`), so it doesn't weigh down the
identity API. The code here depends on `app.services.database_service`,
`app.services.recognition_service` (read_image_from_url) and `app.utils.*`,
which would need to be copied or shared.
