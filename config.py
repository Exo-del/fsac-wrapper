"""Central configuration for the FSAC local wrapper."""

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent

FSAC_ORIGIN = os.getenv("FSAC_ORIGIN", "https://fsac.univh2c.ma").rstrip("/")
FSAC_WS = f"{FSAC_ORIGIN}/app/Controllers/WS.php"
FSAC_GLOBAL_JSON = f"{FSAC_ORIGIN}/Docs/static_pages/global.json"
FSAC_HOME = f"{FSAC_ORIGIN}/front/index.html"
FSAC_FRONT = f"{FSAC_ORIGIN}/front/"

# Hosts allowed through the media proxy (hotlink safety)
PROXY_ALLOWED_HOSTS = {
    FSAC_ORIGIN.split("//", 1)[-1],
    "www.fsac.ac.ma",
    "fsac.ac.ma",
}

CACHE_TTL = int(os.getenv("CACHE_TTL", "60"))
HOME_CACHE_TTL = int(os.getenv("HOME_CACHE_TTL", "600"))
REQUEST_TIMEOUT = float(os.getenv("REQUEST_TIMEOUT", "12"))
ENABLE_PROXY = os.getenv("ENABLE_PROXY", "true").lower() == "true"

USER_AGENT = (
    "FSAC-LocalWrapper/1.0 (+localhost; hobby project; polite fetch; contact: local)"
)

DEFAULT_PAGE_SIZE = 40
DEFAULT_RECRUT_SIZE = 30
