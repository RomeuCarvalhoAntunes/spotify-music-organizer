"""Application entry point for the Spotify Music Organizer."""

import os
import secrets

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import RedirectResponse

from src.spotify_auth import (
    build_authorization_url,
    exchange_code,
    generate_pkce_pair,
    get_current_user,
    get_current_user_playlists,
    get_playlist_items,
)


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


# Return basic information about the application.
@app.get("/")
def home() -> dict[str, object]:
    return {
        "application": "Spotify Music Organizer",
        "status": "running",
        "spotify_connected": bool(spotify_tokens),
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

    spotify_tokens["current_user"] = tokens

    return {
        "status": "connected",
        "message": "Spotify authorization successful.",
    }

# Return information about the currently connected Spotify account.
@app.get("/me")
async def current_user() -> dict[str, object]:
    tokens = spotify_tokens.get("current_user")

    if not tokens:
        raise HTTPException(
            status_code=401,
            detail="Spotify is not connected.",
        )

    profile = await get_current_user(tokens["access_token"])

    return {
        "account_id": profile.get("account_id"),
        "display_name": profile.get("display_name"),
        "id": profile.get("id"),
        "spotify_url": profile.get("external_urls", {}).get("spotify"),
    }

# Return all playlists available to the currently authenticated Spotify user.
@app.get("/playlists")
async def current_user_playlists() -> dict[str, object]:
    tokens = spotify_tokens.get("current_user")

    if not tokens:
        raise HTTPException(
            status_code=401,
            detail="Spotify is not connected.",
        )

    playlists = await get_current_user_playlists(
        tokens["access_token"],
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
    tokens = spotify_tokens.get("current_user")

    if not tokens:
        raise HTTPException(
            status_code=401,
            detail="Spotify is not connected.",
        )

    items = await get_playlist_items(
        access_token=tokens["access_token"],
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