FROM python:3.10-slim

# Runtime libraries needed by OpenCV (headless) + general TLS, plus a C++
# toolchain (build-essential/g++) required to build the insightface wheel from
# source during pip install. dlib/face_recognition were removed (migrated to
# InsightFace), but insightface itself still compiles a native extension.
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    g++ \
    libglib2.0-0 \
    libgl1 \
    libgomp1 \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
ENV PYTHONPATH=/app \
    PYTHONUNBUFFERED=1

# ── Dependency layer (cached) ────────────────────────────────────────────────
# Copy ONLY requirements first and install. This layer is rebuilt only when
# requirements.txt changes — so pushing code changes reuses the cached deps
# and the CI/CD build stays fast (no reinstalling torch/insightface each time).
COPY requirements.txt .
RUN pip install --upgrade pip setuptools wheel \
 && pip install --no-cache-dir -r requirements.txt

# ── Model layer (cached) ─────────────────────────────────────────────────────
# Pre-download the InsightFace "buffalo_l" model at build time so it is baked
# into the image. This layer only rebuilds when requirements change, so code
# pushes never re-download the model, and production cold-starts are fast
# (no first-request download). The model is pretrained — nothing is trained here.
RUN python -c "from insightface.app import FaceAnalysis; \
FaceAnalysis(name='buffalo_l', providers=['CPUExecutionProvider']).prepare(ctx_id=0, det_size=(640, 640))"

# ── Application layer ────────────────────────────────────────────────────────
# Copied after deps so code edits don't invalidate the dependency cache.
COPY . /app

EXPOSE 8080
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
