from src.automatic_classification import (
    classify_tracks_with_lastfm,
    classify_tracks_with_spotify_artists,
    classify_tracks_with_spotify_playlists,
    get_lastfm_api_key,
)
from src.database import (
    get_classification_progress,
    list_genres,
    list_tracks_for_automatic_classification,
    record_automatic_attempts,
    store_automatic_classifications,
)

async def run_automatic_classification_job(
    job_id: str,
    limit: int,
    automatic_jobs: dict[str, dict[str, object]],
    get_spotify_access_token,
    fetch_imported_spotify_genre_rules,
) -> None:
    job = automatic_jobs[job_id]
    try:
        api_key = get_lastfm_api_key()
        tracks = list_tracks_for_automatic_classification(limit=limit)
        job.update({
            "status": "running",
            "phase": "lendo playlists do Spotify",
            "total": len(tracks),
            "processed": 0,
            "matched": 0,
            "current_track": None,
        })
        enabled_genres = list_genres(include_disabled=False)
        genre_ids_by_name = {
            str(genre["name"]): int(genre["id"])
            for genre in enabled_genres
        }

        spotify_access_token = await get_spotify_access_token()
        playlist_summaries, playlist_tracks_by_genre = fetch_imported_spotify_genre_rules()
        playlist_classifications = classify_tracks_with_spotify_playlists(
            tracks=tracks,
            playlist_tracks_by_genre=playlist_tracks_by_genre,
            genre_ids_by_name=genre_ids_by_name,
        )
        playlist_stored = store_automatic_classifications(
            classifications=playlist_classifications,
            provider="spotify_playlist",
        )
        playlist_matched_ids = {
            str(item["spotify_id"]) for item in playlist_classifications
        }
        record_automatic_attempts(
            spotify_ids=[str(track["spotify_id"]) for track in tracks],
            provider="spotify_playlist",
            matched_spotify_ids=playlist_matched_ids,
        )
        job.update({
            "phase": "consultando Last.fm",
            "processed": len(playlist_matched_ids),
            "matched": len(playlist_matched_ids),
            "spotify_genre_playlist_count": sum(
                1 for item in playlist_summaries if item["genre"]
            ),
        })

        async def update_progress(processed: int, track: dict[str, object]) -> None:
            job.update({
                "phase": "consultando Last.fm",
                "processed": min(len(tracks), len(playlist_matched_ids) + processed),
                "matched": len(playlist_matched_ids),
                "current_track": track.get("name"),
            })

        remaining_tracks = [
            track for track in tracks
            if str(track["spotify_id"]) not in playlist_matched_ids
        ]
        lastfm_classifications: list[dict[str, object]] = []
        if api_key:
            lastfm_classifications = await classify_tracks_with_lastfm(
                tracks=remaining_tracks,
                genre_ids_by_name=genre_ids_by_name,
                api_key=api_key,
                progress_callback=update_progress,
            )
        else:
            job.update({
                "phase": "sem Last.fm; usando Spotify e revisão manual",
                "processed": len(tracks),
            })
        lastfm_matched_ids = {
            str(classification["spotify_id"])
            for classification in lastfm_classifications
        }
        lastfm_stored = store_automatic_classifications(
            classifications=lastfm_classifications,
            provider="lastfm",
        )
        record_automatic_attempts(
            spotify_ids=[str(track["spotify_id"]) for track in remaining_tracks],
            provider="lastfm",
            matched_spotify_ids=lastfm_matched_ids,
        )

        spotify_classifications = await classify_tracks_with_spotify_artists(
            tracks=[
                track for track in remaining_tracks
                if str(track["spotify_id"]) not in lastfm_matched_ids
            ],
            genre_ids_by_name=genre_ids_by_name,
            access_token=spotify_access_token,
        )
        spotify_matched_ids = {
            str(classification["spotify_id"])
            for classification in spotify_classifications
        }
        record_automatic_attempts(
            spotify_ids=[str(track["spotify_id"]) for track in remaining_tracks],
            provider="spotify_artist",
            matched_spotify_ids=spotify_matched_ids,
        )
        spotify_stored = store_automatic_classifications(
            classifications=spotify_classifications,
            provider="spotify_artist",
        )

        matched_ids = playlist_matched_ids | lastfm_matched_ids | spotify_matched_ids
        job.update({
            "status": "completed",
            "phase": "concluído",
            "processed": len(tracks),
            "matched": len(matched_ids),
            "no_match": len(tracks) - len(matched_ids),
            "classification_count": (
                playlist_stored["classification_count"]
                + lastfm_stored["classification_count"]
                + spotify_stored["classification_count"]
            ),
            "progress": get_classification_progress(),
            "current_track": None,
        })
    except Exception as error:
        job.update({
            "status": "error",
            "phase": "erro",
            "error": str(error),
        })


