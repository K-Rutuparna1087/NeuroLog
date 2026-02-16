"""Recording pipeline and file exporters for NeuroLog EEG sessions."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import mne
import numpy as np
import pandas as pd

from neuro_log.utils import sanitize_filename


@dataclass(slots=True)
class SessionMetadata:
    """User-provided metadata associated with one recording session."""

    subject: str
    experiment_name: str
    notes: str = ""


@dataclass(slots=True)
class Marker:
    """Manual marker inserted during recording."""

    timestamp: float
    label: str
    value: str = ""


@dataclass
class EEGRecorder:
    """Stateful EEG recorder that accumulates samples and persists to disk."""

    output_dir: Path = Path("recordings")
    recording: bool = False
    metadata: SessionMetadata | None = None
    channel_labels: list[str] = field(default_factory=list)
    sampling_rate_hz: float = 128.0

    timestamps: list[float] = field(default_factory=list)
    samples: list[list[float]] = field(default_factory=list)
    markers: list[Marker] = field(default_factory=list)

    def start(self, metadata: SessionMetadata, channel_labels: list[str], sampling_rate_hz: float) -> None:
        """Start a fresh recording buffer with metadata and stream layout."""
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.recording = True
        self.metadata = metadata
        self.channel_labels = channel_labels
        self.sampling_rate_hz = sampling_rate_hz

        self.timestamps.clear()
        self.samples.clear()
        self.markers.clear()

    def stop(self) -> dict[str, Path]:
        """Stop recording and save all outputs.

        Returns a mapping of file format to output path.
        """
        self.recording = False
        if not self.samples:
            raise RuntimeError("No samples available to save.")

        base_name = self._build_base_name()
        csv_path = self.output_dir / f"{base_name}.csv"
        npy_path = self.output_dir / f"{base_name}.npy"
        fif_path = self.output_dir / f"{base_name}.fif"
        marker_path = self.output_dir / f"{base_name}_markers.csv"

        data_array = np.asarray(self.samples, dtype=np.float64)
        self._save_csv(csv_path, data_array)
        np.save(npy_path, data_array)
        self._save_fif(fif_path, data_array)
        self._save_markers(marker_path)

        return {"csv": csv_path, "npy": npy_path, "fif": fif_path, "markers": marker_path}

    def add_sample(self, timestamp_s: float, eeg_values: list[float]) -> None:
        """Store one EEG sample frame when recording is enabled."""
        if not self.recording:
            return

        if len(eeg_values) != len(self.channel_labels):
            raise ValueError(
                f"EEG sample length ({len(eeg_values)}) does not match channel count ({len(self.channel_labels)})."
            )

        self.timestamps.append(timestamp_s)
        self.samples.append(eeg_values)

    def add_marker(self, timestamp_s: float, label: str, value: str = "") -> None:
        """Store a manual marker."""
        self.markers.append(Marker(timestamp=timestamp_s, label=label, value=value))

    def _save_csv(self, path: Path, data_array: np.ndarray) -> None:
        columns = ["timestamp"] + self.channel_labels
        df = pd.DataFrame(np.column_stack([self.timestamps, data_array]), columns=columns)

        if self.metadata:
            df.attrs["subject"] = self.metadata.subject
            df.attrs["experiment_name"] = self.metadata.experiment_name
            df.attrs["notes"] = self.metadata.notes

        df.to_csv(path, index=False)

    def _save_fif(self, path: Path, data_array: np.ndarray) -> None:
        # MNE expects shape (n_channels, n_times)
        data = data_array.T
        info = mne.create_info(ch_names=self.channel_labels, sfreq=self.sampling_rate_hz, ch_types="eeg")
        raw = mne.io.RawArray(data, info, verbose="ERROR")

        for marker in self.markers:
            onset = max(0.0, marker.timestamp - self.timestamps[0])
            raw.annotations.append(onset=onset, duration=0.0, description=marker.label)

        if self.metadata:
            raw.info["subject_info"] = {"his_id": self.metadata.subject}
            raw.info["description"] = f"experiment={self.metadata.experiment_name}; notes={self.metadata.notes}"

        raw.save(path, overwrite=True, verbose="ERROR")

    def _save_markers(self, path: Path) -> None:
        marker_df = pd.DataFrame(
            [
                {"timestamp": marker.timestamp, "label": marker.label, "value": marker.value}
                for marker in self.markers
            ]
        )
        marker_df.to_csv(path, index=False)

    def _build_base_name(self) -> str:
        now = datetime.now().strftime("%Y%m%d_%H%M%S")
        subject = self.metadata.subject if self.metadata else "unknown"
        experiment = self.metadata.experiment_name if self.metadata else "session"
        return sanitize_filename(f"{subject}_{experiment}_{now}")

    @staticmethod
    def extract_eeg_values(eeg_payload: dict[str, Any], channel_count: int) -> tuple[float, list[float]]:
        """Parse Cortex EEG payload into timestamp and channel vector."""
        eeg = eeg_payload.get("eeg", [])
        if len(eeg) < channel_count:
            raise ValueError(f"Unexpected EEG payload length: {len(eeg)}")

        timestamp = float(eeg_payload.get("time", 0.0)) / 1000.0
        values = [float(v) for v in eeg[:channel_count]]
        return timestamp, values
