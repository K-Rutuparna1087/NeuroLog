"""Utility helpers for NeuroLog."""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

LOGGER = logging.getLogger("neuro_log")


@dataclass(slots=True)
class CortexCredentials:
    """Container for Emotiv Cortex API credentials."""

    client_id: str
    client_secret: str


@dataclass(slots=True)
class SessionMetadata:
    """User-provided metadata associated with a recording session."""

    subject: str
    experiment_name: str
    notes: str


def configure_logging(level: int = logging.INFO) -> None:
    """Configure module-level logging format and level."""
    logging.basicConfig(
        level=level,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )


def now_utc_iso() -> str:
    """Return the current UTC timestamp in ISO-8601 format."""
    return datetime.now(tz=timezone.utc).isoformat()


def load_credentials() -> CortexCredentials:
    """Load Cortex credentials from environment variables.

    Raises:
        RuntimeError: If required variables are missing.
    """

    client_id = os.getenv("CORTEX_CLIENT_ID", "").strip()
    client_secret = os.getenv("CORTEX_CLIENT_SECRET", "").strip()

    if not client_id or not client_secret:
        raise RuntimeError(
            "Missing Cortex credentials. Set CORTEX_CLIENT_ID and "
            "CORTEX_CLIENT_SECRET environment variables."
        )

    return CortexCredentials(client_id=client_id, client_secret=client_secret)


def ensure_output_dir(base_dir: str | Path = "recordings") -> Path:
    """Create and return the output directory for recordings."""

    path = Path(base_dir)
    path.mkdir(parents=True, exist_ok=True)
    return path


def dump_json(path: Path, data: dict[str, Any]) -> None:
    """Write dictionary data as pretty JSON to a file."""

    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
