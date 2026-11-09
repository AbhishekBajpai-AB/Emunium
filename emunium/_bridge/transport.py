from __future__ import annotations

import asyncio
import hmac
import ipaddress
import json
import logging
import re
import secrets
import threading
import time
from typing import Callable

import websockets
import websockets.server

logger = logging.getLogger("emunium.bridge")


class Transport:
    def __init__(self, host: str = "127.0.0.1", port: int = 0) -> None:
        try:
            address = ipaddress.ip_address(host)
        except ValueError as error:
            raise ValueError("Bridge host must be a loopback IP address") from error
        if not address.is_loopback or getattr(address, "scope_id", None):
            raise ValueError("Bridge may only bind to a loopback IP address")
        self.host = address.compressed
        self.port = port
        self.auth_token = secrets.token_urlsafe(32)
        self._server: websockets.server.WebSocketServer | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._ws: websockets.server.WebSocketServerProtocol | None = None
        self._pending: dict[int, asyncio.Future] = {}
        self._next_id = 1
        self._id_lock = threading.Lock()
        self._connected = threading.Event()
        self._event_handlers: dict[str, list[Callable]] = {}
        self._ready_event = threading.Event()
        self._startup_error: BaseException | None = None
        self._pinned_tab_id: int | None = None

    @property
    def actual_port(self) -> int | None:
        if self._server:
            for sock in self._server.sockets:
                return sock.getsockname()[1]
        return None

    def start(self, timeout: float = 30.0) -> None:
        self._ready_event.clear()
        self._startup_error = None
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(
            target=self._run_loop, daemon=True, name="emun-bridge"
        )
        self._thread.start()
        if not self._ready_event.wait(timeout=timeout):
            raise TimeoutError("Bridge server did not start within timeout")
        if self._startup_error is not None:
            raise RuntimeError("Bridge server failed to start") from self._startup_error
        logger.info("Bridge listening on %s:%d", self.host, self.actual_port)

    def _run_loop(self) -> None:
        try:
            asyncio.set_event_loop(self._loop)
            self._loop.run_until_complete(self._serve())
        except BaseException as error:
            self._startup_error = error
            self._ready_event.set()
            logger.exception("Bridge server stopped unexpectedly")
        finally:
            if self._loop and not self._loop.is_closed():
                self._loop.close()

    async def _serve(self) -> None:
        self._stop_future = self._loop.create_future()
        self._server = await websockets.serve(
            self._handle_connection, self.host, self.port
        )
        self._ready_event.set()
        await self._stop_future
        if self._server:
            self._server.close()
            await self._server.wait_closed()

    async def _handle_connection(
        self, ws: websockets.server.WebSocketServerProtocol
    ) -> None:
        if not self._is_authorized_connection(ws):
            logger.warning("Rejected unauthorized bridge connection")
            await ws.close(code=1008, reason="Unauthorized")
            return
        if self._connected.is_set():
            logger.warning("Rejected additional bridge connection")
            await ws.close(code=1008, reason="Bridge already has a connection")
            return

        logger.info("Extension connected")
        self._ws = ws
        self._connected.set()
        try:
            async for raw in ws:
                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    continue

                if "event" in msg:
                    self._dispatch_event(msg)
                    continue

                msg_id = msg.get("id")
                if msg_id is not None and msg_id in self._pending:
                    fut = self._pending.pop(msg_id)
                    if not fut.done():
                        self._loop.call_soon_threadsafe(
                            fut.set_result, msg.get("result")
                        )
        except websockets.exceptions.ConnectionClosed:
            pass
        finally:
            logger.info("Extension disconnected")
            self._ws = None
            self._connected.clear()

    def _is_authorized_connection(
        self, ws: websockets.server.WebSocketServerProtocol
    ) -> bool:
        request = getattr(ws, "request", None)
        path = getattr(request, "path", None) if request is not None else None
        if path is None:
            path = getattr(ws, "path", None)

        headers = getattr(request, "headers", None) if request is not None else None
        if headers is None:
            headers = getattr(ws, "request_headers", None)
        if headers is None:
            return False

        expected_path = f"/bridge/{self.auth_token}"
        if not isinstance(path, str) or not hmac.compare_digest(
            path.encode("utf-8", errors="surrogatepass"), expected_path.encode("ascii")
        ):
            return False

        origin = headers.get("Origin", "")
        if not re.fullmatch(r"chrome-extension://[a-p]{32}", origin):
            return False

        remote_address = getattr(ws, "remote_address", None)
        if not isinstance(remote_address, tuple) or not remote_address:
            return False
        try:
            if not ipaddress.ip_address(remote_address[0]).is_loopback:
                return False
        except ValueError:
            return False

        port = self.actual_port
        if port is None:
            return False
        address = ipaddress.ip_address(self.host)
        host = f"[{self.host}]" if address.version == 6 else self.host
        return headers.get("Host", "") == f"{host}:{port}"

    def _dispatch_event(self, msg: dict) -> None:
        event_name = msg.get("event", "")
        handlers = self._event_handlers.get(event_name, [])
        for handler in handlers:
            try:
                handler(msg)
            except Exception as e:
                logger.warning("Event handler error: %s", e)

    def on(self, event: str, handler: Callable) -> None:
        self._event_handlers.setdefault(event, []).append(handler)

    def wait_for_connection(self, timeout: float = 60.0) -> bool:
        return self._connected.wait(timeout=timeout)

    def send(
        self,
        method: str,
        params: dict[str, object] | None = None,
        timeout: float = 30.0,
        tab_id: int | None = None,
    ) -> object:
        if not self._connected.is_set():
            raise RuntimeError("Extension not connected")

        with self._id_lock:
            msg_id = self._next_id
            self._next_id += 1

        msg: dict[str, object] = {"id": msg_id, "method": method}
        if params:
            msg["params"] = params
        effective_tab_id = tab_id if tab_id is not None else self._pinned_tab_id
        if effective_tab_id is not None:
            msg["tabId"] = effective_tab_id

        fut = self._loop.create_future()
        self._pending[msg_id] = fut

        asyncio.run_coroutine_threadsafe(self._ws.send(json.dumps(msg)), self._loop)

        try:
            return self._wait_future(fut, timeout)
        except TimeoutError:
            self._pending.pop(msg_id, None)
            raise

    def _wait_future(self, fut: asyncio.Future, timeout: float) -> object:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if fut.done():
                return fut.result()
            time.sleep(0.01)
        raise TimeoutError("Bridge call timed out")

    @staticmethod
    def _is_cs_error(result: object) -> bool:
        if isinstance(result, dict) and "error" in result:
            err = str(result["error"]).lower()
            return any(
                p in err
                for p in (
                    "content script",
                    "receiving end",
                    "port closed",
                    "not ready",
                    "could not establish connection",
                )
            )
        return False

    def _send_with_retry(
        self,
        method: str,
        params: dict[str, object] | None = None,
        timeout: float = 10.0,
        max_retries: int = 3,
    ) -> object:
        last_result: object = None
        for attempt in range(max_retries):
            try:
                result = self.send(method, params, timeout=timeout)
            except TimeoutError:
                raise
            if not self._is_cs_error(result):
                return result
            last_result = result
            if attempt < max_retries - 1:
                error_text = (
                    result.get("error", "?") if isinstance(result, dict) else "?"
                )
                logger.warning(
                    "Content script error (attempt %d/%d): %s — retrying",
                    attempt + 1,
                    max_retries,
                    error_text,
                )
                time.sleep(0.5 * (attempt + 1))
        return last_result

    def _send_list(
        self,
        method: str,
        params: dict[str, object] | None = None,
        timeout: float = 10.0,
    ) -> list[dict]:
        result = self._send_with_retry(method, params, timeout=timeout)
        if isinstance(result, list):
            return result
        if self._is_cs_error(result):
            logger.error("Content script unreachable for %s after retries", method)
        return []

    def _send_optional(
        self,
        method: str,
        params: dict[str, object] | None = None,
        timeout: float = 10.0,
    ) -> dict | None:
        result = self._send_with_retry(method, params, timeout=timeout)
        if self._is_cs_error(result):
            logger.error("Content script unreachable for %s after retries", method)
            return None
        return result if result and "error" not in result else None

    def shutdown(self) -> None:
        if self._loop and self._loop.is_running():
            self._loop.call_soon_threadsafe(self._graceful_stop)
        if self._thread:
            self._thread.join(timeout=5)
        logger.info("Bridge stopped")

    def _graceful_stop(self) -> None:
        self._loop.create_task(self._async_shutdown())

    async def _async_shutdown(self) -> None:
        for fut in self._pending.values():
            if not fut.done():
                fut.cancel()
        self._pending.clear()

        if self._ws:
            try:
                await self._ws.close()
            except Exception:
                pass

        if hasattr(self, "_stop_future") and not self._stop_future.done():
            self._stop_future.set_result(None)
