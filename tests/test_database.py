import sqlite3
import tempfile
import unittest
from pathlib import Path

from src.database import (
    create_genre,
    create_genre_rule,
    delete_genre,
    import_library,
    list_genres,
    list_track_genres,
    list_tracks_needing_review,
    update_genre,
)


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


def create_playlist_item(
    track_id: str,
    added_at: str,
    album_id: str = "album-id",
    artist_id: str = "artist-id",
) -> dict:
    return {
        "added_at": added_at,
        "item": {
            "id": track_id,
            "type": "track",
            "name": "Track name",
            "album": {
                "id": album_id,
                "name": "Album name",
                "release_date": "2024-01-01",
            },
            "artists": [{"id": artist_id, "name": "Artist name"}],
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

    # Verify the initial user-editable genre configuration is seeded once.
    def test_initial_genres_are_seeded_once(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "library.db"

            first_genres = list_genres(path=database_path)
            second_genres = list_genres(path=database_path)

            self.assertEqual(len(first_genres), 27)
            self.assertEqual(len(second_genres), 27)
            self.assertIn("Rap Nacional", {genre["name"] for genre in first_genres})

    # Verify users can create, update, disable, and delete local genres.
    def test_genre_crud(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "library.db"
            genre = create_genre(
                name="Custom Genre",
                description="A user-defined genre.",
                enabled=True,
                path=database_path,
            )
            updated_genre = update_genre(
                genre_id=genre["id"],
                name="Updated Genre",
                description=None,
                enabled=False,
                path=database_path,
            )

            self.assertEqual(updated_genre["name"], "Updated Genre")
            self.assertIs(updated_genre["enabled"], False)
            self.assertTrue(delete_genre(genre["id"], path=database_path))
            self.assertFalse(delete_genre(genre["id"], path=database_path))

    # Verify track, album, and artist rules follow the agreed precedence.
    def test_rule_classification_precedence(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "library.db"
            playlists = [create_playlist("playlist-one", "Playlist one")]
            playlist_items = {
                "playlist-one": [
                    create_playlist_item("track-one", "2024-01-02"),
                    create_playlist_item("track-two", "2024-01-03"),
                    create_playlist_item(
                        "track-three",
                        "2024-01-04",
                        album_id="other-album",
                    ),
                ],
            }
            import_library(playlists, playlist_items, database_path)
            genres_by_name = {
                genre["name"]: genre
                for genre in list_genres(path=database_path)
            }

            create_genre_rule(
                genre_id=genres_by_name["Rock"]["id"],
                resource_type="artist",
                spotify_id="artist-id",
                path=database_path,
            )
            create_genre_rule(
                genre_id=genres_by_name["Pop"]["id"],
                resource_type="album",
                spotify_id="album-id",
                path=database_path,
            )
            create_genre_rule(
                genre_id=genres_by_name["Dance"]["id"],
                resource_type="track",
                spotify_id="track-one",
                path=database_path,
            )

            track_one_genres = list_track_genres("track-one", database_path)
            track_two_genres = list_track_genres("track-two", database_path)
            track_three_genres = list_track_genres("track-three", database_path)

            self.assertEqual(track_one_genres[0]["name"], "Dance")
            self.assertEqual(track_one_genres[0]["source"], "track_rule")
            self.assertEqual(track_two_genres[0]["name"], "Pop")
            self.assertEqual(track_two_genres[0]["source"], "album_rule")
            self.assertEqual(track_three_genres[0]["name"], "Rock")
            self.assertEqual(track_three_genres[0]["source"], "artist_rule")

    # Verify unclassified imported tracks are available for manual review.
    def test_review_queue_lists_unclassified_tracks(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "library.db"
            playlists = [create_playlist("playlist-one", "Playlist one")]
            playlist_items = {
                "playlist-one": [create_playlist_item("track-one", "2024-01-02")],
            }
            import_library(playlists, playlist_items, database_path)

            review_queue = list_tracks_needing_review(
                limit=50,
                offset=0,
                path=database_path,
            )

            self.assertEqual(review_queue["total"], 1)
            self.assertEqual(review_queue["items"][0]["spotify_id"], "track-one")


if __name__ == "__main__":
    unittest.main()
