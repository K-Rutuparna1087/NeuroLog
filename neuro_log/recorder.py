"""Recording buffer and export utilities for NeuroLog EEG sessions."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import mne
import numpy as np

from neuro_log.utils import SessionMetadata, dump_json


@dataclass(slots=True)
class EventMarker:
    """A manual event marker created during recording."""

    timestamp: float
    label: str


class EEGRecorder:
    """Collects EEG samples and exports them in multiple research-friendly formats."""

    def __init__(self) -> None:
        self._recording = False
        self._timestamps: list[float] = []
        self._samples: list[list[float]] = []
        self._markers: list[EventMarker] = []
        self.channel_labels: list[str] = []
        self.sample_rate_hz: float | None = None

    @property
    def is_recording(self) -> bool:
        """Return current recording state."""
        return self._recording

    def start(self, channel_labels: list[str], sample_rate_hz: float | None = None) -> None:
        """Begin a new recording and reset in-memory buffers."""
        self._recording = True
        self.channel_labels = channel_labels
        self.sample_rate_hz = sample_rate_hz
        self._timestamps.clear()
        self._samples.clear()
        self._markers.clear()

    def stop(self) -> None:
        """Stop recording without clearing captured data."""
        self._recording = False

    def add_sample(self, timestamp: float, values: list[float]) -> None:
        """Store one EEG sample if recording is active."""
        if not self._recording:
            return
        self._timestamps.append(timestamp)
        self._samples.append(values)

    def add_marker(self, timestamp: float, label: str) -> None:
        """Attach a manual event marker to the active recording."""
        if self._recording and label.strip():
            self._markers.append(EventMarker(timestamp=timestamp, label=label.strip()))

    def export_all(self, output_prefix: Path, metadata: SessionMetadata) -> dict[str, Path]:
        """Save recording data to CSV, NPY, FIF, plus metadata JSON."""
        if not self._samples:
            raise RuntimeError("No EEG samples recorded; cannot export empty dataset.")

        paths = {
            "csv": output_prefix.with_suffix(".csv"),
            "npy": output_prefix.with_suffix(".npy"),
            "fif": output_prefix.with_suffix(".fif"),
            "meta": output_prefix.with_suffix(".json"),
        }

        self._export_csv(paths["csv"])
        self._export_npy(paths["npy"])
        self._export_fif(paths["fif"], metadata)
        self._export_metadata(paths["meta"], metadata)
        return paths

    def _export_csv(self, path: Path) -> None:
        with path.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.writer(fh)
            writer.writerow(["timestamp", *self.channel_labels])
            for ts, values in zip(self._timestamps, self._samples, strict=True):
                writer.writerow([ts, *values])

    def _export_npy(self, path: Path) -> None:
        data = np.asarray(self._samples, dtype=np.float32)
        np.save(path, data)

    def _export_fif(self, path: Path, metadata: SessionMetadata) -> None:
        sample_rate = self.sample_rate_hz or 128.0
        channels = self.channel_labels or [f"EEG{i+1}" for i in range(len(self._samples[0]))]

        data = np.asarray(self._samples, dtype=np.float64).T
        info = mne.create_info(ch_names=channels, sfreq=sample_rate, ch_types="eeg")
        raw = mne.io.RawArray(data, info, verbose=False)

        for marker in self._markers:
            onset = marker.timestamp - self._timestamps[0]
            raw.annotations.append(onset=onset, duration=0.0, description=marker.label)

        raw.info["description"] = (
            f"subject={metadata.subject}; experiment={metadata.experiment_name}; "
            f"notes={metadata.notes}"
        )
        raw.save(path, overwrite=True, verbose=False)

    def _export_metadata(self, path: Path, metadata: SessionMetadata) -> None:
        payload: dict[str, Any] = {
            "subject": metadata.subject,
            "experiment_name": metadata.experiment_name,
            "notes": metadata.notes,
            "sample_rate_hz": self.sample_rate_hz,
            "channels": self.channel_labels,
            "samples": len(self._samples),
            "markers": [marker.__dict__ for marker in self._markers],
        }
        dump_json(path, payload)
