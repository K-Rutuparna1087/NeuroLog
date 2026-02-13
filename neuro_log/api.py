"""Cortex API WebSocket client for Emotiv EEG streaming."""

from __future__ import annotations

import json
import logging
import ssl
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable

from websocket import WebSocketApp

LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class HeadsetInfo:
    """Basic headset information discovered from Cortex."""

    headset_id: str
    status: str
    battery_percent: float | None


class CortexClient:
    """Threaded JSON-RPC client for the Emotiv Cortex WebSocket API.

    This client manages:
    - secure websocket connection to Cortex
    - authentication and token management
    - headset discovery and session creation
    - stream subscription and callbacks for EEG packets
    """

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        url: str = "wss://localhost:6868",
    ) -> None:
        self.client_id = client_id
        self.client_secret = client_secret
        self.url = url

        self._ws: WebSocketApp | None = None
        self._thread: threading.Thread | None = None
        self._connected = threading.Event()
        self._stop_requested = threading.Event()

        self._msg_id = 1
        self._pending: dict[int, dict[str, Any]] = {}
        self._pending_event = threading.Event()
        self._pending_lock = threading.Lock()

        self.auth_token: str | None = None
        self.session_id: str | None = None

        self.on_eeg: Callable[[dict[str, Any]], None] | None = None
        self.on_status: Callable[[str], None] | None = None
        self.on_battery: Callable[[float], None] | None = None

    @property
    def connected(self) -> bool:
        """Return whether websocket is currently connected."""
        return self._connected.is_set()

    def connect(self, timeout_s: float = 10.0) -> None:
        """Connect to Cortex websocket endpoint and wait for readiness."""
        if self._thread and self._thread.is_alive():
            return

        self._stop_requested.clear()
        self._ws = WebSocketApp(
            self.url,
            on_open=self._on_open,
            on_message=self._on_message,
            on_error=self._on_error,
            on_close=self._on_close,
        )

        def _run() -> None:
            assert self._ws is not None
            # Cortex usually uses a self-signed certificate on localhost.
            self._ws.run_forever(sslopt={"cert_reqs": ssl.CERT_NONE})

        self._thread = threading.Thread(target=_run, name="cortex-ws", daemon=True)
        self._thread.start()

        if not self._connected.wait(timeout=timeout_s):
            raise TimeoutError("Timed out waiting for Cortex websocket connection.")

    def close(self) -> None:
        """Close websocket and stop background thread."""
        self._stop_requested.set()
        if self._ws:
            self._ws.close()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2)
        self._connected.clear()

    def authorize(self) -> str:
        """Request user authorization and return Cortex auth token."""
        result = self._rpc(
            "authorize",
            {
                "clientId": self.client_id,
                "clientSecret": self.client_secret,
                "debit": 1,
            },
        )
        token = result["cortexToken"]
        self.auth_token = token
        return token

    def query_headsets(self) -> list[HeadsetInfo]:
        """Query available headsets and parse their metadata."""
        result = self._rpc("queryHeadsets", {})
        headsets: list[HeadsetInfo] = []
        for item in result:
            battery = item.get("battery")
            headsets.append(
                HeadsetInfo(
                    headset_id=item.get("id", ""),
                    status=item.get("status", "unknown"),
                    battery_percent=float(battery) if battery is not None else None,
                )
            )
        return headsets

    def create_session(self, headset_id: str) -> str:
        """Create an active Cortex session for streaming."""
        if not self.auth_token:
            raise RuntimeError("Cannot create session before authorize().")

        result = self._rpc(
            "createSession",
            {
                "cortexToken": self.auth_token,
                "headset": headset_id,
                "status": "active",
            },
        )
        self.session_id = result["id"]
        return self.session_id

    def subscribe_eeg(self) -> dict[str, Any]:
        """Subscribe current session to EEG stream."""
        if not self.auth_token or not self.session_id:
            raise RuntimeError("Cannot subscribe without auth token and session.")

        return self._rpc(
            "subscribe",
            {
                "cortexToken": self.auth_token,
                "session": self.session_id,
                "streams": ["eeg", "dev"],
            },
        )

    def update_session_status(self, status: str) -> dict[str, Any]:
        """Update session status (active, close)."""
        if not self.auth_token or not self.session_id:
            raise RuntimeError("Session not initialized.")

        return self._rpc(
            "updateSession",
            {
                "cortexToken": self.auth_token,
                "session": self.session_id,
                "status": status,
            },
        )

    def _on_open(self, _ws: WebSocketApp) -> None:
        LOGGER.info("Connected to Cortex websocket.")
        self._connected.set()
        if self.on_status:
            self.on_status("Connected")

    def _on_error(self, _ws: WebSocketApp, error: Any) -> None:
        LOGGER.error("Websocket error: %s", error)
        if self.on_status:
            self.on_status(f"Error: {error}")

    def _on_close(self, _ws: WebSocketApp, _status_code: int, _msg: str) -> None:
        LOGGER.info("Cortex websocket closed.")
        self._connected.clear()
        if self.on_status:
            self.on_status("Disconnected")

    def _on_message(self, _ws: WebSocketApp, message: str) -> None:
        payload = json.loads(message)

        # RPC response path
        if "id" in payload:
            with self._pending_lock:
                self._pending[payload["id"]] = payload
                self._pending_event.set()
            return

        # Data stream path
        if "eeg" in payload and self.on_eeg:
            self.on_eeg(payload)

        if "dev" in payload:
            dev = payload["dev"]
            if isinstance(dev, list) and len(dev) > 2 and self.on_battery:
                battery = dev[2]
                try:
                    self.on_battery(float(battery))
                except (TypeError, ValueError):
                    pass

    def _rpc(self, method: str, params: dict[str, Any], timeout_s: float = 10.0) -> Any:
        if not self._ws or not self.connected:
            raise RuntimeError("WebSocket is not connected.")

        msg_id = self._msg_id
        self._msg_id += 1

        request = {
            "jsonrpc": "2.0",
            "id": msg_id,
            "method": method,
            "params": params,
        }
        self._ws.send(json.dumps(request))

        start = time.monotonic()
        while time.monotonic() - start < timeout_s:
            with self._pending_lock:
                response = self._pending.pop(msg_id, None)
                if not self._pending:
                    self._pending_event.clear()

            if response is not None:
                if "error" in response:
                    raise RuntimeError(f"Cortex error for {method}: {response['error']}")
                return response.get("result")

            self._pending_event.wait(timeout=0.05)

        raise TimeoutError(f"Timed out waiting for Cortex RPC response: {method}")
