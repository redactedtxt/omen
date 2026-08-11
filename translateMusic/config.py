"""Central configuration for OMEN.

Secrets live in a .env file next to this module (see .env.example).
Nothing in this project should ever hardcode a key again.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
GENIUS_ACCESS_TOKEN = os.getenv("GENIUS_ACCESS_TOKEN", "")

OPENAI_MODEL = os.getenv("OMEN_OPENAI_MODEL", "gpt-4o-mini")


def missing_keys() -> list[str]:
    """Return the names of any required keys that are not configured."""
    missing = []
    if not OPENAI_API_KEY:
        missing.append("OPENAI_API_KEY")
    if not GENIUS_ACCESS_TOKEN:
        missing.append("GENIUS_ACCESS_TOKEN")
    return missing
