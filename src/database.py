import json
import os
import sqlite3
from dataclasses import asdict, dataclass
from pathlib import Path


DEFAULT_DATABASE_PATH = "/app/data/spotify_music_organizer.db"


@dataclass(frozen=True)
class ImportSummary:
    import_id: int
    playlist_count: int
    playlist_track_count: int
    skipped_item_count: int

    # Return the import result in a format suitable for API responses.
    def to_dict(self) -> dict[str, int]:
        return asdict(self)


# Resolve the SQLite database path from configuration.
def get_database_path() -> Path:
    return Path(os.getenv("SPOTIFY_DATABASE_PATH", DEFAULT_DATABASE_PATH))


# Create the local database connection and ensure its schema exists.
def create_connection(path: Path | None = None) -> sqlite3.Connection:
    database_path = path or get_database_path()
    database_path.parent.mkdir(parents=True, exist_ok=True)

    connection = sqlite3.connect(database_path)
    connection.execute("PRAGMA foreign_keys = ON")
    initialize_database(connection)

    return connection


# Create the tables used to persist imported Spotify library data.
def initialize_database(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS imports (
            id INTEGER PRIMARY KEY,
            started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            completed_at TEXT,
            playlist_count INTEGER NOT NULL DEFAULT 0,
            playlist_track_count INTEGER NOT NULL DEFAULT 0,
            skipped_item_count INTEGER NOT NULL DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS playlists (
            id INTEGER PRIMARY KEY,
            spotify_id TEXT NOT NULL UNIQUE,
            name TEXT NOT NULL,
            public INTEGER,
            owner_spotify_id TEXT,
            owner_display_name TEXT,
            spotify_url TEXT,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS tracks (
            id INTEGER PRIMARY KEY,
            spotify_id TEXT NOT NULL UNIQUE,
            name TEXT NOT NULL,
            album_name TEXT,
            album_spotify_id TEXT,
            release_date TEXT,
            artists_json TEXT NOT NULL,
            duration_ms INTEGER,
            is_explicit INTEGER,
            spotify_uri TEXT,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS playlist_tracks (
            playlist_id INTEGER NOT NULL,
            track_id INTEGER NOT NULL,
            added_at TEXT,
            import_id INTEGER NOT NULL,
            PRIMARY KEY (playlist_id, track_id),
            FOREIGN KEY (playlist_id) REFERENCES playlists(id),
            FOREIGN KEY (track_id) REFERENCES tracks(id),
            FOREIGN KEY (import_id) REFERENCES imports(id)
        );
        """,
    )
    connection.commit()


# Import all fetched Spotify playlist data into the local SQLite library.
def import_library(
    playlists: list[dict],
    playlist_items: dict[str, list[dict]],
    path: Path | None = None,
) -> ImportSummary:
    connection = create_connection(path)

    try:
        with connection:
            cursor = connection.execute("INSERT INTO imports DEFAULT VALUES")
            import_id = cursor.lastrowid
            playlist_track_count = 0
            skipped_item_count = 0

            for playlist in playlists:
                playlist_spotify_id = playlist["id"]
                playlist_id = upsert_playlist(connection, playlist)
                imported_track_ids: set[int] = set()
                connection.execute(
                    "DELETE FROM playlist_tracks WHERE playlist_id = ?",
                    (playlist_id,),
                )

                for item in playlist_items.get(playlist_spotify_id, []):
                    track = item.get("item")

                    if not is_supported_track(track):
                        skipped_item_count += 1
                        continue

                    track_id = upsert_track(connection, track)
                    connection.execute(
                        """
                        INSERT INTO playlist_tracks (
                            playlist_id,
                            track_id,
                            added_at,
                            import_id
                        )
                        VALUES (?, ?, ?, ?)
                        ON CONFLICT(playlist_id, track_id) DO UPDATE SET
                            added_at = excluded.added_at,
                            import_id = excluded.import_id
                        """,
                        (
                            playlist_id,
                            track_id,
                            item.get("added_at"),
                            import_id,
                        ),
                    )
                    if track_id not in imported_track_ids:
                        playlist_track_count += 1
                        imported_track_ids.add(track_id)

            connection.execute(
                """
                UPDATE imports
                SET completed_at = CURRENT_TIMESTAMP,
                    playlist_count = ?,
                    playlist_track_count = ?,
                    skipped_item_count = ?
                WHERE id = ?
                """,
                (
                    len(playlists),
                    playlist_track_count,
                    skipped_item_count,
                    import_id,
                ),
            )
    finally:
        connection.close()

    return ImportSummary(
        import_id=import_id,
        playlist_count=len(playlists),
        playlist_track_count=playlist_track_count,
        skipped_item_count=skipped_item_count,
    )


# Return whether an item can be stored as a Spotify music track.
def is_supported_track(track: object) -> bool:
    return (
        isinstance(track, dict)
        and track.get("type") == "track"
        and isinstance(track.get("id"), str)
    )


# Insert or update a playlist and return its local identifier.
def upsert_playlist(connection: sqlite3.Connection, playlist: dict) -> int:
    owner = playlist.get("owner") or {}
    external_urls = playlist.get("external_urls") or {}

    connection.execute(
        """
        INSERT INTO playlists (
            spotify_id,
            name,
            public,
            owner_spotify_id,
            owner_display_name,
            spotify_url,
            updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(spotify_id) DO UPDATE SET
            name = excluded.name,
            public = excluded.public,
            owner_spotify_id = excluded.owner_spotify_id,
            owner_display_name = excluded.owner_display_name,
            spotify_url = excluded.spotify_url,
            updated_at = CURRENT_TIMESTAMP
        """,
        (
            playlist["id"],
            playlist["name"],
            convert_boolean(playlist.get("public")),
            owner.get("id"),
            owner.get("display_name"),
            external_urls.get("spotify"),
        ),
    )

    return get_local_id(connection, "playlists", playlist["id"])


# Insert or update a track and return its local identifier.
def upsert_track(connection: sqlite3.Connection, track: dict) -> int:
    album = track.get("album") or {}
    external_urls = track.get("external_urls") or {}
    artists = track.get("artists") or []

    connection.execute(
        """
        INSERT INTO tracks (
            spotify_id,
            name,
            album_name,
            album_spotify_id,
            release_date,
            artists_json,
            duration_ms,
            is_explicit,
            spotify_uri,
            updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(spotify_id) DO UPDATE SET
            name = excluded.name,
            album_name = excluded.album_name,
            album_spotify_id = excluded.album_spotify_id,
            release_date = excluded.release_date,
            artists_json = excluded.artists_json,
            duration_ms = excluded.duration_ms,
            is_explicit = excluded.is_explicit,
            spotify_uri = excluded.spotify_uri,
            updated_at = CURRENT_TIMESTAMP
        """,
        (
            track["id"],
            track["name"],
            album.get("name"),
            album.get("id"),
            album.get("release_date"),
            json.dumps(artists),
            track.get("duration_ms"),
            convert_boolean(track.get("explicit")),
            external_urls.get("spotify"),
        ),
    )

    return get_local_id(connection, "tracks", track["id"])


# Retrieve the numeric local identifier for a Spotify resource.
def get_local_id(
    connection: sqlite3.Connection,
    table_name: str,
    spotify_id: str,
) -> int:
    row = connection.execute(
        f"SELECT id FROM {table_name} WHERE spotify_id = ?",
        (spotify_id,),
    ).fetchone()

    if not row:
        raise RuntimeError("Spotify resource was not persisted.")

    return int(row[0])


# Convert optional Spotify boolean values for SQLite storage.
def convert_boolean(value: object) -> int | None:
    if value is None:
        return None

    return int(bool(value))
