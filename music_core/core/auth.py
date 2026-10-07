from pathlib import Path
import requests
from spotipy.exceptions import SpotifyException, SpotifyOauthError
from ..config import settings

def explain_login_error(exc: Exception) -> str:
    """Turns a Spotify login failure into an actionable message."""
    text = str(exc)

    if isinstance(exc, SpotifyOauthError):
        if "invalid_grant" in text:
            return "Spotify ha rechazado el token guardado (invalid_grant). Borra el token y vuelve a autorizar."
        if "server_error" in text:
            return "Spotify devolvió server_error al autorizar. Prueba a crear una app nueva en el dashboard."
        if "invalid_client" in text:
            return "Client ID o Client Secret incorrectos. Revisa tus credenciales en el archivo .env."
        return f"Error de autorización de Spotify: {text}"

    if isinstance(exc, SpotifyException):
        if exc.http_status == 403:
            return "Spotify respondió 403 Forbidden. Comprueba usuarios autorizados y scopes en el dashboard."
        if exc.http_status == 401:
            return "Spotify respondió 401: el token no es válido o ha expirado."
        if exc.http_status == 429:
            return "Spotify respondió 429: demasiadas peticiones. Espera un momento y reintenta."
        return f"Spotify respondió HTTP {exc.http_status}: {exc.msg}"

    if isinstance(exc, requests.exceptions.RequestException):
        return "No se pudo conectar con Spotify. Revisa tu conexión a internet."

    return f"Error inesperado al conectar con Spotify: {type(exc).__name__}: {text}"

def clear_saved_token() -> bool:
    """Deletes the cached Spotify token so the next login starts a fresh authorization."""
    path = Path(settings.cache_path)
    if path.exists():
        path.unlink()
        return True
    return False
