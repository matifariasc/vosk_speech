"""Utilities to send transcription payloads to the CUOS API."""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Dict, Iterable, Iterator, Optional

import requests

ENV_ENDPOINT = "CUOS_ENDPOINT"
REQUEST_TIMEOUT = 5
HEADERS = {"Content-Type": "application/json"}

_ENV_LOADED = False
_ENV_LOCK = threading.Lock()


def _load_env_file(path: Path) -> None:
    """Populate os.environ with entries from a .env file if present."""

    try:
        with path.open("r", encoding="utf-8") as handle:
            for raw_line in handle:
                line = raw_line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                os.environ.setdefault(key, value)
    except OSError:
        return


def _ensure_env_loaded() -> None:
    global _ENV_LOADED  # noqa: PLW0603
    if _ENV_LOADED:
        return
    with _ENV_LOCK:
        if _ENV_LOADED:
            return
        env_path = Path(".env")
        if env_path.exists():
            _load_env_file(env_path)
        _ENV_LOADED = True


def _clean_inicio(value: str) -> str:
    """Normaliza el campo `inicio` para obtener HH:MM:SS."""

    inicio = value.strip()
    if "." in inicio:
        inicio = inicio.split(".", 1)[0]
    if len(inicio) == 5:
        inicio = f"{inicio}:00"
    return inicio


def iter_payloads(
    source: Path,
    only_keys: Optional[Iterable[str]] = None,
) -> Iterator[Dict[str, str]]:
    """Yield payloads ready to POST to the CUOS API.

    Parameters
    ----------
    source:
        Path to the JSON file containing transcription records.
    only_keys:
        Optional iterable with the keys (file paths) to limit iteration to.
        Works with both dict and list based JSON layouts.
    """

    raw = json.loads(source.read_text(encoding="utf-8"))

    keys_filter = set(only_keys or [])
    if isinstance(raw, dict):
        entries = []
        if keys_filter:
            for key in keys_filter:
                if key in raw:
                    entries.append(raw[key])
        else:
            entries = list(raw.values())
    elif isinstance(raw, list):
        if keys_filter:
            entries = [
                entry
                for entry in raw
                if isinstance(entry, dict)
                and entry.get("file") in keys_filter
            ]
            if not entries:
                entries = raw
        else:
            entries = raw
    else:
        entries = []

    for entry in entries:
        if not isinstance(entry, dict):
            continue
        registros = entry.get("registros") or []
        if not isinstance(registros, list):
            continue
        for registro in registros:
            if not isinstance(registro, dict):
                continue
            medio = (registro.get("medio") or "").strip() or "RADIOLAMETRO"
            fecha = (registro.get("fecha") or "").strip()
            inicio = _clean_inicio(registro.get("inicio", ""))
            if not inicio:
                continue
            date = f"{fecha} {inicio}".strip()
            texto = (registro.get("texto") or "").strip()
            if not (fecha and inicio and texto):
                continue
            yield {
                "type": "Radio",
                "media_cuos": medio,
                "date": date,
                "text": texto,
            }


def get_endpoint() -> Optional[str]:
    """Return the CUOS endpoint, loading environment once if needed."""

    _ensure_env_loaded()
    endpoint = os.getenv(ENV_ENDPOINT, "").strip()
    return endpoint or None


def send_payloads(
    source: Path,
    only_keys: Optional[Iterable[str]] = None,
) -> int:
    """Send payloads generated from `source` to the CUOS API.

    Returns the number of payloads successfully posted. Raises RuntimeError
    if the endpoint is missing or request execution fails.
    """

    if not source.exists():
        return 0

    endpoint = get_endpoint()
    if not endpoint:
        raise RuntimeError("No CUOS endpoint configured via .env or default.")

    session = requests.Session()
    enviados = 0
    try:
        for payload in iter_payloads(source, only_keys):
            response = session.post(
                endpoint,
                json=payload,
                headers=HEADERS,
                timeout=REQUEST_TIMEOUT,
            )
            response.raise_for_status()
            enviados += 1
    except requests.RequestException as exc:
        raise RuntimeError(f"Error enviando payloads a CUOS: {exc}") from exc
    finally:
        session.close()
    return enviados


__all__ = [
    "ENV_ENDPOINT",
    "HEADERS",
    "REQUEST_TIMEOUT",
    "get_endpoint",
    "iter_payloads",
    "send_payloads",
]
