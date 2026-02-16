"""General utility helpers for the NeuroLog application."""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass

from neuro_log.api import CortexConfig


def configure_logging() -> None:
    """Initialize process-wide logging configuration."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )


@dataclass(slots=True)
class Credentials:
    """Container for Cortex client credentials."""

    client_id: str
    client_secret: str


def load_credentials_from_env() -> Credentials:
    """Load Cortex credentials from environment variables.

    Required environment variables:
    - EMOTIV_CLIENT_ID
    - EMOTIV_CLIENT_SECRET
    """
    client_id = os.getenv("EMOTIV_CLIENT_ID", "").strip()
    client_secret = os.getenv("EMOTIV_CLIENT_SECRET", "").strip()
    if not client_id or not client_secret:
        raise RuntimeError(
            "Missing credentials. Set EMOTIV_CLIENT_ID and EMOTIV_CLIENT_SECRET environment variables."
        )
    return Credentials(client_id=client_id, client_secret=client_secret)


def build_cortex_config_from_env() -> CortexConfig:
    """Construct Cortex configuration from environment variables."""
    creds = load_credentials_from_env()
    ssl_verify = os.getenv("EMOTIV_SSL_VERIFY", "0") == "1"
    return CortexConfig(client_id=creds.client_id, client_secret=creds.client_secret, ssl_verify=ssl_verify)


def sanitize_filename(value: str) -> str:
    """Convert arbitrary text into a filesystem-safe filename chunk."""
    value = value.strip().replace(" ", "_")
    value = re.sub(r"[^a-zA-Z0-9_.-]", "", value)
    return value or "recording"
