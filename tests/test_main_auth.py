"""Tests for application authentication flow helpers."""

import unittest
from unittest import mock

from src import main


class MainAuthTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        main.spotify_tokens.clear()

    def tearDown(self) -> None:
        main.spotify_tokens.clear()

    # Verify a valid persisted access token is reused without refreshing.
    async def test_get_spotify_access_token_uses_valid_persisted_token(
        self,
    ) -> None:
        with (
            mock.patch(
                "src.main.load_tokens",
                return_value={
                    "current_user": {
                        "access_token": "persisted-access",
                        "refresh_token": "persisted-refresh",
                        "expires_at": 9999999999,
                    },
                },
            ),
            mock.patch("src.main.refresh_access_token") as refresh_mock,
        ):
            access_token = await main.get_spotify_access_token()

        self.assertEqual(access_token, "persisted-access")
        refresh_mock.assert_not_called()

    # Verify refresh responses keep the existing refresh token when omitted.
    async def test_get_spotify_access_token_preserves_refresh_token(
        self,
    ) -> None:
        main.spotify_tokens["current_user"] = {
            "access_token": "expired-access",
            "refresh_token": "existing-refresh",
            "expires_at": 1,
        }

        with (
            mock.patch.dict(
                "os.environ",
                {"SPOTIFY_CLIENT_ID": "client-id"},
            ),
            mock.patch(
                "src.main.refresh_access_token",
                new=mock.AsyncMock(
                    return_value={
                        "access_token": "refreshed-access",
                        "expires_in": 3600,
                    },
                ),
            ),
            mock.patch("src.main.persist_spotify_tokens") as persist_mock,
        ):
            access_token = await main.get_spotify_access_token()

        self.assertEqual(access_token, "refreshed-access")
        self.assertEqual(
            main.spotify_tokens["current_user"]["refresh_token"],
            "existing-refresh",
        )
        persist_mock.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
