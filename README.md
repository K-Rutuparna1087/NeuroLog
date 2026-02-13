# NeuroLog

NeuroLog is a Python 3.10+ desktop application for real-time EEG acquisition from an Emotiv EPOC X+ headset via the Emotiv Cortex WebSocket API (`wss://localhost:6868`).

It provides:
- Secure Cortex connection + authentication (`clientId` / `clientSecret`)
- Headset discovery and active session creation
- EEG stream subscription and live plotting in a PyQt6 GUI
- Recording controls with manual markers
- Session metadata capture (subject, experiment, notes)
- Export formats: CSV, NumPy `.npy`, and MNE `.fif`

---

## Project Structure

```text
NeuroLog/
├── neuro_log/
│   ├── __init__.py
│   ├── app.py        # Entry point
│   ├── api.py        # Cortex API client
│   ├── gui.py        # PyQt6 GUI and live plotting
│   ├── recorder.py   # Recording buffer and file exporters
│   └── utils.py      # Helpers and environment config
├── requirements.txt
└── README.md
```

---

## Installation

1. **Create and activate a virtual environment**:

```bash
python -m venv .venv
source .venv/bin/activate   # Linux/macOS
# .venv\Scripts\activate   # Windows
```

2. **Install dependencies**:

```bash
pip install -r requirements.txt
```

3. **Ensure Emotiv Cortex service is running** on your machine.

---

## Configure Cortex Credentials

NeuroLog reads credentials from environment variables:

- `EMOTIV_CLIENT_ID`
- `EMOTIV_CLIENT_SECRET`
- optional: `EMOTIV_SSL_VERIFY` (`1` to enforce TLS cert verification, default `0`)

Example:

```bash
export EMOTIV_CLIENT_ID="your_client_id"
export EMOTIV_CLIENT_SECRET="your_client_secret"
export EMOTIV_SSL_VERIFY="0"
```

> Obtain client credentials from your Emotiv developer account and Cortex app configuration.

---

## Connect the Emotiv Headset

1. Power on your **Emotiv EPOC X+** headset.
2. Plug in the Emotiv USB receiver/dongle.
3. Open Emotiv Launcher / Cortex service and verify the device is paired.
4. Start NeuroLog and click **Connect**.
5. NeuroLog will:
   - request access
   - authorize
   - query available headsets
   - connect to the first available headset
   - create an active session
   - subscribe to EEG stream

---

## Run the Application

```bash
python -m neuro_log.app
```

GUI features:
- **Live plot** of recent EEG activity
- **Start Recording** / **Stop Recording** buttons
- **Manual marker** input (`label`, optional `value`)
- **Session metadata** input (subject, experiment, notes)
- Status labels for:
  - connection status
  - sampling rate
  - battery level

---

## Recording and Export Formats

On stop recording, NeuroLog writes files to `recordings/`:

1. **CSV** (`*.csv`)
   - Columns: `timestamp` + EEG channel labels
   - Useful for quick inspection and spreadsheet workflows

2. **NumPy array** (`*.npy`)
   - Shape: `(n_samples, n_channels)`
   - Efficient for scientific Python pipelines

3. **MNE FIF** (`*.fif`)
   - Created with `mne.io.RawArray`
   - Contains EEG channels, sampling rate, and marker annotations
   - Ready for advanced EEG processing in MNE

4. **Marker CSV** (`*_markers.csv`)
   - Manual marker timestamps + labels/values

---

## Notes

- The Cortex stream payload layout can vary by SDK version. This project includes practical defaults for EEG and battery updates, but you may adapt parsing for your specific firmware/API version.
- If certificate verification fails on localhost, use `EMOTIV_SSL_VERIFY=0`.
- For production/lab deployments, enable TLS verification whenever possible.
