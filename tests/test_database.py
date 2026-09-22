import sqlite3
import tempfile
import unittest
from pathlib import Path

from src.database import import_library


def create_playlist(spotify_id: str, name: str) -> dict:
    return {
        "id": spotify_id,
        "name": name,
        "public": False,
        "owner": {
            "id": "owner-id",
            "display_name": "Owner",
        },
        "external_urls": {"spotify": f"spotify:playlist:{spotify_id}"},
    }


def create_playlist_item(track_id: str, added_at: str) -> dict:
    return {
        "added_at": added_at,
        "item": {
            "id": track_id,
            "type": "track",
            "name": "Track name",
            "album": {
                "id": "album-id",
                "name": "Album name",
                "release_date": "2024-01-01",
            },
            "artists": [{"id": "artist-id", "name": "Artist name"}],
            "duration_ms": 180000,
            "explicit": False,
            "external_urls": {"spotify": f"spotify:track:{track_id}"},
        },
    }


class DatabaseTest(unittest.TestCase):
    # Verify one Spotify track is shared across multiple imported playlists.
    def test_import_library_deduplicates_tracks_and_preserves_relations(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "library.db"
            playlists = [
                create_playlist("playlist-one", "Playlist one"),
                create_playlist("playlist-two", "Playlist two"),
            ]
            playlist_items = {
                "playlist-one": [create_playlist_item("track-one", "2024-01-02")],
                "playlist-two": [create_playlist_item("track-one", "2024-01-03")],
            }

            summary = import_library(playlists, playlist_items, database_path)

            connection = sqlite3.connect(database_path)

            try:
                track_count = connection.execute(
                    "SELECT COUNT(*) FROM tracks",
                ).fetchone()[0]
                relation_count = connection.execute(
                    "SELECT COUNT(*) FROM playlist_tracks",
                ).fetchone()[0]
            finally:
                connection.close()

            self.assertEqual(summary.playlist_count, 2)
            self.assertEqual(summary.playlist_track_count, 2)
            self.assertEqual(track_count, 1)
            self.assertEqual(relation_count, 2)

    # Verify repeated imports update the local snapshot without duplicates.
    def test_import_library_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "library.db"
            playlists = [create_playlist("playlist-one", "Playlist one")]
            playlist_items = {
                "playlist-one": [create_playlist_item("track-one", "2024-01-02")],
            }

            import_library(playlists, playlist_items, database_path)
            import_library(playlists, playlist_items, database_path)

            connection = sqlite3.connect(database_path)

            try:
                playlist_count = connection.execute(
                    "SELECT COUNT(*) FROM playlists",
                ).fetchone()[0]
                track_count = connection.execute(
                    "SELECT COUNT(*) FROM tracks",
                ).fetchone()[0]
                relation_count = connection.execute(
                    "SELECT COUNT(*) FROM playlist_tracks",
                ).fetchone()[0]
                import_count = connection.execute(
                    "SELECT COUNT(*) FROM imports",
                ).fetchone()[0]
            finally:
                connection.close()

            self.assertEqual(playlist_count, 1)
            self.assertEqual(track_count, 1)
            self.assertEqual(relation_count, 1)
            self.assertEqual(import_count, 2)

    # Verify repeated tracks in one playlist do not make the import fail.
    def test_import_library_deduplicates_repeated_playlist_tracks(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "library.db"
            playlists = [create_playlist("playlist-one", "Playlist one")]
            playlist_items = {
                "playlist-one": [
                    create_playlist_item("track-one", "2024-01-02"),
                    create_playlist_item("track-one", "2024-01-03"),
                ],
            }

            summary = import_library(playlists, playlist_items, database_path)

            connection = sqlite3.connect(database_path)

            try:
                relation = connection.execute(
                    "SELECT added_at FROM playlist_tracks",
                ).fetchone()
            finally:
                connection.close()

            self.assertEqual(summary.playlist_track_count, 1)
            self.assertEqual(relation[0], "2024-01-03")

    # Verify unsupported Spotify items do not prevent an import from completing.
    def test_import_library_skips_unsupported_items(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "library.db"
            playlists = [create_playlist("playlist-one", "Playlist one")]
            playlist_items = {
                "playlist-one": [{"added_at": "2024-01-02", "item": None}],
            }

            summary = import_library(playlists, playlist_items, database_path)

            self.assertEqual(summary.playlist_track_count, 0)
            self.assertEqual(summary.skipped_item_count, 1)


if __name__ == "__main__":
    unittest.main()
