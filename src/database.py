import json
import os
import sqlite3
from dataclasses import asdict, dataclass
from pathlib import Path

from src.default_genres import INITIAL_GENRES


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

        CREATE TABLE IF NOT EXISTS application_metadata (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS genres (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL COLLATE NOCASE UNIQUE,
            description TEXT NOT NULL,
            enabled INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS genre_rules (
            id INTEGER PRIMARY KEY,
            genre_id INTEGER NOT NULL,
            resource_type TEXT NOT NULL CHECK (
                resource_type IN ('track', 'album', 'artist')
            ),
            spotify_id TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (genre_id, resource_type, spotify_id),
            FOREIGN KEY (genre_id) REFERENCES genres(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS track_genres (
            track_id INTEGER NOT NULL,
            genre_id INTEGER NOT NULL,
            source TEXT NOT NULL CHECK (
                source IN ('track_rule', 'album_rule', 'artist_rule')
            ),
            confidence REAL NOT NULL,
            classified_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (track_id, genre_id),
            FOREIGN KEY (track_id) REFERENCES tracks(id) ON DELETE CASCADE,
            FOREIGN KEY (genre_id) REFERENCES genres(id) ON DELETE CASCADE
        );
        """,
    )
    seed_initial_genres(connection)
    connection.commit()


# Seed the initial user-editable genres only when the database is first created.
def seed_initial_genres(connection: sqlite3.Connection) -> None:
    seed_marker = connection.execute(
        "SELECT value FROM application_metadata WHERE key = ?",
        ("initial_genres_seeded",),
    ).fetchone()

    if seed_marker:
        return

    connection.executemany(
        """
        INSERT INTO genres (name, description)
        VALUES (:name, :description)
        """,
        INITIAL_GENRES,
    )
    connection.execute(
        """
        INSERT INTO application_metadata (key, value)
        VALUES (?, ?)
        """,
        ("initial_genres_seeded", "true"),
    )


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


# Return the configured genres, optionally including disabled entries.
def list_genres(
    include_disabled: bool = True,
    path: Path | None = None,
) -> list[dict[str, object]]:
    connection = create_connection(path)

    try:
        query = "SELECT * FROM genres"

        if not include_disabled:
            query += " WHERE enabled = 1"

        rows = connection.execute(f"{query} ORDER BY name COLLATE NOCASE").fetchall()
        return [genre_row_to_dict(row) for row in rows]
    finally:
        connection.close()


# Return a configured genre by its local identifier.
def get_genre(genre_id: int, path: Path | None = None) -> dict[str, object] | None:
    connection = create_connection(path)

    try:
        row = connection.execute(
            "SELECT * FROM genres WHERE id = ?",
            (genre_id,),
        ).fetchone()

        if not row:
            return None

        return genre_row_to_dict(row)
    finally:
        connection.close()


# Create a local user-configured genre.
def create_genre(
    name: str,
    description: str,
    enabled: bool,
    path: Path | None = None,
) -> dict[str, object]:
    connection = create_connection(path)

    try:
        with connection:
            cursor = connection.execute(
                """
                INSERT INTO genres (name, description, enabled)
                VALUES (?, ?, ?)
                """,
                (name, description, convert_boolean(enabled)),
            )
            genre_id = cursor.lastrowid

        return get_genre_from_connection(connection, genre_id)
    finally:
        connection.close()


# Update the editable fields of a local genre.
def update_genre(
    genre_id: int,
    name: str | None,
    description: str | None,
    enabled: bool | None,
    path: Path | None = None,
) -> dict[str, object] | None:
    connection = create_connection(path)

    try:
        current_genre = get_genre_from_connection(connection, genre_id)

        if not current_genre:
            return None

        updated_name = name if name is not None else current_genre["name"]
        updated_description = (
            description
            if description is not None
            else current_genre["description"]
        )
        updated_enabled = enabled if enabled is not None else current_genre["enabled"]

        with connection:
            connection.execute(
                """
                UPDATE genres
                SET name = ?,
                    description = ?,
                    enabled = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (
                    updated_name,
                    updated_description,
                    convert_boolean(updated_enabled),
                    genre_id,
                ),
            )
            rebuild_classifications(connection)

        return get_genre_from_connection(connection, genre_id)
    finally:
        connection.close()


# Delete a local genre and its local rules and classifications.
def delete_genre(genre_id: int, path: Path | None = None) -> bool:
    connection = create_connection(path)

    try:
        with connection:
            cursor = connection.execute(
                "DELETE FROM genres WHERE id = ?",
                (genre_id,),
            )
            rebuild_classifications(connection)

        return cursor.rowcount == 1
    finally:
        connection.close()


# Create a reusable local genre rule for a Spotify resource.
def create_genre_rule(
    genre_id: int,
    resource_type: str,
    spotify_id: str,
    path: Path | None = None,
) -> dict[str, object]:
    connection = create_connection(path)

    try:
        with connection:
            cursor = connection.execute(
                """
                INSERT INTO genre_rules (genre_id, resource_type, spotify_id)
                VALUES (?, ?, ?)
                """,
                (genre_id, resource_type, spotify_id),
            )
            rebuild_classifications(connection)

        return get_genre_rule_from_connection(connection, cursor.lastrowid)
    finally:
        connection.close()


# Return all local genre rules with their configured genre names.
def list_genre_rules(path: Path | None = None) -> list[dict[str, object]]:
    connection = create_connection(path)

    try:
        rows = connection.execute(
            """
            SELECT
                genre_rules.id,
                genre_rules.genre_id,
                genres.name AS genre_name,
                genre_rules.resource_type,
                genre_rules.spotify_id,
                genre_rules.created_at,
                genre_rules.updated_at
            FROM genre_rules
            JOIN genres ON genres.id = genre_rules.genre_id
            ORDER BY genre_rules.id
            """,
        ).fetchall()
        return [genre_rule_row_to_dict(row) for row in rows]
    finally:
        connection.close()


# Delete a local genre rule and recalculate affected classifications.
def delete_genre_rule(rule_id: int, path: Path | None = None) -> bool:
    connection = create_connection(path)

    try:
        with connection:
            cursor = connection.execute(
                "DELETE FROM genre_rules WHERE id = ?",
                (rule_id,),
            )
            rebuild_classifications(connection)

        return cursor.rowcount == 1
    finally:
        connection.close()


# Recalculate local classifications from enabled manual rules.
def rebuild_classifications(connection: sqlite3.Connection) -> dict[str, int]:
    rule_rows = connection.execute(
        """
        SELECT genre_id, resource_type, spotify_id
        FROM genre_rules
        JOIN genres ON genres.id = genre_rules.genre_id
        WHERE genres.enabled = 1
        """,
    ).fetchall()
    track_rules: dict[str, set[int]] = {}
    album_rules: dict[str, set[int]] = {}
    artist_rules: dict[str, set[int]] = {}

    for genre_id, resource_type, spotify_id in rule_rows:
        rules_by_resource = {
            "track": track_rules,
            "album": album_rules,
            "artist": artist_rules,
        }[resource_type]
        rules_by_resource.setdefault(spotify_id, set()).add(genre_id)

    connection.execute("DELETE FROM track_genres")
    track_rows = connection.execute(
        """
        SELECT id, spotify_id, album_spotify_id, artists_json
        FROM tracks
        """,
    ).fetchall()
    classified_track_count = 0
    classification_count = 0

    for track_id, spotify_id, album_spotify_id, artists_json in track_rows:
        genre_ids, source = get_rule_classification(
            spotify_id,
            album_spotify_id,
            artists_json,
            track_rules,
            album_rules,
            artist_rules,
        )

        if not genre_ids or not source:
            continue

        connection.executemany(
            """
            INSERT INTO track_genres (track_id, genre_id, source, confidence)
            VALUES (?, ?, ?, ?)
            """,
            [
                (track_id, genre_id, source, 1.0)
                for genre_id in genre_ids
            ],
        )
        classified_track_count += 1
        classification_count += len(genre_ids)

    return {
        "classified_track_count": classified_track_count,
        "classification_count": classification_count,
    }


# Apply track, album, and artist rule precedence to one imported track.
def get_rule_classification(
    spotify_id: str,
    album_spotify_id: str | None,
    artists_json: str,
    track_rules: dict[str, set[int]],
    album_rules: dict[str, set[int]],
    artist_rules: dict[str, set[int]],
) -> tuple[set[int], str | None]:
    if spotify_id in track_rules:
        return track_rules[spotify_id], "track_rule"

    if album_spotify_id and album_spotify_id in album_rules:
        return album_rules[album_spotify_id], "album_rule"

    artist_genre_ids = set()

    for artist in json.loads(artists_json):
        artist_id = artist.get("id")

        if artist_id in artist_rules:
            artist_genre_ids.update(artist_rules[artist_id])

    if artist_genre_ids:
        return artist_genre_ids, "artist_rule"

    return set(), None


# Return tracks without any current local genre classification.
def list_tracks_needing_review(
    limit: int,
    offset: int,
    path: Path | None = None,
) -> dict[str, object]:
    connection = create_connection(path)

    try:
        total = connection.execute(
            """
            SELECT COUNT(*)
            FROM tracks
            LEFT JOIN track_genres ON track_genres.track_id = tracks.id
            WHERE track_genres.track_id IS NULL
            """,
        ).fetchone()[0]
        rows = connection.execute(
            """
            SELECT
                tracks.spotify_id,
                tracks.name,
                tracks.album_name,
                tracks.album_spotify_id,
                tracks.release_date,
                tracks.artists_json
            FROM tracks
            LEFT JOIN track_genres ON track_genres.track_id = tracks.id
            WHERE track_genres.track_id IS NULL
            ORDER BY tracks.release_date DESC, tracks.name COLLATE NOCASE
            LIMIT ? OFFSET ?
            """,
            (limit, offset),
        ).fetchall()
        return {
            "total": total,
            "items": [track_row_to_dict(row) for row in rows],
        }
    finally:
        connection.close()


# Return all current local classifications for an imported track.
def list_track_genres(
    spotify_id: str,
    path: Path | None = None,
) -> list[dict[str, object]] | None:
    connection = create_connection(path)

    try:
        track = connection.execute(
            "SELECT id FROM tracks WHERE spotify_id = ?",
            (spotify_id,),
        ).fetchone()

        if not track:
            return None

        rows = connection.execute(
            """
            SELECT
                genres.id,
                genres.name,
                genres.description,
                track_genres.source,
                track_genres.confidence,
                track_genres.classified_at
            FROM track_genres
            JOIN genres ON genres.id = track_genres.genre_id
            WHERE track_genres.track_id = ?
            ORDER BY genres.name COLLATE NOCASE
            """,
            (track[0],),
        ).fetchall()
        return [
            {
                "id": row[0],
                "name": row[1],
                "description": row[2],
                "source": row[3],
                "confidence": row[4],
                "classified_at": row[5],
            }
            for row in rows
        ]
    finally:
        connection.close()


# Convert a SQLite genre row into an API response dictionary.
def genre_row_to_dict(row: sqlite3.Row | tuple) -> dict[str, object]:
    return {
        "id": row[0],
        "name": row[1],
        "description": row[2],
        "enabled": bool(row[3]),
        "created_at": row[4],
        "updated_at": row[5],
    }


# Return one genre using an existing database connection.
def get_genre_from_connection(
    connection: sqlite3.Connection,
    genre_id: int | None,
) -> dict[str, object] | None:
    if genre_id is None:
        return None

    row = connection.execute(
        "SELECT * FROM genres WHERE id = ?",
        (genre_id,),
    ).fetchone()

    if not row:
        return None

    return genre_row_to_dict(row)


# Return one genre rule using an existing database connection.
def get_genre_rule_from_connection(
    connection: sqlite3.Connection,
    rule_id: int | None,
) -> dict[str, object] | None:
    if rule_id is None:
        return None

    row = connection.execute(
        """
        SELECT
            genre_rules.id,
            genre_rules.genre_id,
            genres.name AS genre_name,
            genre_rules.resource_type,
            genre_rules.spotify_id,
            genre_rules.created_at,
            genre_rules.updated_at
        FROM genre_rules
        JOIN genres ON genres.id = genre_rules.genre_id
        WHERE genre_rules.id = ?
        """,
        (rule_id,),
    ).fetchone()

    if not row:
        return None

    return genre_rule_row_to_dict(row)


# Convert a SQLite genre rule row into an API response dictionary.
def genre_rule_row_to_dict(row: sqlite3.Row | tuple) -> dict[str, object]:
    return {
        "id": row[0],
        "genre_id": row[1],
        "genre_name": row[2],
        "resource_type": row[3],
        "spotify_id": row[4],
        "created_at": row[5],
        "updated_at": row[6],
    }


# Convert a SQLite track row into a review queue response dictionary.
def track_row_to_dict(row: sqlite3.Row | tuple) -> dict[str, object]:
    return {
        "spotify_id": row[0],
        "name": row[1],
        "album_name": row[2],
        "album_spotify_id": row[3],
        "release_date": row[4],
        "artists": json.loads(row[5]),
    }
