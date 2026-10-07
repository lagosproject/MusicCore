import os
from pathlib import Path
from typing import List, Optional
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from dotenv import load_dotenv

# Load from current directory and any parent directory
load_dotenv(override=False)

PROJECT_ROOT = Path(__file__).resolve().parent.parent

class Settings(BaseSettings):
    # Spotify credentials (supports both SPOTIPY_* and standard clientID/clientSecret)
    spotipy_client_id: str = ""
    spotipy_client_secret: str = ""
    spotipy_redirect_uri: str = "http://127.0.0.1:8978/callback"
    spotify_country: str = "ES"

    # Server / App settings
    port: int = 8080
    host: str = "127.0.0.1"

    # Storage
    data_dir: str = "data"

    def __init__(self, **values):
        super().__init__(**values)
        # Fallback to alternate environment variable names if not set
        if not self.spotipy_client_id:
            self.spotipy_client_id = (
                os.getenv("SPOTIPY_CLIENT_ID") or 
                os.getenv("clientID") or 
                os.getenv("CLIENT_ID") or 
                ""
            )
        if not self.spotipy_client_secret:
            self.spotipy_client_secret = (
                os.getenv("SPOTIPY_CLIENT_SECRET") or 
                os.getenv("clientSecret") or 
                os.getenv("CLIENT_SECRET") or 
                ""
            )

    @field_validator("data_dir")
    @classmethod
    def _resolve_data_dir(cls, value: str) -> str:
        path = Path(value)
        return str(path if path.is_absolute() else PROJECT_ROOT / path)

    def missing_spotify_credentials(self) -> List[str]:
        missing = []
        if not self.spotipy_client_id.strip():
            missing.append("SPOTIPY_CLIENT_ID / clientID")
        if not self.spotipy_client_secret.strip():
            missing.append("SPOTIPY_CLIENT_SECRET / clientSecret")
        return missing

    @property
    def cache_path(self) -> str:
        return str(Path(self.data_dir) / ".cache")

    @property
    def previews_cache_path(self) -> str:
        return str(Path(self.data_dir) / "previews_cache.json")

    model_config = SettingsConfigDict(
        env_file=(".env", PROJECT_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

settings = Settings()
