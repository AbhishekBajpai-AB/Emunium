import unittest
from types import SimpleNamespace
from unittest import mock

from _test_support import prepare_imports

prepare_imports()

from emunium._bridge.facade import Bridge


class BridgeNetworkTests(unittest.TestCase):
    def make_bridge(self):
        bridge = Bridge.__new__(Bridge)
        bridge._response_marker = None
        bridge._network = mock.Mock()
        bridge._transport = SimpleNamespace(_pinned_tab_id=None)
        return bridge

    def test_wait_uses_marker_captured_before_action(self):
        bridge = self.make_bridge()
        bridge._response_marker = 12

        bridge.wait_for_response("*/api/users", timeout=4)

        bridge._network.wait_for_response.assert_called_once_with(
            "*/api/users", 4, since_request_sequence=12
        )
        bridge._network.get_response_marker.assert_not_called()
        self.assertIsNone(bridge._response_marker)

    def test_wait_without_an_action_marks_at_call_time(self):
        bridge = self.make_bridge()
        bridge._network.get_response_marker.return_value = 23

        bridge.wait_for_response("*/api/users")

        bridge._network.wait_for_response.assert_called_once_with(
            "*/api/users", 10.0, since_request_sequence=23
        )

    def test_create_tab_pins_the_new_tab(self):
        bridge = self.make_bridge()
        bridge._tabs = mock.Mock()
        bridge._tabs.create_tab.return_value = {"tabId": 9}
        bridge.mark_response_boundary = mock.Mock()

        result = bridge.create_tab("https://example.test")

        self.assertEqual(result, {"tabId": 9})
        self.assertEqual(bridge.pinned_tab_id, 9)


if __name__ == "__main__":
    unittest.main()
