"""Spotify OAuth authentication utilities."""

import base64
import hashlib
import secrets
from urllib.parse import urlencode

import httpx


SPOTIFY_AUTHORIZE_URL = "https://accounts.spotify.com/authorize"
SPOTIFY_TOKEN_URL = "https://accounts.spotify.com/api/token"

SCOPES = [
    "user-read-private",
    "playlist-read-private",
    "playlist-modify-private",
    "playlist-modify-public",
]

# Generate the PKCE code verifier and its corresponding challenge.
def generate_pkce_pair() -> tuple[str, str]:
    code_verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(code_verifier.encode()).digest()
    code_challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()

    return code_verifier, code_challenge


# Build the Spotify authorization URL for the current user.
def build_authorization_url(
    client_id: str,
    redirect_uri: str,
    state: str,
    code_challenge: str,
) -> str:
    params = {
        "response_type": "code",
        "client_id": client_id,
        "scope": " ".join(SCOPES),
        "redirect_uri": redirect_uri,
        "state": state,
        "code_challenge_method": "S256",
        "code_challenge": code_challenge,
    }

    return f"{SPOTIFY_AUTHORIZE_URL}?{urlencode(params)}"


# Exchange the authorization code for Spotify access and refresh tokens.
async def exchange_code(
    client_id: str,
    redirect_uri: str,
    code: str,
    code_verifier: str,
) -> dict:
    data = {
        "grant_type": "authorization_code",
        "client_id": client_id,
        "code": code,
        "redirect_uri": redirect_uri,
        "code_verifier": code_verifier,
    }

    async with httpx.AsyncClient() as client:
        response = await client.post(
            SPOTIFY_TOKEN_URL,
            data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )

    response.raise_for_status()
    return response.json()

# Retrieve the profile of the currently authenticated Spotify user.
async def get_current_user(access_token: str) -> dict:
    async with httpx.AsyncClient() as client:
        response = await client.get(
            "https://api.spotify.com/v1/me",
            headers={"Authorization": f"Bearer {access_token}"},
        )

    response.raise_for_status()
    return response.json()

# Retrieve all playlists available to the currently authenticated Spotify user.
async def get_current_user_playlists(access_token: str) -> list[dict]:
    playlists = []
    offset = 0
    limit = 50

    async with httpx.AsyncClient() as client:
        while True:
            response = await client.get(
                "https://api.spotify.com/v1/me/playlists",
                params={
                    "limit": limit,
                    "offset": offset,
                },
                headers={"Authorization": f"Bearer {access_token}"},
            )

            response.raise_for_status()
            data = response.json()

            playlists.extend(data["items"])

            if not data["next"]:
                break

            offset += limit

    return playlists

# Retrieve all items from a Spotify playlist using pagination.
async def get_playlist_items(
    access_token: str,
    playlist_id: str,
) -> list[dict]:
    items = []
    offset = 0
    limit = 50

    async with httpx.AsyncClient() as client:
        while True:
            response = await client.get(
                f"https://api.spotify.com/v1/playlists/{playlist_id}/items",
                params={
                    "limit": limit,
                    "offset": offset,
                },
                headers={"Authorization": f"Bearer {access_token}"},
            )

            response.raise_for_status()
            data = response.json()

            items.extend(data["items"])

            if not data["next"]:
                break

            offset += limit

    return items