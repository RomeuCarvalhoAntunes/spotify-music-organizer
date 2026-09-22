import os
import secrets

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import RedirectResponse

from src.database import import_library
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
spotify_tokens: dict[str, dict] = {}


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
@app.get("/")
def home() -> dict[str, object]:
    return {
        "application": "Spotify Music Organizer",
        "status": "running",
        "spotify_connected": bool(load_spotify_tokens()),
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
