import json
import os
from pathlib import Path


DEFAULT_TOKEN_FILE_PATH = "/app/data/spotify_tokens.json"


# Resolve the local token file path from configuration.
def get_token_file_path() -> Path:
    return Path(os.getenv("SPOTIFY_TOKEN_FILE", DEFAULT_TOKEN_FILE_PATH))


# Load locally persisted Spotify tokens.
def load_tokens(path: Path | None = None) -> dict[str, dict]:
    token_path = path or get_token_file_path()

    if not token_path.exists():
        return {}

    with token_path.open("r", encoding="utf-8") as token_file:
        data = json.load(token_file)

    if not isinstance(data, dict):
        return {}

    return data


# Persist Spotify tokens locally using a restricted file mode.
def save_tokens(tokens: dict[str, dict], path: Path | None = None) -> None:
    token_path = path or get_token_file_path()
    token_path.parent.mkdir(parents=True, exist_ok=True)

    temporary_path = token_path.with_suffix(f"{token_path.suffix}.tmp")

    with temporary_path.open("w", encoding="utf-8") as token_file:
        json.dump(tokens, token_file, indent=2)
        token_file.write("\n")

    os.chmod(temporary_path, 0o600)
    temporary_path.replace(token_path)
