import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from _test_support import prepare_imports

prepare_imports()

from emunium._browser import launcher

PROJECT_ROOT = Path(__file__).resolve().parents[1]
_real_mkdtemp = tempfile.mkdtemp


def workspace_mkdtemp(prefix):
    return _real_mkdtemp(prefix=prefix, dir=str(PROJECT_ROOT))


class FakeBridge:
    def __init__(self, connected=False):
        self.actual_port = 45678
        self.connected = connected
        self.shutdown_called = False

    def start(self):
        pass

    def wait_for_connection(self, timeout):
        return self.connected

    def shutdown(self):
        self.shutdown_called = True


class LauncherTests(unittest.TestCase):
    def test_extension_port_is_written_to_a_private_copy(self):
        with tempfile.TemporaryDirectory(dir=PROJECT_ROOT) as temp_dir:
            source = Path(temp_dir) / "source"
            source.mkdir()
            (source / "manifest.json").write_text("{}", encoding="utf-8")
            (source / "port.json").write_text('{"port": 1111}', encoding="utf-8")
            session = launcher.BrowserSession()

            with mock.patch.object(launcher, "EXTENSION_DIR", str(source)):
                with mock.patch.object(
                    launcher.tempfile, "mkdtemp", side_effect=workspace_mkdtemp
                ):
                    private_dir = launcher._copy_extension_for_session(session, 2222)

            self.assertNotEqual(Path(private_dir).resolve(), source.resolve())
            self.assertEqual(
                json.loads((Path(private_dir) / "port.json").read_text()),
                {"port": 2222},
            )
            self.assertEqual(
                json.loads((source / "port.json").read_text()), {"port": 1111}
            )
            launcher.close(session)
            self.assertIsNone(session.tmp_extension_dir)

    def test_failed_handshake_cleans_up_process_and_temporary_files(self):
        session = launcher.BrowserSession()
        bridge = FakeBridge(connected=False)
        session.bridge = bridge
        process = mock.MagicMock()

        with mock.patch.object(launcher, "ensure_chrome", return_value="chrome"):
            with mock.patch.object(
                launcher.tempfile, "mkdtemp", side_effect=workspace_mkdtemp
            ):
                with mock.patch.object(
                    launcher.subprocess, "Popen", return_value=process
                ) as popen:
                    with mock.patch.object(launcher, "_write_master_preferences"):
                        with mock.patch.object(launcher, "_seed_profile"):
                            with mock.patch.object(launcher.time, "sleep"):
                                with self.assertRaisesRegex(
                                    RuntimeError, "did not connect"
                                ):
                                    launcher.launch(session, bridge_timeout=0)

        args = popen.call_args[0][0]
        self.assertFalse(
            any("IsolateOrigins" in arg or "site-per-process" in arg for arg in args)
        )
        process.terminate.assert_called_once()
        self.assertTrue(bridge.shutdown_called)
        self.assertIsNone(session.process)
        self.assertIsNone(session.tmp_data_dir)
        self.assertIsNone(session.tmp_extension_dir)


if __name__ == "__main__":
    unittest.main()
