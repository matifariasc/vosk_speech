"""Simple HTTP server that serves transcription data.

The server reads all ``transcripciones_*.json`` files in the current directory
and exposes their combined contents over a REST-like API. Use optional
``fecha`` (``YYYY-MM-DD``), ``hora`` (``HH:MM[:SS]``), ``fechahora`` and range
parameters (``fechahora_inicio``/``fechahora_fin`` o ``hora_inicio``/``hora_fin``)
alongside ``medio`` and ``hours`` (ventana en horas, por defecto 48) to filtrar
los resultados por día, instante o rangos completos.

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
from typing import Any, Dict, List, Optional, Tuple


def _load_env_file(path: str = ".env") -> None:
    """Best-effort loader for simple KEY=VALUE lines in a .env file."""
    if not os.path.exists(path):
        return
    try:
        with open(path, "r", encoding="utf-8") as env_file:
            for raw_line in env_file:
                line = raw_line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                os.environ.setdefault(key, value)
    except OSError:
        # Ignore file access issues; fall back to process env defaults.
        return


def _get_int_env(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        return default


_load_env_file()

BASE_URL = os.getenv("BASE_URL", "http://localhost:5212/")
DEFAULT_HOURS = _get_int_env("DEFAULT_HOURS", 48)
ORDER_DESC_VALUES = {"desc", "newest", "reciente"}
TEXT_MARGIN_SECONDS = 0.5
_DATETIME_FORMATS = (
    "%Y-%m-%d %H:%M:%S.%f",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d %H:%M",
)


def _parse_datetime_string(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    cleaned = value.strip()
    if not cleaned:
        return None
    # Permite tanto separador espacio como 'T'
    normalized = cleaned.replace("T", " ")
    for fmt in _DATETIME_FORMATS:
        try:
            return datetime.strptime(normalized, fmt)
        except ValueError:
            continue
    return None


def _parse_datetime(fecha: Optional[str], hora: Optional[str]) -> Optional[datetime]:
    if not fecha or not hora:
        return None
    return _parse_datetime_string(f"{fecha.strip()} {hora.strip()}")


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


def _get_block_bounds(
    ruta_archivo: str, entrada: Dict[str, Any]
) -> Tuple[Optional[datetime], Optional[datetime]]:
    """Devuelve datetime inicio/fin aproximados para un archivo de transcripción."""

    inicio_archivo = extraer_datetime(ruta_archivo)
    duracion = entrada.get("duracion")
    if isinstance(duracion, (int, float)):
        duracion_seg = float(duracion)
    else:
        duracion_seg = None

    if inicio_archivo and duracion_seg is not None:
        return inicio_archivo, inicio_archivo + timedelta(seconds=duracion_seg)

    registros = entrada.get("registros", []) or []
    inicios: List[datetime] = []
    fines: List[datetime] = []

    for bloque in registros:
        if not isinstance(bloque, dict):
            continue
        inicio = _parse_datetime(bloque.get("fecha"), bloque.get("inicio"))
        fin = _parse_datetime(bloque.get("fecha"), bloque.get("fin"))
        if inicio:
            inicios.append(inicio)
        if fin:
            fines.append(fin)

    inicio_est = inicio_archivo
    if inicios:
        inicio_min = min(inicios)
        inicio_est = min(inicio_archivo, inicio_min) if inicio_archivo else inicio_min

    fin_est: Optional[datetime] = None
    if fines:
        fin_est = max(fines)
    elif inicio_est and duracion_seg is not None:
        fin_est = inicio_est + timedelta(seconds=duracion_seg)

    if inicio_est and fin_est and fin_est < inicio_est:
        fin_est = None

    return inicio_est, fin_est


def _block_contains_datetime(ruta_archivo: str, entrada: Dict[str, Any], objetivo: datetime) -> bool:
    """Indica si el bloque de transcripción cubre la fecha-hora indicada."""

    inicio, fin = _get_block_bounds(ruta_archivo, entrada)
    if not inicio:
        return False
    if fin:
        return inicio <= objetivo <= fin
    return objetivo >= inicio


def _block_overlaps_range(
    ruta_archivo: str,
    entrada: Dict[str, Any],
    inicio_rango: Optional[datetime],
    fin_rango: Optional[datetime],
) -> bool:
    """Determina si el bloque se cruza con el rango solicitado."""

    if inicio_rango is None and fin_rango is None:
        return True
    inicio, fin = _get_block_bounds(ruta_archivo, entrada)
    if inicio is None:
        return False
    # Si no tenemos fin del bloque, asumimos que se extiende hacia adelante.
    if fin is None:
        if fin_rango is None:
            return True
        return inicio <= fin_rango
    if inicio_rango is None:
        return fin_rango >= inicio  # type: ignore[operator]
    if fin_rango is None:
        return inicio <= fin
    return not (fin < inicio_rango or inicio > fin_rango)


def _get_record_bounds(bloque: Dict[str, Any]) -> Tuple[Optional[datetime], Optional[datetime]]:
    """Devuelve datetime inicio/fin de un registro."""

    inicio = _parse_datetime(bloque.get("fecha"), bloque.get("inicio"))
    fin = _parse_datetime(bloque.get("fecha"), bloque.get("fin"))
    if fin is None and inicio and isinstance(bloque.get("duracion"), (int, float)):
        fin = inicio + timedelta(seconds=float(bloque["duracion"]))
    return inicio, fin


def _record_overlaps_range(
    bloque: Dict[str, Any],
    inicio_rango: Optional[datetime],
    fin_rango: Optional[datetime],
    margen_segundos: float = TEXT_MARGIN_SECONDS,
) -> bool:
    """Determina si el registro se cruza con el rango solicitado."""

    inicio, fin = _get_record_bounds(bloque)
    if inicio is None and fin is None:
        return False
    if inicio is None:
        inicio = fin
    if fin is None:
        fin = inicio
    margen = timedelta(seconds=margen_segundos)
    inicio_rango = inicio_rango - margen if inicio_rango else None
    fin_rango = fin_rango + margen if fin_rango else None
    if inicio_rango and fin_rango:
        return not (fin < inicio_rango or inicio > fin_rango)
    if inicio_rango:
        return fin >= inicio_rango
    if fin_rango:
        return inicio <= fin_rango
    return True


def _collect_text(
    items: List[Tuple[str, dict]],
    objetivo_dt: Optional[datetime],
    rango_inicio: Optional[datetime],
    rango_fin: Optional[datetime],
) -> Tuple[str, int]:
    """Concatena los textos de los registros filtrados por rango."""

    seleccionados: List[Tuple[datetime, int, str]] = []
    orden_seq = 0
    for _, entrada in items:
        registros = entrada.get("registros", []) or []
        for bloque in registros:
            if not isinstance(bloque, dict):
                continue
            if objetivo_dt:
                if not _record_overlaps_range(bloque, objetivo_dt, objetivo_dt):
                    continue
            elif rango_inicio or rango_fin:
                if not _record_overlaps_range(bloque, rango_inicio, rango_fin):
                    continue
            texto = bloque.get("texto")
            if texto is None:
                continue
            if not isinstance(texto, str):
                texto = str(texto)
            texto = texto.strip()
            if not texto:
                continue
            inicio, fin = _get_record_bounds(bloque)
            orden_dt = inicio or fin or datetime.min
            seleccionados.append((orden_dt, orden_seq, texto))
            orden_seq += 1
    seleccionados.sort(key=lambda item: (item[0], item[1]))
    return " ".join(texto for _, _, texto in seleccionados).strip(), len(seleccionados)


def _build_remote_url(ruta_archivo: str) -> str:
    medio = extraer_medio(ruta_archivo)
    filename = os.path.basename(ruta_archivo)
    # Asegura un solo slash al unir base, medio y archivo
    base = BASE_URL.rstrip("/")
    return f"{base}/{medio}/{filename}"


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
        filtro_hora = qs.get("hora", [None])[0]
        filtro_fechahora = qs.get("fechahora", [None])[0]
        filtro_fechahora_inicio = qs.get("fechahora_inicio", [None])[0]
        filtro_fechahora_fin = qs.get("fechahora_fin", [None])[0]
        filtro_hora_inicio = qs.get("hora_inicio", [None])[0]
        filtro_hora_fin = qs.get("hora_fin", [None])[0]
        filtro_fecha_fin = qs.get("fecha_fin", [None])[0]
        text_only = "text" in qs or "texto" in qs
        order_param = (qs.get("order", [None])[0] or "").lower()
        ordenar_desc = order_param in ORDER_DESC_VALUES
        try:
            filtro_horas = int(qs.get("hours", [DEFAULT_HOURS])[0])
        except ValueError:
            filtro_horas = DEFAULT_HOURS

        objetivo_dt: Optional[datetime] = None
        if filtro_fechahora:
            objetivo_dt = _parse_datetime_string(filtro_fechahora)
            if objetivo_dt is None:
                self.send_error(
                    400,
                    "Formato de 'fechahora' inválido. Use YYYY-MM-DD HH:MM[:SS[.sss]]",
                )
                return
        elif filtro_hora:
            if not filtro_fecha:
                self.send_error(400, "Debe proporcionar 'fecha' junto con 'hora'")
                return
            objetivo_dt = _parse_datetime(filtro_fecha, filtro_hora)
            if objetivo_dt is None:
                self.send_error(
                    400,
                    "Formato de 'hora' inválido. Use HH:MM, HH:MM:SS o HH:MM:SS.sss",
                )
                return

        rango_inicio: Optional[datetime] = None
        if filtro_fechahora_inicio:
            rango_inicio = _parse_datetime_string(filtro_fechahora_inicio)
            if rango_inicio is None:
                self.send_error(
                    400,
                    "Formato de 'fechahora_inicio' inválido. Use YYYY-MM-DD HH:MM[:SS[.sss]]",
                )
                return
        elif filtro_hora_inicio:
            if not filtro_fecha:
                self.send_error(
                    400,
                    "Debe proporcionar 'fecha' cuando utiliza 'hora_inicio'",
                )
                return
            rango_inicio = _parse_datetime(filtro_fecha, filtro_hora_inicio)
            if rango_inicio is None:
                self.send_error(
                    400,
                    "Formato de 'hora_inicio' inválido. Use HH:MM, HH:MM:SS o HH:MM:SS.sss",
                )
                return

        rango_fin: Optional[datetime] = None
        if filtro_fechahora_fin:
            rango_fin = _parse_datetime_string(filtro_fechahora_fin)
            if rango_fin is None:
                self.send_error(
                    400,
                    "Formato de 'fechahora_fin' inválido. Use YYYY-MM-DD HH:MM[:SS[.sss]]",
                )
                return
        elif filtro_hora_fin:
            fecha_para_fin = filtro_fecha_fin or filtro_fecha
            if not fecha_para_fin:
                self.send_error(
                    400,
                    "Debe proporcionar 'fecha' o 'fecha_fin' cuando utiliza 'hora_fin'",
                )
                return
            rango_fin = _parse_datetime(fecha_para_fin, filtro_hora_fin)
            if rango_fin is None:
                self.send_error(
                    400,
                    "Formato de 'hora_fin' inválido. Use HH:MM, HH:MM:SS o HH:MM:SS.sss",
                )
                return

        if rango_inicio and rango_fin and rango_inicio > rango_fin:
            self.send_error(400, "'fechahora_inicio' debe ser anterior a 'fechahora_fin'")
            return

        registro, error = cargar_registros()
        if error:
            self.send_error(500, error)
            return
        if archivo:
            datos = registro.get(archivo)
            if datos is None:
                self.send_error(404, "Archivo no encontrado en el registro")
                return
            if objetivo_dt and not _block_contains_datetime(archivo, datos, objetivo_dt):
                self.send_error(404, "El archivo no contiene la fecha y hora solicitadas")
                return
            if (rango_inicio or rango_fin) and not _block_overlaps_range(archivo, datos, rango_inicio, rango_fin):
                self.send_error(404, "El archivo no intersecta con el rango solicitado")
                return
            if text_only:
                texto, total = _collect_text(
                    [(archivo, datos)],
                    objetivo_dt,
                    rango_inicio,
                    rango_fin,
                )
                if total == 0 or not texto:
                    self.send_error(404, "No se encontraron registros en el rango indicado")
                    return
                self._write_json({"texto": texto})
                return
            respuesta = {
                "file": archivo,
                "url": _build_remote_url(archivo),
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
            if objetivo_dt:
                items = [
                    (k, v)
                    for k, v in items
                    if _block_contains_datetime(k, v, objetivo_dt)
                ]
                if not items:
                    self.send_error(404, "No se encontró un bloque para la fecha y hora indicadas")
                    return
            if rango_inicio or rango_fin:
                items = [
                    (k, v)
                    for k, v in items
                    if _block_overlaps_range(k, v, rango_inicio, rango_fin)
                ]
            if not items:
                self.send_error(404, "No se encontraron bloques en el rango indicado")
                return
            if text_only:
                texto, total = _collect_text(
                    items,
                    objetivo_dt,
                    rango_inicio,
                    rango_fin,
                )
                if total == 0 or not texto:
                    self.send_error(404, "No se encontraron registros en el rango indicado")
                    return
                self._write_json({"texto": texto})
                return
            # Ordenar por fecha/hora (más antiguos primero por defecto)
            items.sort(
                key=lambda item: extraer_datetime(item[0]) or datetime.min,
                reverse=ordenar_desc,
            )
            respuesta = [
                {
                    "file": k,
                    "url": _build_remote_url(k),
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
                        "hora": "HH:MM[:SS] para traer el bloque que cubre esa hora (requiere 'fecha')",
                        "fechahora": "YYYY-MM-DD HH:MM[:SS] para apuntar a un bloque usando un solo parámetro",
                        "fechahora_inicio": "Inicio del rango en formato YYYY-MM-DD HH:MM[:SS]",
                        "fechahora_fin": "Fin del rango en formato YYYY-MM-DD HH:MM[:SS]",
                        "hora_inicio": "HH:MM[:SS] como inicio del rango (requiere 'fecha')",
                        "hora_fin": "HH:MM[:SS] como fin del rango (requiere 'fecha' o 'fecha_fin')",
                        "fecha_fin": "Permite indicar un día distinto para 'hora_fin'",
                        "medio": "Nombre de la carpeta canal (p.ej. Canal13)",
                        "hours": f"Ventana en horas (int), por defecto {DEFAULT_HOURS}",
                        "order": "Orden de los resultados (por defecto antiguos primero; usar 'newest' o 'reciente')",
                        "text": "Si está presente, devuelve un solo texto concatenado del rango solicitado",
                    },
                    "examples": [
                        "/?medio=Canal13",
                        "/?fecha=2025-07-22",
                        "/?hours=24",
                        "/?medio=Canal13&hours=12",
                        "/?medio=Canal13&order=newest",
                        "/?fecha=2025-10-24&hora=13:00:00",
                        "/?fechahora=2025-10-24T13:00:00",
                        "/?fecha=2025-10-24&hora_inicio=13:00&hora_fin=14:00",
                        "/?fechahora_inicio=2025-10-24 12:50&fechahora_fin=2025-10-24 13:10",
                        "/?fecha=2025-10-24&hora_inicio=13:00&hora_fin=14:00&medio=Canal13&text",
                    ],
                    "notes": [
                        "Los resultados vienen ordenados por defecto desde el archivo más antiguo al más reciente.",
                        "Agrega order=newest (o order=reciente) para invertir y ver primero los más nuevos.",
                        "Combina fecha y hora para recuperar directamente el bloque que cubre ese instante.",
                        "Cuando uses 'hora_inicio' o 'hora_fin' incluye también 'fecha' (y 'fecha_fin' si corresponde).",
                        "Cuando uses 'text', el filtro de rango incluye un margen de 1 segundo.",
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
