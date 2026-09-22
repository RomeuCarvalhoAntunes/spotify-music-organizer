import stat
import tempfile
import unittest
from pathlib import Path

from src.spotify_tokens import load_tokens, save_tokens


class SpotifyTokensTest(unittest.TestCase):
    # Verify missing token files are treated as an empty token store.
    def test_load_tokens_returns_empty_dict_when_file_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            token_path = Path(temporary_directory) / "missing.json"

            self.assertEqual(load_tokens(token_path), {})

    # Verify tokens are saved and loaded from the configured file path.
    def test_save_and_load_tokens(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            token_path = Path(temporary_directory) / "spotify_tokens.json"
            tokens = {
                "current_user": {
                    "access_token": "access",
                    "refresh_token": "refresh",
                    "expires_at": 123,
                },
            }

            save_tokens(tokens, token_path)

            self.assertEqual(load_tokens(token_path), tokens)

    # Verify the token file is written with a restricted permission mode.
    def test_save_tokens_uses_restricted_file_permissions(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            token_path = Path(temporary_directory) / "spotify_tokens.json"

            save_tokens({"current_user": {"access_token": "access"}}, token_path)

            mode = stat.S_IMODE(token_path.stat().st_mode)

            self.assertEqual(mode, 0o600)


if __name__ == "__main__":
    unittest.main()
