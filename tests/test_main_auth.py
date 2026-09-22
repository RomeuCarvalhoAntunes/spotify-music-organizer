import unittest
from unittest import mock

from src import main
from src.database import ImportSummary


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

    # Verify a local import fetches items for every available playlist.
    async def test_import_spotify_library_fetches_all_playlists(self) -> None:
        playlists = [{"id": "playlist-one"}, {"id": "playlist-two"}]
        playlist_items = [[{"item": {"id": "track-one"}}], []]
        summary = ImportSummary(
            import_id=1,
            playlist_count=2,
            playlist_track_count=1,
            skipped_item_count=0,
        )

        with (
            mock.patch(
                "src.main.get_spotify_access_token",
                new=mock.AsyncMock(return_value="access-token"),
            ),
            mock.patch(
                "src.main.get_current_user_playlists",
                new=mock.AsyncMock(return_value=playlists),
            ),
            mock.patch(
                "src.main.get_playlist_items",
                new=mock.AsyncMock(side_effect=playlist_items),
            ) as playlist_items_mock,
            mock.patch(
                "src.main.import_library",
                return_value=summary,
            ) as import_mock,
        ):
            result = await main.import_spotify_library()

        self.assertEqual(result, summary.to_dict())
        self.assertEqual(playlist_items_mock.await_count, 2)
        import_mock.assert_called_once_with(
            playlists,
            {
                "playlist-one": playlist_items[0],
                "playlist-two": playlist_items[1],
            },
        )


if __name__ == "__main__":
    unittest.main()
