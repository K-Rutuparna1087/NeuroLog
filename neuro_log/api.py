"""Cortex API client for Emotiv EEG streaming over secure WebSocket.

This module wraps the JSON-RPC workflow required by the Emotiv Cortex API:
1. Connect to `wss://localhost:6868`
2. Request access and authenticate
3. Query headset information
4. Create an active session
5. Subscribe to EEG and motion/system streams

The client runs the WebSocket in a background thread and emits parsed updates
through callback hooks suitable for GUI integration.
"""

from __future__ import annotations

import json
import logging
import queue
import ssl
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable

import websocket

LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class CortexConfig:
    """Configuration required to authenticate against Cortex."""

    client_id: str
    client_secret: str
    debit: int = 1
    license: str = ""
    host: str = "localhost"
    port: int = 6868
    ssl_verify: bool = False

    @property
    def url(self) -> str:
        """Return the secure websocket endpoint URL."""
        return f"wss://{self.host}:{self.port}"


class CortexApiClient:
    """Threaded client for Cortex JSON-RPC and EEG stream subscription."""

    def __init__(self, config: CortexConfig) -> None:
        self.config = config
        self.ws: websocket.WebSocketApp | None = None
        self.ws_thread: threading.Thread | None = None

        self._running = threading.Event()
        self._opened = threading.Event()
        self._authorized = threading.Event()

        self._request_id = 0
        self._pending: dict[int, queue.Queue[dict[str, Any]]] = {}
        self._lock = threading.Lock()

        self.cortex_token: str | None = None
        self.session_id: str | None = None
        self.headset_id: str | None = None

        self.channel_labels: list[str] = []
        self.sampling_rate_hz: float | None = None
        self.battery_percent: int | None = None

        self.on_status: Callable[[str], None] | None = None
        self.on_eeg: Callable[[dict[str, Any]], None] | None = None
        self.on_battery: Callable[[int], None] | None = None

    def connect(self, timeout_s: float = 10.0) -> None:
        """Connect and complete the authentication/session setup flow."""
        self._set_status("Connecting to Cortex...")
        self._running.set()

        sslopt: dict[str, Any]
        if self.config.ssl_verify:
            sslopt = {}
        else:
            sslopt = {"cert_reqs": ssl.CERT_NONE, "check_hostname": False}

        self.ws = websocket.WebSocketApp(
            self.config.url,
            on_open=self._on_open,
            on_message=self._on_message,
            on_error=self._on_error,
            on_close=self._on_close,
        )

        self.ws_thread = threading.Thread(
            target=self.ws.run_forever,
            kwargs={"sslopt": sslopt, "ping_interval": 20, "ping_timeout": 10},
            daemon=True,
            name="CortexWebSocketThread",
        )
        self.ws_thread.start()

        if not self._opened.wait(timeout_s):
            raise TimeoutError("Timed out while connecting to Cortex websocket.")

        self._setup_authorized_session(timeout_s=timeout_s)
        self._set_status("Connected and streaming-ready")

    def disconnect(self) -> None:
        """Close session and stop websocket thread gracefully."""
        self._running.clear()
        if self.ws:
            try:
                if self.session_id and self.cortex_token:
                    self._rpc(
                        "updateSession",
                        {
                            "cortexToken": self.cortex_token,
                            "session": self.session_id,
                            "status": "close",
                        },
                        timeout_s=3,
                    )
            except Exception:
                LOGGER.exception("Failed to close Cortex session cleanly")
            self.ws.close()

        if self.ws_thread and self.ws_thread.is_alive():
            self.ws_thread.join(timeout=2)

        self._set_status("Disconnected")

    def subscribe_eeg(self) -> dict[str, Any]:
        """Subscribe to EEG and battery/system streams for updates."""
        if not self.cortex_token or not self.session_id:
            raise RuntimeError("Client must be connected/authenticated before subscribing.")

        response = self._rpc(
            "subscribe",
            {
                "cortexToken": self.cortex_token,
                "session": self.session_id,
                "streams": ["eeg", "dev"],
            },
        )

        for stream_info in response.get("success", []):
            stream_name = stream_info.get("streamName")
            if stream_name == "eeg":
                cols = stream_info.get("cols", [])
                self.channel_labels = [
                    col for col in cols if col not in {"COUNTER", "INTERPOLATED", "MARKER_HARDWARE", "MARKERS"}
                ]
                self.sampling_rate_hz = stream_info.get("sampleRate")

        if not self.channel_labels:
            # Fallback for SDK variants that omit EEG labels in subscribe metadata.
            self.channel_labels = [
                "AF3",
                "F7",
                "F3",
                "FC5",
                "T7",
                "P7",
                "O1",
                "O2",
                "P8",
                "T8",
                "FC6",
                "F4",
                "F8",
                "AF4",
            ]

        if not self.sampling_rate_hz:
            self.sampling_rate_hz = 128.0

        self._set_status("Subscribed to EEG stream")
        return response

    def create_marker(self, label: str, value: str = "", port: str = "python") -> dict[str, Any]:
        """Inject a manual marker into the current session."""
        if not self.cortex_token or not self.session_id:
            raise RuntimeError("Cannot create marker before session is active.")

        return self._rpc(
            "injectMarker",
            {
                "cortexToken": self.cortex_token,
                "session": self.session_id,
                "label": label,
                "value": value,
                "port": port,
                "time": int(time.time() * 1000),
            },
        )

    def _setup_authorized_session(self, timeout_s: float) -> None:
        self._rpc(
            "requestAccess",
            {"clientId": self.config.client_id, "clientSecret": self.config.client_secret},
            timeout_s=timeout_s,
        )

        auth = self._rpc(
            "authorize",
            {
                "clientId": self.config.client_id,
                "clientSecret": self.config.client_secret,
                "debit": self.config.debit,
                "license": self.config.license,
            },
            timeout_s=timeout_s,
        )
        self.cortex_token = auth.get("cortexToken")
        if not self.cortex_token:
            raise RuntimeError(f"Authorization failed: {auth}")

        query = self._rpc("queryHeadsets", {}, timeout_s=timeout_s)
        headsets = query if isinstance(query, list) else query.get("headsets", [])
        if not headsets:
            raise RuntimeError("No Emotiv headset found. Check dongle/headset pairing.")

        headset = headsets[0]
        self.headset_id = headset.get("id")
        if not self.headset_id:
            raise RuntimeError(f"Headset payload missing id: {headset}")

        self._rpc(
            "controlDevice",
            {"command": "connect", "headset": self.headset_id},
            timeout_s=timeout_s,
        )

        session = self._rpc(
            "createSession",
            {
                "cortexToken": self.cortex_token,
                "headset": self.headset_id,
                "status": "active",
            },
            timeout_s=timeout_s,
        )
        self.session_id = session.get("id")
        if not self.session_id:
            raise RuntimeError(f"Could not create Cortex session: {session}")

        self._authorized.set()

    def _rpc(self, method: str, params: dict[str, Any], timeout_s: float = 8.0) -> dict[str, Any]:
        if not self.ws:
            raise RuntimeError("WebSocket is not initialized")

        request_id = self._next_id()
        msg = {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}

        response_queue: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=1)
        self._pending[request_id] = response_queue

        self.ws.send(json.dumps(msg))

        try:
            raw = response_queue.get(timeout=timeout_s)
        except queue.Empty as exc:
            self._pending.pop(request_id, None)
            raise TimeoutError(f"RPC timeout for method '{method}'") from exc

        error = raw.get("error")
        if error:
            raise RuntimeError(f"Cortex RPC error for {method}: {error}")

        return raw.get("result", {})

    def _next_id(self) -> int:
        with self._lock:
            self._request_id += 1
            return self._request_id

    def _on_open(self, _: websocket.WebSocketApp) -> None:
        self._set_status("WebSocket open")
        self._opened.set()

    def _on_message(self, _: websocket.WebSocketApp, message: str) -> None:
        try:
            payload = json.loads(message)
        except json.JSONDecodeError:
            LOGGER.warning("Received non-JSON payload: %s", message)
            return

        if "id" in payload:
            request_id = payload["id"]
            response_queue = self._pending.pop(request_id, None)
            if response_queue:
                response_queue.put(payload)
            return

        if "eeg" in payload:
            if self.on_eeg:
                self.on_eeg(payload)
            return

        if "dev" in payload:
            dev = payload.get("dev", [])
            # Device payload varies by SDK version; battery often appears as int in index 2/3.
            battery_candidates = [v for v in dev if isinstance(v, int)]
            if battery_candidates:
                self.battery_percent = max(0, min(100, battery_candidates[-1]))
                if self.on_battery:
                    self.on_battery(self.battery_percent)
            return

    def _on_error(self, _: websocket.WebSocketApp, error: Any) -> None:
        LOGGER.error("Cortex websocket error: %s", error)
        self._set_status(f"Connection error: {error}")

    def _on_close(self, _: websocket.WebSocketApp, close_status_code: int, close_msg: str) -> None:
        self._set_status(f"WebSocket closed ({close_status_code}): {close_msg}")

    def _set_status(self, status: str) -> None:
        LOGGER.info("Cortex status: %s", status)
        if self.on_status:
            self.on_status(status)
