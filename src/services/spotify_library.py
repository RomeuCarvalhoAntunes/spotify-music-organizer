from collections.abc import Awaitable, Callable

from src.automatic_classification import map_spotify_playlist_to_genre
from src.database import import_library, list_imported_playlist_snapshots
from src.services.operations import update_operation


async def run_import_operation(
    operation_id: str,
    access_token: str,
    get_playlists: Callable[[str], Awaitable[list[dict]]],
    get_items: Callable[[str, str], Awaitable[list[dict]]],
) -> None:
    try:
        update_operation(
            operation_id,
            status="running",
            phase="listando playlists do Spotify",
        )
        playlists = await get_playlists(access_token)
        update_operation(
            operation_id,
            total=len(playlists),
            processed=0,
            phase="importando faixas",
        )
        playlist_items_by_id: dict[str, list[dict]] = {}
        for index, playlist in enumerate(playlists, start=1):
            playlist_items_by_id[playlist["id"]] = await get_items(
                access_token=access_token,
                playlist_id=playlist["id"],
            )
            update_operation(
                operation_id,
                processed=index,
                current_item=playlist.get("name"),
            )

        summary = import_library(playlists, playlist_items_by_id)
        update_operation(
            operation_id,
            status="completed",
            phase="concluído",
            processed=len(playlists),
            result=summary.to_dict(),
            current_item=None,
        )
    except Exception as error:
        update_operation(
            operation_id,
            status="error",
            phase="erro",
            error=str(error),
        )

def fetch_imported_spotify_genre_rules() -> tuple[
    list[dict[str, object]], dict[str, list[dict[str, object]]]
]:
    playlists = list_imported_playlist_snapshots()
    playlist_summaries: list[dict[str, object]] = []
    playlist_tracks_by_genre: dict[str, list[dict[str, object]]] = {}

    for playlist in playlists:
        genre_name = map_spotify_playlist_to_genre(str(playlist.get("name", "")))
        summary = {
            "id": playlist["id"],
            "name": playlist["name"],
            "track_count": playlist["track_count"],
            "spotify_url": playlist["spotify_url"],
            "genre": genre_name,
            "rule": (
                f"Classificar como {genre_name}"
                if genre_name
                else "Não usar como regra de gênero"
            ),
        }
        playlist_summaries.append(summary)
        if genre_name:
            playlist_tracks_by_genre.setdefault(genre_name, []).extend(
                playlist["items"]
            )

    return playlist_summaries, playlist_tracks_by_genre


