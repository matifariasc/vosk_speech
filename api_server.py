"""Simple HTTP server that serves transcription data.

The server reads all ``transcripciones_*.json`` files in the current directory
and exposes their combined contents over a REST-like API. Use optional
``fecha`` (``YYYY-MM-DD``) and ``medio`` query parameters to filter results by
date and channel.

Example::

    http://localhost:8000/?fecha=2025-07-22&medio=Canal13
"""

import json
import os
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse, parse_qs
from typing import Optional

BASE_URL = "http://integra.ispaccess.conectamedia.cl:5232//Canal13/"


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


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path != "/":
            self.send_error(404)
            return
        qs = parse_qs(parsed.query)
        archivo = qs.get("file", [None])[0]
        filtro_fecha = qs.get("fecha", [None])[0]
        filtro_medio = qs.get("medio", [None])[0]
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


def run(port: int = 8000) -> None:
    server = HTTPServer(("", port), Handler)
    print(f"Servidor escuchando en http://localhost:{port}")
    server.serve_forever()


if __name__ == "__main__":
    from sys import argv

    port = int(argv[1]) if len(argv) > 1 else 8000
    run(port)
