import os
from dotenv import load_dotenv

load_dotenv()

BRAVE_API_KEY = os.getenv("BRAVE_API_KEY")

INPUT_FILE = "data/input/contacts.xlsx"
OUTPUT_FILE = "data/output/enriched_contacts.xlsx"
CHECKPOINT_FILE = "data/checkpoints/processed.json"
LOG_FILE = "logs/enrichment.log"

MAX_QUERIES = 5
MAX_EMAILS = 2
GENERIC_PREFIXES = ["info@", "support@", "admin@", "no-reply@"]
