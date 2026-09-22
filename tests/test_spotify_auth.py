import unittest
from unittest import mock

from src.spotify_auth import (
    TOKEN_EXPIRATION_BUFFER_SECONDS,
    add_expiration_information,
    is_access_token_expired,
)


class SpotifyAuthTest(unittest.TestCase):
    # Verify Spotify token responses receive a local expiration timestamp.
    def test_add_expiration_information(self) -> None:
        with mock.patch("src.spotify_auth.time.time", return_value=1000):
            tokens = add_expiration_information(
                {
                    "access_token": "access",
                    "refresh_token": "refresh",
                    "expires_in": 3600,
                },
            )

        self.assertEqual(tokens["expires_at"], 4600)

    # Verify tokens inside the refresh buffer are treated as expired.
    def test_is_access_token_expired_inside_buffer(self) -> None:
        with mock.patch("src.spotify_auth.time.time", return_value=1000):
            expired = is_access_token_expired(
                {
                    "access_token": "access",
                    "expires_at": 1000 + TOKEN_EXPIRATION_BUFFER_SECONDS,
                },
            )

        self.assertIs(expired, True)

    # Verify tokens beyond the refresh buffer can be reused.
    def test_is_access_token_expired_outside_buffer(self) -> None:
        with mock.patch("src.spotify_auth.time.time", return_value=1000):
            expired = is_access_token_expired(
                {
                    "access_token": "access",
                    "expires_at": (
                        1000 + TOKEN_EXPIRATION_BUFFER_SECONDS + 1
                    ),
                },
            )

        self.assertIs(expired, False)


if __name__ == "__main__":
    unittest.main()
