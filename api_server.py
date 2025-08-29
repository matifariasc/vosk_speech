"""Simple HTTP server that serves transcription data.

The server reads all ``transcripciones_*.json`` files in the current directory
and exposes their combined contents over a REST-like API. Use optional
``fecha`` (``YYYY-MM-DD``), ``medio`` and ``hours`` query parameters to filter
results by date, channel and time window (default: 48 hours).

Example::

    http://localhost:8000/?fecha=2025-07-22&medio=Canal13
    http://localhost:8000/?hours=48
    http://localhost:8000/docs
"""

import json
import os
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse, parse_qs
from datetime import datetime, timedelta
from typing import Optional

BASE_URL = "http://integra.ispaccess.conectamedia.cl:5232//Canal13/"
DEFAULT_HOURS = 48


def cargar_registros():
    """Carga y combina los archivos de transcripciones.

    Returns a tuple ``(registro, error)``. ``registro`` contiene el diccionario
    con las transcripciones combinadas o ``None`` si no se pudieron cargar.
    ``error`` guarda un mensaje descriptivo cuando ocurre un problema, en caso
    contrario es ``None``.
    """

    archivos = [
        f
        for f in os.listdir()
        if f.startswith("transcripciones") and f.endswith(".json")
    ]
    if not archivos:
        return None, "No se encontraron archivos de transcripciones"
    registro: dict[str, list[dict]] = {}
    for archivo in archivos:
        try:
            with open(archivo, "r", encoding="utf-8") as fh:
                datos = json.load(fh)
        except json.JSONDecodeError as exc:
            return None, f"Error leyendo {archivo}: {exc}"
        registro.update(datos)
    return registro, None


def extraer_fecha(nombre_archivo: str) -> Optional[str]:
    """Devuelve la fecha (YYYY-MM-DD) extraída desde el nombre del archivo."""

    base, _ = os.path.splitext(os.path.basename(nombre_archivo))
    partes = base.split("_")
    if len(partes) >= 2:
        return partes[1]
    return None


def extraer_medio(ruta_archivo: str) -> str:
    """Devuelve el nombre del medio (carpeta contenedora)."""

    return os.path.basename(os.path.dirname(ruta_archivo))


def extraer_datetime(nombre_archivo: str) -> Optional[datetime]:
    base, _ = os.path.splitext(os.path.basename(nombre_archivo))
    partes = base.split("_")
    if len(partes) >= 3:
        fecha_str = partes[1]
        hora_str = partes[2]
        try:
            return datetime.strptime(f"{fecha_str} {hora_str}", "%Y-%m-%d %H-%M-%S")
        except ValueError:
            return None
    return None


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/docs":
            self._send_docs()
            return
        if parsed.path != "/":
            self.send_error(404)
            return
        qs = parse_qs(parsed.query)
        archivo = qs.get("file", [None])[0]
        filtro_fecha = qs.get("fecha", [None])[0]
        filtro_medio = qs.get("medio", [None])[0]
        try:
            filtro_horas = int(qs.get("hours", [DEFAULT_HOURS])[0])
        except ValueError:
            filtro_horas = DEFAULT_HOURS
        registro, error = cargar_registros()
        if error:
            self.send_error(500, error)
            return
        if archivo:
            datos = registro.get(archivo)
            if datos is None:
                self.send_error(404, "Archivo no encontrado en el registro")
                return
            if not datos:
                self.send_error(404, "Archivo sin transcripciones")
                return
            respuesta = {
                "file": archivo,
                "url": BASE_URL + os.path.basename(archivo),
                "registros": datos,
            }
            if not os.path.exists(archivo):
                respuesta["warning"] = "Archivo de video no encontrado"
        else:
            items = registro.items()
            if filtro_fecha:
                items = [
                    (k, v)
                    for k, v in items
                    if extraer_fecha(k) == filtro_fecha
                ]
            if filtro_medio:
                items = [
                    (k, v)
                    for k, v in items
                    if extraer_medio(k) == filtro_medio
                ]
            # Filtrar por ventana de horas (por defecto 48h)
            limite = datetime.now() - timedelta(hours=filtro_horas)
            items = [
                (k, v)
                for k, v in items
                if (dt := extraer_datetime(k)) is not None and dt >= limite
            ]
            respuesta = [
                {
                    "file": k,
                    "url": BASE_URL + os.path.basename(k),
                    "registros": v,
                }
                for k, v in items
            ]
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.end_headers()
        self.wfile.write(json.dumps(respuesta, ensure_ascii=False, indent=2).encode("utf-8"))

    def _send_docs(self) -> None:
        docs = {
            "endpoints": {
                "/": {
                    "desc": "Lista transcripciones combinadas (por archivo)",
                    "query": {
                        "file": "Ruta exacta del archivo para obtener solo ese registro",
                        "fecha": "YYYY-MM-DD para filtrar por día",
                        "medio": "Nombre de la carpeta canal (p.ej. Canal13)",
                        "hours": f"Ventana en horas (int), por defecto {DEFAULT_HOURS}",
                    },
                    "examples": [
                        "/?medio=Canal13",
                        "/?fecha=2025-07-22",
                        "/?hours=24",
                        "/?medio=Canal13&hours=12",
                    ],
                },
                "/docs": {
                    "desc": "Este documento de ayuda (JSON)",
                },
            }
        }
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.end_headers()
        self.wfile.write(json.dumps(docs, ensure_ascii=False, indent=2).encode("utf-8"))


def run(port: int = 8000) -> None:
    server = HTTPServer(("", port), Handler)
    print(f"Servidor escuchando en http://localhost:{port}")
    server.serve_forever()


if __name__ == "__main__":
    from sys import argv

    port = int(argv[1]) if len(argv) > 1 else 8000
    run(port)
