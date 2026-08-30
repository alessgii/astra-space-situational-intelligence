"""Global configuration: env loading, constants, logger, and paths."""

import logging
from pathlib import Path

import httpx
from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"

# Load .env before anything else reads os.getenv()
load_dotenv(BASE_DIR / ".env")

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("astra")

# ---------------------------------------------------------------------------
# External-service timeouts
# ---------------------------------------------------------------------------
# 12 s was too tight for NASA/JPL on a slow day (especially with DEMO_KEY).
NASA_HTTP_TIMEOUT = httpx.Timeout(20.0, connect=8.0)
WATSONX_TIMEOUT_SECONDS = 45.0
