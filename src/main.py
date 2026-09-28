import os
import secrets
import sqlite3
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query, Response, status
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, RedirectResponse
from pydantic import BaseModel, Field

from src.automatic_classification import (
    classify_tracks_with_lastfm,
    classify_tracks_with_spotify_artists,
    get_lastfm_api_key,
)
from src.database import (
    create_connection,
    create_genre,
    apply_manual_classification,
    create_genre_rule,
    delete_genre,
    delete_genre_rule,
    get_genre,
    import_library,
    list_genre_rules,
    list_genres,
    list_track_genres,
    list_tracks_for_automatic_classification,
    get_classification_progress,
    generate_local_playlists,
    list_local_playlists,
    store_automatic_classifications,
    record_automatic_attempts,
    list_tracks_needing_review,
    rebuild_classifications,
    update_genre,
)
from src.spotify_auth import (
    add_expiration_information,
    build_authorization_url,
    exchange_code,
    generate_pkce_pair,
    get_current_user,
    get_current_user_playlists,
    get_playlist_items,
    is_access_token_expired,
    refresh_access_token,
)
from src.spotify_tokens import load_tokens, save_tokens


load_dotenv()

app = FastAPI(
    title="Spotify Music Organizer",
    description=(
        "A self-hosted application for organizing Spotify playlists "
        "by user-defined genres."
    ),
    version="0.1.0",
)

oauth_sessions: dict[str, str] = {}

STATIC_DIR = Path(__file__).parent / "static"


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

spotify_tokens: dict[str, dict] = {}


class GenreCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    description: str = Field(min_length=1, max_length=2000)
    enabled: bool = True


class GenreUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = Field(default=None, min_length=1, max_length=2000)
    enabled: bool | None = None


class GenreRuleCreateRequest(BaseModel):
    genre_id: int = Field(gt=0)
    resource_type: Literal["track", "album", "artist"]
    spotify_id: str = Field(min_length=1, max_length=100)


class ClassificationDecisionRequest(BaseModel):
    resource_type: Literal["track", "album", "artist"]
    spotify_id: str = Field(min_length=1, max_length=100)
    genre_ids: list[int] = Field(min_length=1)


# Load Spotify tokens from local storage into memory.
def load_spotify_tokens() -> dict[str, dict]:
    if not spotify_tokens:
        spotify_tokens.update(load_tokens())

    return spotify_tokens


# Persist the current Spotify tokens to local storage.
def persist_spotify_tokens() -> None:
    save_tokens(spotify_tokens)


# Return a valid Spotify access token, refreshing it when needed.
async def get_spotify_access_token() -> str:
    tokens = load_spotify_tokens().get("current_user")

    if not tokens:
        raise HTTPException(
            status_code=401,
            detail="Spotify is not connected.",
        )

    if not is_access_token_expired(tokens):
        return tokens["access_token"]

    refresh_token = tokens.get("refresh_token")

    if not refresh_token:
        raise HTTPException(
            status_code=401,
            detail="Spotify refresh token is not available.",
        )

    client_id = os.getenv("SPOTIFY_CLIENT_ID")

    if not client_id:
        raise HTTPException(
            status_code=500,
            detail="Spotify environment variables are not configured.",
        )

    refreshed_tokens = await refresh_access_token(
        client_id=client_id,
        refresh_token=refresh_token,
    )
    refreshed_tokens = add_expiration_information(refreshed_tokens)
    refreshed_tokens["refresh_token"] = refreshed_tokens.get(
        "refresh_token",
        refresh_token,
    )

    spotify_tokens["current_user"] = refreshed_tokens
    persist_spotify_tokens()

    return refreshed_tokens["access_token"]


# Return basic information about the application.
@app.get("/", response_class=FileResponse)
def home() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/status")
def application_status() -> dict[str, object]:
    return {
        "application": "Spotify Music Organizer",
        "status": "running",
        "spotify_connected": bool(load_spotify_tokens()),
        "automatic_provider_configured": bool(get_lastfm_api_key()),
    }


# Check whether the application is running correctly.
@app.get("/health")
def health_check() -> dict[str, str]:
    return {"status": "ok"}


# Start the Spotify OAuth authorization flow.
@app.get("/login")
def spotify_login() -> RedirectResponse:
    client_id = os.getenv("SPOTIFY_CLIENT_ID")
    redirect_uri = os.getenv("SPOTIFY_REDIRECT_URI")

    if not client_id or not redirect_uri:
        raise HTTPException(
            status_code=500,
            detail="Spotify environment variables are not configured.",
        )

    state = secrets.token_urlsafe(32)
    code_verifier, code_challenge = generate_pkce_pair()

    oauth_sessions[state] = code_verifier

    authorization_url = build_authorization_url(
        client_id=client_id,
        redirect_uri=redirect_uri,
        state=state,
        code_challenge=code_challenge,
    )

    return RedirectResponse(authorization_url)


# Handle the authorization response from Spotify.
@app.get("/callback")
async def spotify_callback(
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
) -> dict[str, object]:
    if error:
        raise HTTPException(
            status_code=400,
            detail=f"Spotify authorization failed: {error}",
        )

    if not code or not state:
        raise HTTPException(
            status_code=400,
            detail="Missing authorization code or state.",
        )

    code_verifier = oauth_sessions.pop(state, None)

    if not code_verifier:
        raise HTTPException(
            status_code=400,
            detail="Invalid or expired OAuth state.",
        )

    client_id = os.getenv("SPOTIFY_CLIENT_ID")
    redirect_uri = os.getenv("SPOTIFY_REDIRECT_URI")

    if not client_id or not redirect_uri:
        raise HTTPException(
            status_code=500,
            detail="Spotify environment variables are not configured.",
        )

    tokens = await exchange_code(
        client_id=client_id,
        redirect_uri=redirect_uri,
        code=code,
        code_verifier=code_verifier,
    )
    tokens = add_expiration_information(tokens)

    spotify_tokens["current_user"] = tokens
    persist_spotify_tokens()

    return {
        "status": "connected",
        "message": "Spotify authorization successful.",
    }


# Return information about the currently connected Spotify account.
@app.get("/me")
async def current_user() -> dict[str, object]:
    access_token = await get_spotify_access_token()
    profile = await get_current_user(access_token)

    return {
        "account_id": profile.get("account_id"),
        "display_name": profile.get("display_name"),
        "id": profile.get("id"),
        "spotify_url": profile.get("external_urls", {}).get("spotify"),
    }


# Return all playlists available to the currently authenticated Spotify user.
@app.get("/playlists")
async def current_user_playlists() -> dict[str, object]:
    access_token = await get_spotify_access_token()

    playlists = await get_current_user_playlists(
        access_token,
    )

    return {
        "total": len(playlists),
        "items": [
            {
                "id": playlist["id"],
                "name": playlist["name"],
                "public": playlist["public"],
                "owner": playlist["owner"]["display_name"],
                "track_count": playlist["items"]["total"],
                "spotify_url": playlist["external_urls"]["spotify"],
            }
            for playlist in playlists
        ],
    }


# Retrieve all tracks from a Spotify playlist without modifying it.
@app.get("/playlists/{playlist_id}/items")
async def playlist_items(playlist_id: str) -> dict[str, object]:
    access_token = await get_spotify_access_token()

    items = await get_playlist_items(
        access_token=access_token,
        playlist_id=playlist_id,
    )

    return {
        "playlist_id": playlist_id,
        "total": len(items),
        "items": [
            {
                "added_at": item.get("added_at"),
                "track": {
                    "id": item["item"]["id"],
                    "name": item["item"]["name"],
                    "artists": [
                        artist["name"]
                        for artist in item["item"]["artists"]
                    ],
                    "album": item["item"]["album"]["name"],
                    "release_date": item["item"]["album"]["release_date"],
                },
            }
            for item in items
            if item.get("item")
        ],
    }


# Import all Spotify playlists and their tracks into the local SQLite database.
@app.post("/imports")
async def import_spotify_library() -> dict[str, int]:
    access_token = await get_spotify_access_token()
    playlists = await get_current_user_playlists(access_token)
    playlist_items_by_id = {}

    for playlist in playlists:
        playlist_items_by_id[playlist["id"]] = await get_playlist_items(
            access_token=access_token,
            playlist_id=playlist["id"],
        )

    import_summary = import_library(playlists, playlist_items_by_id)

    return import_summary.to_dict()


# List local genres configured by the user.
@app.get("/genres")
def genres(include_disabled: bool = True) -> dict[str, object]:
    items = list_genres(include_disabled=include_disabled)

    return {"total": len(items), "items": items}


# Create a local genre without performing any Spotify operation.
@app.post("/genres", status_code=status.HTTP_201_CREATED)
def create_local_genre(genre: GenreCreateRequest) -> dict[str, object]:
    try:
        return create_genre(
            name=genre.name,
            description=genre.description,
            enabled=genre.enabled,
        )
    except sqlite3.IntegrityError as error:
        raise HTTPException(
            status_code=409,
            detail="A genre with this name already exists.",
        ) from error


# Return one local genre by its identifier.
@app.get("/genres/{genre_id}")
def genre(genre_id: int) -> dict[str, object]:
    item = get_genre(genre_id)

    if not item:
        raise HTTPException(status_code=404, detail="Genre was not found.")

    return item


# Edit or enable or disable a local genre.
@app.patch("/genres/{genre_id}")
def update_local_genre(
    genre_id: int,
    genre_update: GenreUpdateRequest,
) -> dict[str, object]:
    if not genre_update.model_fields_set:
        raise HTTPException(status_code=400, detail="No genre fields were provided.")

    try:
        item = update_genre(
            genre_id=genre_id,
            name=genre_update.name,
            description=genre_update.description,
            enabled=genre_update.enabled,
        )
    except sqlite3.IntegrityError as error:
        raise HTTPException(
            status_code=409,
            detail="A genre with this name already exists.",
        ) from error

    if not item:
        raise HTTPException(status_code=404, detail="Genre was not found.")

    return item


# Delete a local genre and its local configuration.
@app.delete("/genres/{genre_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_local_genre(genre_id: int) -> Response:
    if not delete_genre(genre_id):
        raise HTTPException(status_code=404, detail="Genre was not found.")

    return Response(status_code=status.HTTP_204_NO_CONTENT)


# List reusable local classification rules.
@app.get("/genre-rules")
def genre_rules() -> dict[str, object]:
    items = list_genre_rules()

    return {"total": len(items), "items": items}


# Create a local rule for a track, album, or artist.
@app.post("/genre-rules", status_code=status.HTTP_201_CREATED)
def create_local_genre_rule(
    genre_rule: GenreRuleCreateRequest,
) -> dict[str, object]:
    if not get_genre(genre_rule.genre_id):
        raise HTTPException(status_code=404, detail="Genre was not found.")

    try:
        item = create_genre_rule(
            genre_id=genre_rule.genre_id,
            resource_type=genre_rule.resource_type,
            spotify_id=genre_rule.spotify_id,
        )
    except sqlite3.IntegrityError as error:
        raise HTTPException(
            status_code=409,
            detail="This genre rule already exists.",
        ) from error

    if not item:
        raise HTTPException(status_code=500, detail="Genre rule was not created.")

    return item


# Delete a reusable local rule.
@app.delete("/genre-rules/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_local_genre_rule(rule_id: int) -> Response:
    if not delete_genre_rule(rule_id):
        raise HTTPException(status_code=404, detail="Genre rule was not found.")

    return Response(status_code=status.HTTP_204_NO_CONTENT)


# Apply a manual classification decision and persist it as reusable rules.
@app.post("/classification/decisions")
def create_classification_decision(
    decision: ClassificationDecisionRequest,
) -> dict[str, object]:
    enabled_genre_ids = {
        int(item["id"]) for item in list_genres(include_disabled=False)
    }
    selected_genre_ids = set(decision.genre_ids)

    if not selected_genre_ids.issubset(enabled_genre_ids):
        raise HTTPException(
            status_code=404,
            detail="One or more selected genres were not found or are disabled.",
        )

    try:
        return apply_manual_classification(
            resource_type=decision.resource_type,
            spotify_id=decision.spotify_id,
            genre_ids=decision.genre_ids,
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


# Generate local playlists by genre without writing to Spotify.
@app.post("/local-playlists")
def create_local_playlists() -> dict[str, object]:
    return generate_local_playlists()


# List local playlists and their tracks in playback order.
@app.get("/local-playlists")
def local_playlists() -> dict[str, object]:
    items = list_local_playlists()
    return {"total": len(items), "items": items}


# Return library classification progress for the web interface.
@app.get("/classifications/progress")
def classification_progress() -> dict[str, int]:
    return get_classification_progress()


# Classify a batch of pending tracks using Last.fm tags.
@app.post("/classifications/automatic")
async def automatic_classification(
    limit: int = Query(default=25, ge=1, le=100),
) -> dict[str, object]:
    api_key = get_lastfm_api_key()
    if not api_key:
        raise HTTPException(
            status_code=503,
            detail="LASTFM_API_KEY is not configured.",
        )

    tracks = list_tracks_for_automatic_classification(limit=limit)
    enabled_genres = list_genres(include_disabled=False)
    genre_ids_by_name = {
        str(genre["name"]): int(genre["id"])
        for genre in enabled_genres
    }
    lastfm_classifications = await classify_tracks_with_lastfm(
        tracks=tracks,
        genre_ids_by_name=genre_ids_by_name,
        api_key=api_key,
    )
    lastfm_matched_ids = {
        str(classification["spotify_id"])
        for classification in lastfm_classifications
    }
    lastfm_stored = store_automatic_classifications(
        classifications=lastfm_classifications,
        provider="lastfm",
    )
    record_automatic_attempts(
        spotify_ids=[str(track["spotify_id"]) for track in tracks],
        provider="lastfm",
        matched_spotify_ids=lastfm_matched_ids,
    )

    spotify_classifications: list[dict[str, object]] = []
    try:
        spotify_access_token = await get_spotify_access_token()
        spotify_classifications = await classify_tracks_with_spotify_artists(
            tracks=[
                track
                for track in tracks
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
            spotify_ids=[str(track["spotify_id"]) for track in tracks],
            provider="spotify_artist",
            matched_spotify_ids=spotify_matched_ids,
        )
        spotify_stored = store_automatic_classifications(
            classifications=spotify_classifications,
            provider="spotify_artist",
        )
    except HTTPException:
        spotify_stored = {"classified_track_count": 0, "classification_count": 0}

    matched_track_ids = lastfm_matched_ids | {
        str(classification["spotify_id"])
        for classification in spotify_classifications
    }

    return {
        "provider": "lastfm+spotify_artist",
        "processed_track_count": len(tracks),
        "matched_track_count": len(matched_track_ids),
        "no_match_track_count": len(tracks) - len(matched_track_ids),
        "classification_count": (
            lastfm_stored["classification_count"]
            + spotify_stored["classification_count"]
        ),
        "progress": get_classification_progress(),
    }


# Recalculate local classifications from the currently configured rules.
@app.post("/classifications/rebuild")
def rebuild_local_classifications() -> dict[str, int]:
    connection = None

    try:
        connection = create_connection()

        with connection:
            return rebuild_classifications(connection)
    finally:
        if connection:
            connection.close()


# List imported tracks that still need a user classification decision.
@app.get("/classification/review")
def classification_review(
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> dict[str, object]:
    return list_tracks_needing_review(limit=limit, offset=offset)


# Return current local genre classifications for one imported Spotify track.
@app.get("/tracks/{spotify_id}/genres")
def track_genres(spotify_id: str) -> dict[str, object]:
    items = list_track_genres(spotify_id)

    if items is None:
        raise HTTPException(status_code=404, detail="Track was not found.")

    return {"spotify_id": spotify_id, "total": len(items), "items": items}
