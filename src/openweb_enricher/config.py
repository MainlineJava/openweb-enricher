





import os
from dotenv import load_dotenv

load_dotenv()

# Project root: directory containing this config.py, up 2 levels (src/openweb_enricher/ -> project root)
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))

BRAVE_API_KEY = os.getenv("BRAVE_API_KEY")

INPUT_FILE = os.path.join(PROJECT_ROOT, "data", "input", "contacts.xlsx")
OUTPUT_FILE = os.path.join(PROJECT_ROOT, "data", "output", "enriched_contacts.xlsx")
CHECKPOINT_FILE = os.path.join(PROJECT_ROOT, "data", "checkpoints", "processed.json")
LOG_FILE = os.path.join(PROJECT_ROOT, "logs", "enrichment.log")

MAX_QUERIES = 5
MAX_EMAILS = 2
GENERIC_PREFIXES = ["info@", "support@", "admin@", "no-reply@"]

# New settings
SCRAPE_PAGES = True  # default; UI can override per-run
JOBS_DIR = os.path.join(PROJECT_ROOT, "data", "jobs")  # per-run persisted outputs/logs

# Optional basic auth for the local web UI (set in .env to enable)
BASIC_AUTH_USER = os.getenv("BASIC_AUTH_USER")
BASIC_AUTH_PASS = os.getenv("BASIC_AUTH_PASS")
