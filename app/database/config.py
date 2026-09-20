"""Configuration helpers.

Firebase (Firestore + Storage) has been removed. The identity service is now a
stateless demo: the async request queue lives in-process (see
app/services/store.py) and images are exchanged as base64 (no external storage).

This module only loads the local .env in non-production environments.
"""

import os

# Load .env only in local/dev; in production the env is provided by Cloud Run.
if os.getenv("ENV", "local") != "production":
    try:
        from dotenv import load_dotenv

        load_dotenv()
    except Exception:
        pass
