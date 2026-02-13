# NeuroLog

NeuroLog is a Python desktop application for **real-time EEG acquisition** with the **Emotiv Cortex API**. It provides a PyQt6 GUI to connect to Cortex, view a live EEG waveform, start/stop recordings, add manual markers, and export recordings in common research formats.

## Features

- Secure WebSocket connection to Cortex (`wss://localhost:6868`)
- Authentication with `clientId` and `clientSecret`
- Headset discovery for Emotiv EPOC X+
- Session creation and EEG stream subscription
- Real-time EEG plotting in GUI
- Start/Stop recording controls
- Metadata capture (subject, experiment, notes)
- Manual event markers during recording
- Export to:
  - **CSV** (`timestamp` + channel columns)
  - **NumPy** (`.npy` array)
  - **FIF** (`.fif` via MNE, includes annotations)

## Installation

1. Ensure Python **3.10+** is installed.
2. (Recommended) create and activate a virtual environment.
3. Install dependencies:

```bash
pip install -r requirements.txt
```

## Configure Cortex credentials

Set your Emotiv Cortex credentials as environment variables before launching the app:

```bash
export CORTEX_CLIENT_ID="your_client_id"
export CORTEX_CLIENT_SECRET="your_client_secret"
```

> On Windows PowerShell use `$env:CORTEX_CLIENT_ID="..."` and `$env:CORTEX_CLIENT_SECRET="..."`.

## Running the application

From the repository root:

```bash
python -m neuro_log.app
```

## Connecting Emotiv EPOC X+

1. Turn on your EPOC X+ headset.
2. Open Emotiv Launcher and ensure Cortex service is running.
3. Make sure the headset is connected and available to Cortex.
4. In NeuroLog, click **Connect to Cortex**.
5. Once connected, click **Start Recording**.

## Recording workflow

1. Fill in session metadata fields (subject / experiment / notes).
2. Click **Start Recording**.
3. Use the annotation field and **Add Marker** to insert event markers.
4. Click **Stop + Save** to export files.

Files are written to the `recordings/` folder with timestamped names.

## Exported file formats

For each session, NeuroLog saves:

- `*.csv` — row-wise samples with first column `timestamp`
- `*.npy` — NumPy array of EEG samples (`n_samples x n_channels`)
- `*.fif` — MNE Raw file with EEG channels and marker annotations
- `*.json` — metadata and marker summary

## Project structure

```text
neuro_log/
  app.py       # application entrypoint
  api.py       # Cortex API WebSocket client
  gui.py       # PyQt6 GUI and live plotting
  recorder.py  # recording buffers and export
  utils.py     # shared helpers and dataclasses
requirements.txt
README.md
```
