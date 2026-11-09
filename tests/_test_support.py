"""Load Emunium source modules without requiring desktop runtime packages."""

import sys
import types
from pathlib import Path


def prepare_imports():
    project_root = Path(__file__).resolve().parents[1]
    package_root = project_root / "emunium"

    if "emunium" not in sys.modules:
        package = types.ModuleType("emunium")
        package.__path__ = [str(package_root)]
        package.__package__ = "emunium"
        sys.modules["emunium"] = package

    pyautogui = types.ModuleType("pyautogui")
    for name in ("typewrite", "hotkey", "click", "moveTo", "doubleClick", "drag"):
        setattr(pyautogui, name, lambda *args, **kwargs: None)
    sys.modules["pyautogui"] = pyautogui

    pyperclip = types.ModuleType("pyperclip")
    pyperclip.PyperclipException = RuntimeError
    pyperclip.paste = lambda: ""
    pyperclip.copy = lambda value: None
    sys.modules["pyperclip"] = pyperclip

    websockets = types.ModuleType("websockets")
    websockets.serve = lambda *args, **kwargs: None
    websockets.exceptions = types.SimpleNamespace(ConnectionClosed=Exception)
    server = types.ModuleType("websockets.server")
    server.WebSocketServer = object
    server.WebSocketServerProtocol = object
    websockets.server = server
    sys.modules["websockets"] = websockets
    sys.modules["websockets.server"] = server
