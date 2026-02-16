"""Application entry point for NeuroLog."""

from __future__ import annotations

import sys

from PyQt6.QtWidgets import QApplication, QMessageBox

from neuro_log.api import CortexApiClient
from neuro_log.gui import NeuroLogMainWindow
from neuro_log.utils import build_cortex_config_from_env, configure_logging


def main() -> int:
    """Launch the NeuroLog GUI application."""
    configure_logging()

    app = QApplication(sys.argv)

    try:
        config = build_cortex_config_from_env()
    except Exception as exc:
        QMessageBox.critical(None, "Configuration Error", str(exc))
        return 1

    client = CortexApiClient(config)
    window = NeuroLogMainWindow(client)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
