from __future__ import annotations

import json
import logging
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from emunium.bridge import Bridge
from emunium.chrome_installer import ensure_chrome

logger = logging.getLogger("emunium.browser")

EXTENSION_DIR = str(Path(__file__).resolve().parent.parent / "extension")


class BrowserSession:
    __slots__ = (
        "bridge",
        "process",
        "headless",
        "user_data_dir",
        "tmp_data_dir",
        "tmp_extension_dir",
        "chrome_path",
    )

    def __init__(self) -> None:
        self.bridge: Bridge | None = None
        self.process: subprocess.Popen | None = None
        self.headless: bool = False
        self.user_data_dir: str | None = None
        self.tmp_data_dir: str | None = None
        self.tmp_extension_dir: str | None = None
        self.chrome_path: str = ""


def launch(session: BrowserSession, bridge_timeout: float = 60.0) -> None:
    try:
        session.chrome_path = ensure_chrome()
        if session.bridge is None:
            raise RuntimeError("Browser session has no bridge")
        session.bridge.start()
        port = session.bridge.actual_port
        if port is None:
            raise RuntimeError("Bridge did not start listening")
        logger.info("Bridge started on port %d", port)

        if session.user_data_dir:
            data_dir = str(Path(session.user_data_dir).resolve())
        else:
            session.tmp_data_dir = tempfile.mkdtemp(prefix="emun_profile_")
            data_dir = session.tmp_data_dir
            logger.info("Created temp profile: %s", data_dir)

        _write_master_preferences(session.chrome_path)
        _seed_profile(data_dir)
        extension_dir = _copy_extension_for_session(session, port)

        args = [
            session.chrome_path,
            f"--user-data-dir={data_dir}",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-popup-blocking",
            f"--load-extension={extension_dir}",
        ]
        if session.headless:
            args.append("--headless=new")

        session.process = subprocess.Popen(args)
        time.sleep(2)

        connected = session.bridge.wait_for_connection(timeout=bridge_timeout)
        if not connected:
            raise RuntimeError("Extension did not connect within timeout")
        logger.info("Extension connected to bridge")
    except Exception:
        try:
            close(session)
        except Exception:
            logger.exception("Failed to clean up browser after launch error")
        raise


def close(session: BrowserSession) -> None:
    process = session.process
    session.process = None
    if process:
        try:
            process.terminate()
            process.wait(timeout=5)
        except Exception:
            try:
                process.kill()
                process.wait(timeout=5)
            except Exception:
                logger.exception("Could not stop Chrome process")
    if session.bridge:
        try:
            session.bridge.shutdown()
        except Exception:
            logger.exception("Could not stop bridge")
    if session.tmp_extension_dir:
        try:
            _restore_extension(session.tmp_extension_dir)
        except OSError:
            logger.exception("Could not remove extension port configuration")
        shutil.rmtree(session.tmp_extension_dir, ignore_errors=True)
        session.tmp_extension_dir = None
    if session.tmp_data_dir:
        shutil.rmtree(session.tmp_data_dir, ignore_errors=True)
        session.tmp_data_dir = None
    logger.info("Browser closed")


def _copy_extension_for_session(session: BrowserSession, port: int) -> str:
    extension_dir = tempfile.mkdtemp(prefix="emun_extension_")
    session.tmp_extension_dir = extension_dir
    shutil.copytree(
        EXTENSION_DIR,
        extension_dir,
        dirs_exist_ok=True,
        ignore=shutil.ignore_patterns("port.json", ".port"),
    )
    _patch_extension_port(port, extension_dir)
    return extension_dir


def _patch_extension_port(port: int, extension_dir: str) -> None:
    port_file = Path(extension_dir) / "port.json"
    port_file.write_text(json.dumps({"port": port}), encoding="utf-8")


def _restore_extension(extension_dir: str) -> None:
    port_file = Path(extension_dir) / "port.json"
    if port_file.exists():
        port_file.unlink(missing_ok=True)


def _write_master_preferences(chrome_path: str) -> None:
    master = Path(chrome_path).parent / "master_preferences"
    payload = {"extensions": {"ui": {"developer_mode": True}}}
    master.write_text(json.dumps(payload), encoding="utf-8")


def _seed_profile(data_dir: str) -> None:
    default_dir = Path(data_dir) / "Default"
    default_dir.mkdir(parents=True, exist_ok=True)
    prefs_path = default_dir / "Preferences"
    if prefs_path.exists():
        try:
            prefs = json.loads(prefs_path.read_text(encoding="utf-8"))
        except Exception:
            prefs = {}
        prefs.setdefault("extensions", {}).setdefault("ui", {})["developer_mode"] = True
        prefs.setdefault("profile", {})["exited_cleanly"] = True
        tracked = prefs.get("prefs", {}).get("tracked_preferences_reset", [])
        if "extensions.ui.developer_mode" in tracked:
            tracked.remove("extensions.ui.developer_mode")
            prefs["prefs"]["tracked_preferences_reset"] = tracked
    else:
        prefs = {
            "extensions": {
                "alerts": {"initialized": True},
                "ui": {"developer_mode": True},
            },
            "profile": {"exited_cleanly": True},
            "browser": {"has_seen_welcome_page": True},
            "prefs": {"tracked_preferences_reset": []},
        }
    prefs_path.write_text(json.dumps(prefs), encoding="utf-8")
    local_state_path = Path(data_dir) / "Local State"
    if not local_state_path.exists():
        local_state = {
            "browser": {"enabled_labs_experiments": []},
            "profile": {"info_cache": {}},
        }
        local_state_path.write_text(json.dumps(local_state), encoding="utf-8")
