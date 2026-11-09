import unittest
from unittest import mock

from _test_support import prepare_imports

prepare_imports()

from emunium._element_interactor import ElementInteractor


class ElementInteractorTypingTests(unittest.TestCase):
    def setUp(self):
        self.interactor = ElementInteractor()

    def test_default_unicode_typing_uses_clipboard(self):
        with mock.patch.object(self.interactor, "_paste_text") as paste, mock.patch.object(
            self.interactor, "_type_with_rhythm"
        ) as rhythm:
            self.interactor.type_text("namaste नमस्ते")

        paste.assert_called_once_with("namaste नमस्ते")
        rhythm.assert_not_called()

    def test_ascii_uses_rhythm_when_speed_is_positive(self):
        with mock.patch.object(self.interactor, "_paste_text") as paste, mock.patch.object(
            self.interactor, "_type_with_rhythm"
        ) as rhythm:
            self.interactor.type_text("hello", characters_per_minute=280)

        rhythm.assert_called_once_with(
            "hello", characters_per_minute=280, offset=20
        )
        paste.assert_not_called()

    def test_zero_speed_uses_fast_ascii_typing(self):
        with mock.patch("emunium._element_interactor.pyautogui.typewrite") as typewrite:
            self.interactor.type_text("hello", characters_per_minute=0)

        typewrite.assert_called_once_with("hello", interval=0.03)

    def test_negative_speed_is_rejected(self):
        with self.assertRaises(ValueError):
            self.interactor.type_text("hello", characters_per_minute=-1)

    def test_clipboard_is_restored_when_paste_fails(self):
        with (
            mock.patch(
                "emunium._element_interactor.pyperclip.paste", return_value="previous"
            ),
            mock.patch("emunium._element_interactor.pyperclip.copy") as copy,
            mock.patch(
                "emunium._element_interactor.pyautogui.hotkey",
                side_effect=RuntimeError("paste failed"),
            ),
        ):
            with self.assertRaisesRegex(RuntimeError, "paste failed"):
                self.interactor._paste_text("नमस्ते")

        self.assertEqual(
            [call.args[0] for call in copy.call_args_list], ["नमस्ते", "previous"]
        )


if __name__ == "__main__":
    unittest.main()
