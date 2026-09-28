import unittest

from src.automatic_classification import (
    classify_tracks_with_spotify_playlists,
    map_spotify_playlist_to_genre,
)


class AutomaticClassificationTests(unittest.TestCase):
    def test_spotify_playlist_names_map_only_genre_playlists(self) -> None:
        self.assertEqual(map_spotify_playlist_to_genre("Hip Hop / Rap"), "Hip-Hop")
        self.assertEqual(map_spotify_playlist_to_genre("R&B / Soul"), "R&B / Soul")
        self.assertIsNone(map_spotify_playlist_to_genre("Banho"))
        self.assertIsNone(map_spotify_playlist_to_genre("Faixas do Shazam"))

    def test_spotify_playlist_items_are_ground_truth(self) -> None:
        classifications = classify_tracks_with_spotify_playlists(
            tracks=[{"spotify_id": "track-one"}],
            playlist_tracks_by_genre={
                "Funk": [{"item": {"id": "track-one"}}],
                "Rap Nacional": [{"item": {"id": "track-one"}}],
            },
            genre_ids_by_name={"Funk": 1, "Rap Nacional": 2},
        )
        self.assertEqual(classifications[0]["genre_ids"], [1, 2])
        self.assertEqual(classifications[0]["confidence"], 1.0)


if __name__ == "__main__":
    unittest.main()
