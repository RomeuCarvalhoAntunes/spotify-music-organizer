import os
import unicodedata
from collections.abc import Iterable

import httpx


LASTFM_ENDPOINT = "https://ws.audioscrobbler.com/2.0/"
PROVIDER_NAME = "lastfm"


def normalize_tag(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    without_accents = "".join(
        character for character in normalized
        if not unicodedata.combining(character)
    )
    return " ".join(without_accents.lower().replace("-", " ").split())


GENRE_TAG_ALIASES: dict[str, tuple[str, ...]] = {
    "Alternativa": ("alternative", "indie"),
    "Axé": ("axe",),
    "Jazz / Blues": ("jazz", "blues"),
    "Dance": ("dance", "dance pop", "edm"),
    "Dubstep": ("dubstep",),
    "Eletrônica": ("electronic", "house", "techno", "trance", "drum and bass", "ambient"),
    "Forró": ("forro",),
    "Funk": ("funk",),
    "Hip-Hop": ("hip hop",),
    "Latina": ("latin", "reggaeton", "salsa", "bachata", "cumbia"),
    "Modão": ("modao", "sertanejo raiz"),
    "MPB": ("mpb",),
    "Pagode": ("pagode",),
    "Pisadinha": ("pisadinha",),
    "Pop": ("pop",),
    "Rap Nacional": ("rap nacional", "brazilian rap"),
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
    return [
        str(tag.get("name", ""))
        for tag in tags
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
) -> list[dict[str, object]]:
    classifications: list[dict[str, object]] = []

    async with httpx.AsyncClient(timeout=15.0) as client:
        for track in tracks:
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
                continue

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

    return classifications
