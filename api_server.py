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
from typing import Any, Dict, List, Optional

BASE_URL = "http://integra.ispaccess.conectamedia.cl:5232//Canal13/"
DEFAULT_HOURS = 48


def _parse_datetime(fecha: Optional[str], hora: Optional[str]) -> Optional[datetime]:
    if not fecha or not hora:
        return None
    try:
        return datetime.strptime(f"{fecha} {hora}", "%Y-%m-%d %H:%M:%S.%f")
    except ValueError:
        return None


def _ensure_block_duration(bloque: dict) -> None:
    if "duracion" in bloque and bloque["duracion"] is not None:
        return
    inicio = _parse_datetime(bloque.get("fecha"), bloque.get("inicio"))
    fin = _parse_datetime(bloque.get("fecha"), bloque.get("fin"))
    if inicio and fin:
        bloque["duracion"] = round((fin - inicio).total_seconds(), 3)
    else:
        bloque.setdefault("duracion", None)


def _calculate_file_duration(registros: List[dict]) -> Optional[float]:
    if not registros:
        return None
    inicios = []
    fines = []
    for bloque in registros:
        if not isinstance(bloque, dict):
            continue
        inicio = _parse_datetime(bloque.get("fecha"), bloque.get("inicio"))
        fin = _parse_datetime(bloque.get("fecha"), bloque.get("fin"))
        if inicio:
            inicios.append(inicio)
        if fin:
            fines.append(fin)
    if not inicios or not fines:
        return None
    duracion_total = (max(fines) - min(inicios)).total_seconds()
    if duracion_total < 0:
        return None
    return round(duracion_total, 3)


def _normalizar_entrada(entrada: Any) -> dict:
    if isinstance(entrada, dict):
        registros = entrada.get("registros", [])
        if not isinstance(registros, list):
            registros = []
        entrada["registros"] = registros
    elif isinstance(entrada, list):
        registros = entrada
        entrada = {"registros": registros}
    else:
        registros = []
        entrada = {"registros": registros}

    for bloque in registros:
        if isinstance(bloque, dict):
            _ensure_block_duration(bloque)

    if entrada.get("duracion") is None:
        entrada["duracion"] = _calculate_file_duration([
            b for b in registros if isinstance(b, dict)
        ])

    return entrada


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
    registro: Dict[str, dict] = {}
    for archivo in archivos:
        try:
            with open(archivo, "r", encoding="utf-8") as fh:
                datos = json.load(fh)
        except json.JSONDecodeError as exc:
            return None, f"Error leyendo {archivo}: {exc}"
        if not isinstance(datos, dict):
            continue
        for ruta, entrada in datos.items():
            registro[ruta] = _normalizar_entrada(entrada)
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
    def _write_json(self, payload: Any, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError, TimeoutError) as exc:
            self.log_error("Client disconnected before response was sent: %r", exc)
            self.close_connection = True

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
            respuesta = {
                "file": archivo,
                "url": BASE_URL + os.path.basename(archivo),
                "duracion": datos.get("duracion"),
                "registros": datos.get("registros", []),
            }
            if not respuesta["registros"]:
                self.send_error(404, "Archivo sin transcripciones")
                return
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
            # Ordenar por fecha/hora (más recientes primero)
            items.sort(
                key=lambda item: extraer_datetime(item[0]) or datetime.min,
                reverse=True,
            )
            respuesta = [
                {
                    "file": k,
                    "url": BASE_URL + os.path.basename(k),
                    "duracion": v.get("duracion"),
                    "registros": v.get("registros", []),
                }
                for k, v in items
            ]
        self._write_json(respuesta)

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
        self._write_json(docs)


def run(port: int = 8000) -> None:
    server = HTTPServer(("", port), Handler)
    print(f"Servidor escuchando en http://localhost:{port}")
    server.serve_forever()


if __name__ == "__main__":
    from sys import argv

    port = int(argv[1]) if len(argv) > 1 else 8000
    run(port)
