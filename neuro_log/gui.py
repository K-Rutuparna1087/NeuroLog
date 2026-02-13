"""PyQt6 GUI for real-time EEG visualization and recording controls."""

from __future__ import annotations

import queue
import time
from collections import deque
from pathlib import Path

import numpy as np
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import (
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QStatusBar,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from neuro_log.api import CortexClient
from neuro_log.recorder import EEGRecorder
from neuro_log.utils import SessionMetadata, ensure_output_dir, now_utc_iso


class NeuroLogWindow(QMainWindow):
    """Main NeuroLog window integrating stream management, plotting, and export."""

    def __init__(self, api_client: CortexClient, recorder: EEGRecorder) -> None:
        super().__init__()
        self.api_client = api_client
        self.recorder = recorder

        self.setWindowTitle("NeuroLog - Emotiv EEG Recorder")
        self.resize(1100, 720)

        self._sample_queue: queue.Queue[dict] = queue.Queue()
        self._plot_buffer: deque[list[float]] = deque(maxlen=500)
        self._timestamps: deque[float] = deque(maxlen=500)
        self._channel_labels: list[str] = []
        self._sample_rate_hz: float = 128.0

        self._init_widgets()
        self._bind_callbacks()

        self.refresh_timer = QTimer(self)
        self.refresh_timer.timeout.connect(self._process_incoming_samples)
        self.refresh_timer.start(40)

    def _init_widgets(self) -> None:
        central = QWidget()
        layout = QGridLayout(central)

        self.status_connection = QLabel("Disconnected")
        self.status_sample_rate = QLabel("Sample rate: -- Hz")
        self.status_battery = QLabel("Battery: --%")

        status_box = QGroupBox("Device Status")
        status_layout = QFormLayout(status_box)
        status_layout.addRow("Connection", self.status_connection)
        status_layout.addRow("Sampling", self.status_sample_rate)
        status_layout.addRow("Battery", self.status_battery)

        self.subject_input = QLineEdit()
        self.experiment_input = QLineEdit()
        self.notes_input = QTextEdit()
        self.notes_input.setPlaceholderText("Session notes...")

        metadata_box = QGroupBox("Session Metadata")
        metadata_layout = QFormLayout(metadata_box)
        metadata_layout.addRow("Subject", self.subject_input)
        metadata_layout.addRow("Experiment", self.experiment_input)
        metadata_layout.addRow("Notes", self.notes_input)

        self.marker_input = QLineEdit()
        self.marker_input.setPlaceholderText("e.g., stimulus_onset")
        self.marker_button = QPushButton("Add Marker")

        marker_box = QGroupBox("Manual Annotation")
        marker_layout = QHBoxLayout(marker_box)
        marker_layout.addWidget(self.marker_input)
        marker_layout.addWidget(self.marker_button)

        self.connect_button = QPushButton("Connect to Cortex")
        self.start_button = QPushButton("Start Recording")
        self.stop_button = QPushButton("Stop + Save")
        self.stop_button.setEnabled(False)

        controls_box = QGroupBox("Controls")
        controls_layout = QVBoxLayout(controls_box)
        controls_layout.addWidget(self.connect_button)
        controls_layout.addWidget(self.start_button)
        controls_layout.addWidget(self.stop_button)
        controls_layout.addStretch(1)

        self.figure = Figure(figsize=(8, 5), tight_layout=True)
        self.canvas = FigureCanvas(self.figure)
        self.axes = self.figure.add_subplot(111)
        self.axes.set_title("Live EEG")
        self.axes.set_xlabel("Samples")
        self.axes.set_ylabel("Amplitude (uV)")

        layout.addWidget(status_box, 0, 0)
        layout.addWidget(metadata_box, 1, 0)
        layout.addWidget(marker_box, 2, 0)
        layout.addWidget(controls_box, 3, 0)
        layout.addWidget(self.canvas, 0, 1, 4, 1)
        layout.setColumnStretch(1, 1)

        self.setCentralWidget(central)
        self.setStatusBar(QStatusBar())

    def _bind_callbacks(self) -> None:
        self.connect_button.clicked.connect(self.connect_cortex)
        self.start_button.clicked.connect(self.start_recording)
        self.stop_button.clicked.connect(self.stop_and_save)
        self.marker_button.clicked.connect(self.add_marker)

        self.api_client.on_eeg = self._on_eeg
        self.api_client.on_status = self._on_status
        self.api_client.on_battery = self._on_battery

    def connect_cortex(self) -> None:
        """Connect, authorize, query headset, and subscribe to EEG stream."""
        try:
            self.statusBar().showMessage("Connecting to Cortex...")
            self.api_client.connect()
            self.api_client.authorize()

            headsets = self.api_client.query_headsets()
            if not headsets:
                raise RuntimeError("No headset detected. Please pair your EPOC X+.")

            headset = headsets[0]
            self.api_client.create_session(headset.headset_id)
            sub_result = self.api_client.subscribe_eeg()

            eeg_stream = next((s for s in sub_result.get("success", []) if s.get("streamName") == "eeg"), None)
            if eeg_stream:
                self._channel_labels = eeg_stream.get("cols", [])[2:]

            self.status_connection.setText(f"Connected ({headset.headset_id})")
            if headset.battery_percent is not None:
                self.status_battery.setText(f"Battery: {headset.battery_percent:.0f}%")
            self.statusBar().showMessage("Connected and subscribed to EEG stream.", 5000)
        except Exception as exc:  # UI-safe message relay
            QMessageBox.critical(self, "Connection Error", str(exc))
            self.statusBar().showMessage("Connection failed.", 5000)

    def start_recording(self) -> None:
        """Start recording incoming EEG packets."""
        try:
            if not self.api_client.connected:
                raise RuntimeError("Connect to Cortex before recording.")
            labels = self._channel_labels or [f"CH{i+1}" for i in range(14)]
            self.recorder.start(labels, sample_rate_hz=self._sample_rate_hz)
            self.start_button.setEnabled(False)
            self.stop_button.setEnabled(True)
            self.statusBar().showMessage("Recording started.")
        except Exception as exc:
            QMessageBox.warning(self, "Start Recording", str(exc))

    def stop_and_save(self) -> None:
        """Stop recording and export files to recordings/ directory."""
        try:
            self.recorder.stop()
            metadata = SessionMetadata(
                subject=self.subject_input.text().strip() or "unknown",
                experiment_name=self.experiment_input.text().strip() or "untitled",
                notes=self.notes_input.toPlainText().strip(),
            )
            output_dir = ensure_output_dir("recordings")
            stem = f"{metadata.subject}_{metadata.experiment_name}_{int(time.time())}"
            paths = self.recorder.export_all(Path(output_dir / stem), metadata)

            self.start_button.setEnabled(True)
            self.stop_button.setEnabled(False)
            self.statusBar().showMessage(
                f"Saved CSV/NPY/FIF: {paths['csv'].name}, {paths['npy'].name}, {paths['fif'].name}",
                8000,
            )
        except Exception as exc:
            QMessageBox.warning(self, "Save Error", str(exc))

    def add_marker(self) -> None:
        """Add a manual annotation marker at current wall-clock timestamp."""
        label = self.marker_input.text().strip()
        if not label:
            return
        self.recorder.add_marker(timestamp=time.time(), label=label)
        self.marker_input.clear()
        self.statusBar().showMessage(f"Marker added: {label}", 3000)

    def _on_eeg(self, payload: dict) -> None:
        """Receive EEG packet callback from websocket thread."""
        self._sample_queue.put(payload)

    def _on_status(self, text: str) -> None:
        self.status_connection.setText(text)

    def _on_battery(self, value: float) -> None:
        self.status_battery.setText(f"Battery: {value:.0f}%")

    def _process_incoming_samples(self) -> None:
        """Drain queue, update recorder and refresh plot at UI timer cadence."""
        updated = False
        while True:
            try:
                payload = self._sample_queue.get_nowait()
            except queue.Empty:
                break

            eeg = payload.get("eeg")
            if not isinstance(eeg, list) or len(eeg) < 4:
                continue

            # Cortex eeg payload commonly: [COUNTER, INTERPOLATED, CH1..CHn, MARKERSYNC]
            timestamp = time.time()
            values = [float(v) for v in eeg[2:-1]] if len(eeg) > 3 else [float(v) for v in eeg[2:]]
            self._timestamps.append(timestamp)
            self._plot_buffer.append(values)
            self.recorder.add_sample(timestamp, values)
            updated = True

            if self._channel_labels and not self.recorder.channel_labels:
                self.recorder.channel_labels = self._channel_labels

            sid = payload.get("sid")
            if sid:
                self.status_connection.setText(f"Session: {sid}")

        if updated:
            self._redraw_plot()

    def _redraw_plot(self) -> None:
        """Draw first channel as a lightweight live waveform."""
        if not self._plot_buffer:
            return

        data = np.asarray(self._plot_buffer)
        first_channel = data[:, 0]

        self.axes.cla()
        self.axes.plot(first_channel, linewidth=1.0, color="#1f77b4")
        self.axes.set_title(f"Live EEG - {self._channel_labels[0] if self._channel_labels else 'Channel 1'}")
        self.axes.set_xlabel("Samples")
        self.axes.set_ylabel("Amplitude (uV)")
        self.canvas.draw_idle()

    def closeEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        """Shutdown Cortex session and websocket when GUI exits."""
        try:
            if self.api_client.session_id and self.api_client.auth_token:
                self.api_client.update_session_status("close")
            self.api_client.close()
        finally:
            super().closeEvent(event)

    @property
    def session_info(self) -> str:
        """Expose short session string used by tests/debugging."""
        return now_utc_iso()
