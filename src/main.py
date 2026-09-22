"""Application entry point for the Spotify Music Organizer."""

from fastapi import FastAPI


app = FastAPI(
    title="Spotify Music Organizer",
    description=(
        "A self-hosted application for organizing Spotify playlists "
        "by user-defined genres."
    ),
    version="0.1.0",
)


# Return basic information about the application.
@app.get("/")
def home() -> dict[str, object]:
    return {
        "application": "Spotify Music Organizer",
        "status": "running",
        "spotify_connected": False,
    }


# Check whether the application is running correctly.
@app.get("/health")
def health_check() -> dict[str, str]:
    return {"status": "ok"}