import time
from typing import Callable, TypeVar
import requests
from loguru import logger
from requests.adapters import HTTPAdapter
from spotipy.exceptions import SpotifyException
from urllib3.util.retry import Retry

T = TypeVar("T")

# Longer waits are reported to the user instead of freezing the app
MAX_WAIT_SECONDS = 60

def make_session() -> requests.Session:
    """
    HTTP session for spotipy that never sleeps indefinitely on a 429.
    By default urllib3 waits as long as Spotify's Retry-After says, which can freeze the process.
    Here a 429 comes back as an error with headers, and call_with_retry decides whether waiting is reasonable.
    """
    retry = Retry(
        total=3,
        connect=3,
        read=False,
        status=3,
        backoff_factor=0.3,
        status_forcelist=(500, 502, 503, 504),
        allowed_methods=None,
        respect_retry_after_header=False,
    )
    session = requests.Session()
    session.mount("https://", HTTPAdapter(max_retries=retry))
    session.mount("http://", HTTPAdapter(max_retries=retry))
    return session

def humanize_seconds(seconds: int) -> str:
    if seconds < 120:
        return f"{seconds} s"
    if seconds < 7200:
        return f"{round(seconds / 60)} min"
    return f"{seconds / 3600:.1f}".replace(".", ",") + " horas"

def retry_after_seconds(exc: SpotifyException, default: int = 1) -> int:
    headers = getattr(exc, "headers", None) or {}
    for key, value in headers.items():
        if key.lower() == "retry-after":
            try:
                return max(int(float(value)), 1)
            except (TypeError, ValueError):
                break
    return default

def call_with_retry(
    fn: Callable[..., T],
    *args,
    attempts: int = 4,
    sleep: Callable[[float], None] = time.sleep,
    **kwargs
) -> T:
    """Calls a Spotify function, waiting out reasonable 429 rate limits before giving up."""
    for attempt in range(1, attempts + 1):
        try:
            return fn(*args, **kwargs)
        except SpotifyException as exc:
            if exc.http_status != 429 or attempt == attempts:
                raise
            wait = retry_after_seconds(exc)
            if wait > MAX_WAIT_SECONDS:
                raise
            logger.warning(f"Spotify 429 Rate Limit: esperando {wait}s (intento {attempt}/{attempts})")
            sleep(wait)
    raise RuntimeError("unreachable")

def describe_api_error(exc: Exception) -> str:
    """User-facing explanation of a failed Spotify call."""
    if isinstance(exc, SpotifyException):
        if exc.http_status == 429:
            return (
                f"Spotify está limitando las peticiones. Espera {humanize_seconds(retry_after_seconds(exc, 30))}."
            )
        if exc.http_status == 403:
            return f"Spotify rechazó la operación (403 Forbidden). Mensaje: {exc.msg}"
        if exc.http_status == 404:
            return "El recurso no existe en Spotify (404)."
        return f"Spotify respondió HTTP {exc.http_status}: {exc.msg}"
    if isinstance(exc, requests.exceptions.RequestException):
        return "No se pudo conectar con los servidores de Spotify. Revisa tu conexión."
    return f"{type(exc).__name__}: {exc}"
