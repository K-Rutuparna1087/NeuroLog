"""PyQt6 GUI for real-time NeuroLog EEG acquisition and recording."""

from __future__ import annotations

import time
from collections import deque
from pathlib import Path

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
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from neuro_log.api import CortexApiClient
from neuro_log.recorder import EEGRecorder, SessionMetadata


class NeuroLogMainWindow(QMainWindow):
    """Main application window for EEG streaming and recording control."""

    def __init__(self, api_client: CortexApiClient) -> None:
        super().__init__()
        self.api_client = api_client
        self.recorder = EEGRecorder(output_dir=Path("recordings"))

        self.setWindowTitle("NeuroLog - Emotiv EEG Recorder")
        self.resize(1200, 800)

        self.channel_labels: list[str] = []
        self.plot_window_s = 8
        self.plot_buffers: dict[str, deque[float]] = {}
        self.plot_time: deque[float] = deque(maxlen=1024)
        self.connected_and_subscribed = False

        self._build_ui()
        self._configure_callbacks()

        self.redraw_timer = QTimer(self)
        self.redraw_timer.timeout.connect(self._refresh_plot)
        self.redraw_timer.start(120)

    def _build_ui(self) -> None:
        root = QWidget()
        root_layout = QVBoxLayout(root)

        status_group = QGroupBox("Status")
        status_layout = QGridLayout(status_group)
        self.connection_status = QLabel("Disconnected")
        self.sampling_rate_label = QLabel("-")
        self.battery_label = QLabel("-")
        self.hint_label = QLabel("Click Connect first, then Start Recording.")
        status_layout.addWidget(QLabel("Connection:"), 0, 0)
        status_layout.addWidget(self.connection_status, 0, 1)
        status_layout.addWidget(QLabel("Sampling rate:"), 0, 2)
        status_layout.addWidget(self.sampling_rate_label, 0, 3)
        status_layout.addWidget(QLabel("Battery:"), 0, 4)
        status_layout.addWidget(self.battery_label, 0, 5)
        status_layout.addWidget(self.hint_label, 1, 0, 1, 6)

        control_group = QGroupBox("Recording Controls")
        control_layout = QHBoxLayout(control_group)
        self.connect_button = QPushButton("Connect")
        self.start_button = QPushButton("Start Recording")
        self.stop_button = QPushButton("Stop Recording")
        self.start_button.setEnabled(False)
        self.stop_button.setEnabled(False)

        self.marker_label_input = QLineEdit()
        self.marker_label_input.setPlaceholderText("marker label")
        self.marker_value_input = QLineEdit()
        self.marker_value_input.setPlaceholderText("optional value")
        self.add_marker_button = QPushButton("Add Marker")
        self.add_marker_button.setEnabled(False)

        control_layout.addWidget(self.connect_button)
        control_layout.addWidget(self.start_button)
        control_layout.addWidget(self.stop_button)
        control_layout.addWidget(self.marker_label_input)
        control_layout.addWidget(self.marker_value_input)
        control_layout.addWidget(self.add_marker_button)

        metadata_group = QGroupBox("Session Metadata")
        metadata_layout = QFormLayout(metadata_group)
        self.subject_input = QLineEdit()
        self.experiment_input = QLineEdit()
        self.notes_input = QTextEdit()
        self.notes_input.setMaximumHeight(100)

        metadata_layout.addRow("Subject:", self.subject_input)
        metadata_layout.addRow("Experiment:", self.experiment_input)
        metadata_layout.addRow("Notes:", self.notes_input)

        self.figure = Figure(figsize=(10, 5))
        self.canvas = FigureCanvas(self.figure)
        self.axes = self.figure.add_subplot(111)
        self.axes.set_title("Live EEG")
        self.axes.set_xlabel("Time (s)")
        self.axes.set_ylabel("Amplitude (uV)")

        root_layout.addWidget(status_group)
        root_layout.addWidget(control_group)
        root_layout.addWidget(metadata_group)
        root_layout.addWidget(self.canvas, stretch=1)

        self.setCentralWidget(root)

    def _configure_callbacks(self) -> None:
        self.api_client.on_status = self.connection_status.setText
        self.api_client.on_eeg = self._on_eeg_message
        self.api_client.on_battery = lambda val: self.battery_label.setText(f"{val}%")

        self.connect_button.clicked.connect(self._connect_client)
        self.start_button.clicked.connect(self._start_recording)
        self.stop_button.clicked.connect(self._stop_recording)
        self.add_marker_button.clicked.connect(self._add_marker)

    def _connect_client(self) -> None:
        self.connect_button.setEnabled(False)
        self.connection_status.setText("Connecting...")

        try:
            self.api_client.connect()
            self.api_client.subscribe_eeg()
        except Exception as exc:
            self.connect_button.setEnabled(True)
            self.connected_and_subscribed = False
            self.start_button.setEnabled(False)
            self.add_marker_button.setEnabled(False)
            QMessageBox.critical(self, "Connection Error", str(exc))
            return

        self.channel_labels = self.api_client.channel_labels
        if not self.channel_labels:
            self.connect_button.setEnabled(True)
            self.connected_and_subscribed = False
            self.start_button.setEnabled(False)
            self.add_marker_button.setEnabled(False)
            QMessageBox.critical(
                self,
                "Subscription Error",
                "Connected to Cortex but no EEG channels were returned. "
                "Check that the headset is connected and streaming EEG.",
            )
            return

        sample_rate = self.api_client.sampling_rate_hz or 128.0
        self.sampling_rate_label.setText(f"{sample_rate} Hz")
        self._init_plot_buffers(self.channel_labels)

        self.connected_and_subscribed = True
        self.start_button.setEnabled(True)
        self.add_marker_button.setEnabled(True)
        self.connect_button.setText("Connected")
        self.hint_label.setText("Connected. You can now start recording.")

    def _start_recording(self) -> None:
        if not self.connected_and_subscribed:
            QMessageBox.warning(
                self,
                "Not Ready",
                "You must connect first. Click Connect and wait for EEG subscription to complete.",
            )
            return

        metadata = SessionMetadata(
            subject=self.subject_input.text().strip() or "unknown",
            experiment_name=self.experiment_input.text().strip() or "baseline",
            notes=self.notes_input.toPlainText().strip(),
        )

        self.recorder.start(
            metadata=metadata,
            channel_labels=self.channel_labels,
            sampling_rate_hz=self.api_client.sampling_rate_hz or 128.0,
        )

        self.start_button.setEnabled(False)
        self.stop_button.setEnabled(True)
        self.hint_label.setText("Recording in progress...")

    def _stop_recording(self) -> None:
        try:
            saved_paths = self.recorder.stop()
        except Exception as exc:
            QMessageBox.warning(self, "Recording", str(exc))
            self.start_button.setEnabled(True)
            self.stop_button.setEnabled(False)
            self.hint_label.setText("Connected. You can start recording when ready.")
            return

        self.start_button.setEnabled(True)
        self.stop_button.setEnabled(False)
        self.hint_label.setText("Recording stopped and exported.")

        file_lines = "\n".join(f"{fmt.upper()}: {path}" for fmt, path in saved_paths.items())
        QMessageBox.information(self, "Saved", f"Recording exported:\n{file_lines}")

    def _add_marker(self) -> None:
        label = self.marker_label_input.text().strip()
        value = self.marker_value_input.text().strip()
        if not label:
            QMessageBox.warning(self, "Marker", "Please provide a marker label.")
            return

        now = time.time()
        self.recorder.add_marker(now, label, value)

        try:
            if self.api_client.session_id:
                self.api_client.create_marker(label=label, value=value)
        except Exception:
            # Marker is still stored locally even if cortex injection fails.
            pass

        self.marker_label_input.clear()
        self.marker_value_input.clear()

    def _on_eeg_message(self, payload: dict) -> None:
        if not self.channel_labels:
            return

        try:
            timestamp, values = EEGRecorder.extract_eeg_values(payload, len(self.channel_labels))
        except Exception:
            return

        self.recorder.add_sample(timestamp, values)

        self.plot_time.append(timestamp)
        for idx, label in enumerate(self.channel_labels):
            self.plot_buffers[label].append(values[idx])

    def _init_plot_buffers(self, channels: list[str]) -> None:
        self.plot_time = deque(maxlen=2048)
        self.plot_buffers = {label: deque(maxlen=2048) for label in channels}

    def _refresh_plot(self) -> None:
        if not self.plot_time or not self.plot_buffers:
            return

        t0 = self.plot_time[-1]
        min_t = t0 - self.plot_window_s
        xs = [t - t0 for t in self.plot_time if t >= min_t]
        if not xs:
            return

        self.axes.clear()
        offset_step = 70.0

        for idx, label in enumerate(self.channel_labels[:8]):
            ys_full = list(self.plot_buffers[label])
            ys = ys_full[-len(xs) :]
            shifted = [y + idx * offset_step for y in ys]
            self.axes.plot(xs, shifted, linewidth=0.9, label=label)

        self.axes.set_title("Live EEG (last 8s, first 8 channels)")
        self.axes.set_xlabel("Time relative to now (s)")
        self.axes.set_ylabel("Amplitude + offset")
        self.axes.legend(loc="upper left", ncols=4, fontsize=8)
        self.axes.grid(alpha=0.2)
        self.canvas.draw_idle()

    def closeEvent(self, event) -> None:  # noqa: N802
        try:
            self.api_client.disconnect()
        except Exception:
            pass
        super().closeEvent(event)
