"""Application entrypoint for NeuroLog."""

from __future__ import annotations

import sys

from PyQt6.QtWidgets import QApplication

from neuro_log.api import CortexClient
from neuro_log.gui import NeuroLogWindow
from neuro_log.recorder import EEGRecorder
from neuro_log.utils import configure_logging, load_credentials


def main() -> int:
    """Start the NeuroLog GUI application."""
    configure_logging()
    creds = load_credentials()

    app = QApplication(sys.argv)
    api_client = CortexClient(client_id=creds.client_id, client_secret=creds.client_secret)
    recorder = EEGRecorder()
    window = NeuroLogWindow(api_client=api_client, recorder=recorder)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
