import os
import unicodedata
from collections.abc import Awaitable, Callable, Iterable

import httpx

from src.spotify_auth import get_artists


LASTFM_ENDPOINT = "https://ws.audioscrobbler.com/2.0/"
PROVIDER_NAME = "lastfm"


def normalize_tag(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    without_accents = "".join(
        character for character in normalized
        if not unicodedata.combining(character)
    )
    return " ".join(
        without_accents.lower().replace("-", " ").replace("/", " ").split()
    )


SPOTIFY_PLAYLIST_GENRE_ALIASES: dict[str, str] = {
    "alternativa": "Alternativa",
    "axe": "Axé",
    "blues": "Jazz / Blues",
    "dance": "Dance",
    "eletronica": "Eletrônica",
    "dubstep": "Dubstep",
    "forro": "Forró",
    "funk": "Funk",
    "best do funk": "Funk",
    "hip hop rap": "Hip-Hop",
    "latina": "Latina",
    "pop": "Pop",
    "rap nacional": "Rap Nacional",
    "reggae": "Reggae",
    "soundtrack": "Soundtrack",
    "sertanejo": "Sertanejo",
    "rock": "Rock",
    "samba": "Samba",
    "samba de domingo": "Samba",
    "mpb": "MPB",
    "r&b soul": "R&B / Soul",
    "modao": "Modão",
    "xote": "Xote",
    "trap": "Trap",
    "pisadinha": "Pisadinha",
    "pagode v2": "Pagode",
    "pagode com samba": "Pagode",
}


# Map only playlists whose names explicitly represent a genre.
def map_spotify_playlist_to_genre(playlist_name: str) -> str | None:
    return SPOTIFY_PLAYLIST_GENRE_ALIASES.get(normalize_tag(playlist_name))


# Build classifications from the user's own genre playlists.
def classify_tracks_with_spotify_playlists(
    tracks: list[dict[str, object]],
    playlist_tracks_by_genre: dict[str, list[dict[str, object]]],
    genre_ids_by_name: dict[str, int],
) -> list[dict[str, object]]:
    tracks_by_id = {str(track["spotify_id"]): track for track in tracks}
    classifications: dict[str, dict[str, object]] = {}

    for genre_name, playlist_items in playlist_tracks_by_genre.items():
        genre_id = genre_ids_by_name.get(genre_name)
        if not genre_id:
            continue
        for item in playlist_items:
            track = item.get("item") or item.get("track") or {}
            spotify_id = str(track.get("id", ""))
            if spotify_id not in tracks_by_id:
                continue
            entry = classifications.setdefault(
                spotify_id,
                {"spotify_id": spotify_id, "genre_ids": [], "evidence": []},
            )
            entry["genre_ids"].append(genre_id)
            entry["evidence"].append(genre_name)

    return [
        {
            "spotify_id": spotify_id,
            "genre_ids": list(dict.fromkeys(entry["genre_ids"])),
            "confidence": 1.0,
            "evidence": "Playlist Spotify: " + ", ".join(dict.fromkeys(entry["evidence"])),
        }
        for spotify_id, entry in classifications.items()
    ]


GENRE_TAG_ALIASES: dict[str, tuple[str, ...]] = {
    "Alternativa": ("alternative", "indie"),
    "Axé": ("axe",),
    "Jazz / Blues": ("jazz", "blues"),
    "Dance": ("dance", "dance pop", "edm"),
    "Dubstep": ("dubstep",),
    "Eletrônica": ("electronic", "house", "techno", "trance", "drum and bass", "ambient"),
    "Forró": ("forro",),
    "Funk": ("funk", "baile funk", "funk carioca", "brazilian funk"),
    "Hip-Hop": ("hip hop",),
    "Latina": ("latin", "reggaeton", "salsa", "bachata", "cumbia"),
    "Modão": ("modao", "sertanejo raiz"),
    "MPB": ("mpb",),
    "Pagode": ("pagode",),
    "Pisadinha": ("pisadinha",),
    "Pop": ("pop",),
    "Rap Nacional": ("rap nacional", "brazilian rap", "brazilian hip hop"),
    "R&B / Soul": ("r&b", "soul", "rhythm and blues"),
    "Reggae": ("reggae",),
    "Rock": ("rock",),
    "Country Rock": ("country rock",),
    "Samba": ("samba",),
    "Sertanejo": ("sertanejo", "country brasileiro"),
    "Soundtrack": ("soundtrack", "film score"),
    "Trap": ("trap",),
    "Xote": ("xote",),
}


def get_lastfm_api_key() -> str | None:
    return os.getenv("LASTFM_API_KEY") or None


async def fetch_lastfm_tags(
    client: httpx.AsyncClient,
    artist: str,
    track: str,
    api_key: str,
) -> list[str]:
    response = await client.get(
        LASTFM_ENDPOINT,
        params={
            "method": "track.getInfo",
            "api_key": api_key,
            "artist": artist,
            "track": track,
            "autocorrect": 1,
            "format": "json",
        },
    )
    response.raise_for_status()
    payload = response.json()
    tags = payload.get("track", {}).get("toptags", {}).get("tag", [])
    if isinstance(tags, dict):
        tags = [tags]
    tag_names = [
        str(tag.get("name", ""))
        for tag in tags
        if isinstance(tag, dict) and tag.get("name")
    ]
    if tag_names:
        return tag_names

    artist_response = await client.get(
        LASTFM_ENDPOINT,
        params={
            "method": "artist.getTopTags",
            "api_key": api_key,
            "artist": artist,
            "autocorrect": 1,
            "format": "json",
        },
    )
    artist_response.raise_for_status()
    artist_payload = artist_response.json()
    artist_tags = artist_payload.get("toptags", {}).get("tag", [])
    if isinstance(artist_tags, dict):
        artist_tags = [artist_tags]
    return [
        str(tag.get("name", ""))
        for tag in artist_tags
        if isinstance(tag, dict) and tag.get("name")
    ]


def map_tags_to_genres(
    tags: Iterable[str],
    genre_ids_by_name: dict[str, int],
) -> list[int]:
    normalized_tags = {normalize_tag(tag) for tag in tags}
    matches: list[int] = []

    for genre_name, aliases in GENRE_TAG_ALIASES.items():
        genre_id = genre_ids_by_name.get(genre_name)
        if not genre_id:
            continue
        if any(
            normalize_tag(alias) in normalized_tag
            or normalized_tag in normalize_tag(alias)
            for alias in aliases
            for normalized_tag in normalized_tags
        ):
            matches.append(genre_id)

    return matches


async def classify_tracks_with_lastfm(
    tracks: list[dict[str, object]],
    genre_ids_by_name: dict[str, int],
    api_key: str,
    progress_callback: Callable[[int, dict[str, object]], Awaitable[None]] | None = None,
) -> list[dict[str, object]]:
    classifications: list[dict[str, object]] = []

    async with httpx.AsyncClient(timeout=15.0) as client:
        for index, track in enumerate(tracks):
            artists = track.get("artists") or []
            artist_name = (
                str(artists[0].get("name"))
                if isinstance(artists, list)
                and artists
                and isinstance(artists[0], dict)
                else ""
            )
            track_name = str(track.get("name", ""))
            if not artist_name or not track_name:
                continue

            try:
                tags = await fetch_lastfm_tags(
                    client,
                    artist_name,
                    track_name,
                    api_key,
                )
            except (httpx.HTTPError, ValueError):
                tags = []

            genre_ids = map_tags_to_genres(tags, genre_ids_by_name)
            if genre_ids:
                classifications.append(
                    {
                        "spotify_id": track["spotify_id"],
                        "genre_ids": genre_ids,
                        "confidence": min(0.95, 0.55 + 0.08 * len(genre_ids)),
                        "evidence": ", ".join(tags[:8]),
                    }
                )
            if progress_callback:
                await progress_callback(index + 1, track)

    return classifications

async def classify_tracks_with_spotify_artists(
    tracks: list[dict[str, object]],
    genre_ids_by_name: dict[str, int],
    access_token: str,
) -> list[dict[str, object]]:
    artist_ids = {
        str(artist["id"])
        for track in tracks
        for artist in (track.get("artists") or [])
        if isinstance(artist, dict) and artist.get("id")
    }
    artists_by_id: dict[str, dict] = {}

    for start in range(0, len(artist_ids), 50):
        batch = list(artist_ids)[start:start + 50]
        try:
            artists = await get_artists(access_token, batch)
        except httpx.HTTPError:
            continue
        artists_by_id.update(
            {
                str(artist["id"]): artist
                for artist in artists
                if artist.get("id")
            }
        )

    classifications: list[dict[str, object]] = []
    for track in tracks:
        genres = [
            genre
            for artist in (track.get("artists") or [])
            if isinstance(artist, dict)
            for genre in artists_by_id.get(str(artist.get("id")), {}).get(
                "genres",
                [],
            )
        ]
        genre_ids = map_tags_to_genres(genres, genre_ids_by_name)
        if genre_ids:
            classifications.append(
                {
                    "spotify_id": track["spotify_id"],
                    "genre_ids": genre_ids,
                    "confidence": min(0.85, 0.60 + 0.05 * len(genre_ids)),
                    "evidence": ", ".join(genres[:8]),
                }
            )

    return classifications
