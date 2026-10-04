"""The Creature World server code. Importing anything from this package loads .env first."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent   # the project folder


def load_env():
    """Read KEY=value lines from .env without overriding real environment variables."""
    env = ROOT / ".env"
    if not env.exists():
        return
    for line in env.read_text(encoding="utf-8").splitlines():
        key, sep, value = line.partition("=")
        if sep and not line.lstrip().startswith("#"):
            os.environ.setdefault(key.strip(), value.strip().strip('"\''))


load_env()
