"""Procesa múltiples videos generando un archivo JSON con las transcripciones.

El script recorre una carpeta que contiene archivos MP4 u OGG con nombre::

   <id>_YYYY-MM-DD_HH-MM-SS.<ext>

Para cada archivo se invoca ``generador_audio.procesar_audio_con_pausas`` y se
almacena la lista de bloques devuelta. El resultado completo se guarda en
``transcripciones_<canal>.json`` y los tiempos de procesamiento en
``tiempos_procesamiento_<canal>.json``, donde ``<canal>`` corresponde al nombre
de la carpeta procesada. Si una entrada ya existe en el JSON, el video no se
vuelve a procesar.

Prioridad de procesamiento (modo "al día"):
- Ordena por hora descendente (lo más reciente primero).
- Omite SIEMPRE el archivo más reciente (posible escritura en curso).
- Procesa uno por corrida: toma el siguiente más reciente (dentro de los últimos 50).
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta
from time import perf_counter, sleep
from typing import Any, Dict, List, Optional


from generador_audio import (
    procesar_audio_con_pausas,
    extraer_hora_desde_nombre,
)

# Política de retención: mantener solo las últimas 48 horas por canal
HOURS_TO_KEEP = 48


def _parse_datetime(fecha: Optional[str], hora: Optional[str]) -> Optional[datetime]:
    """Convierte fecha y hora en :class:`datetime` si es posible."""

    if not fecha or not hora:
        return None
    try:
        return datetime.strptime(f"{fecha} {hora}", "%Y-%m-%d %H:%M:%S.%f")
    except ValueError:
        return None


def _asegurar_duracion_bloque(bloque: dict) -> None:
    """Agrega la duración (s) al bloque si no existe."""

    if "duracion" in bloque and bloque["duracion"] is not None:
        return
    inicio_dt = _parse_datetime(bloque.get("fecha"), bloque.get("inicio"))
    fin_dt = _parse_datetime(bloque.get("fecha"), bloque.get("fin"))
    if inicio_dt and fin_dt:
        bloque["duracion"] = round((fin_dt - inicio_dt).total_seconds(), 3)
    else:
        bloque.setdefault("duracion", None)


def _calcular_duracion_archivo(registros: List[dict]) -> Optional[float]:
    """Deriva la duración estimada del archivo a partir de los registros."""

    if not registros:
        return None
    inicios: List[datetime] = []
    fines: List[datetime] = []
    for bloque in registros:
        if not isinstance(bloque, dict):
            continue
        inicio_dt = _parse_datetime(bloque.get("fecha"), bloque.get("inicio"))
        fin_dt = _parse_datetime(bloque.get("fecha"), bloque.get("fin"))
        if inicio_dt:
            inicios.append(inicio_dt)
        if fin_dt:
            fines.append(fin_dt)
    if not inicios or not fines:
        return None
    duracion_total = (max(fines) - min(inicios)).total_seconds()
    if duracion_total < 0:
        return None
    return round(duracion_total, 3)


def _normalizar_entrada(entrada: Any) -> dict:
    """Garantiza que cada entrada tenga ``duracion`` y ``registros``."""

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
            _asegurar_duracion_bloque(bloque)

    if entrada.get("duracion") is None:
        entrada["duracion"] = _calcular_duracion_archivo([
            b for b in registros if isinstance(b, dict)
        ])

    return entrada



def cargar_registro(ruta: str) -> Dict[str, dict]:
    """Carga el archivo JSON de registro si existe y normaliza su formato."""

    if os.path.exists(ruta):
        with open(ruta, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, dict):
            return {k: _normalizar_entrada(v) for k, v in data.items()}
    return {}


def guardar_registro(registro: Dict[str, dict], ruta: str) -> None:
    """Guarda el registro de transcripciones a disco."""

    with open(ruta, "w", encoding="utf-8") as fh:
        json.dump(registro, fh, ensure_ascii=False, indent=2)


def cargar_tiempos(ruta: str) -> Dict[str, float]:
    """Carga el registro de tiempos de procesamiento si existe."""

    if os.path.exists(ruta):
        with open(ruta, "r", encoding="utf-8") as fh:
            return json.load(fh)
    return {}


def guardar_tiempos(tiempos: Dict[str, float], ruta: str) -> None:
    """Guarda el registro de tiempos de procesamiento."""

    with open(ruta, "w", encoding="utf-8") as fh:
        json.dump(tiempos, fh, ensure_ascii=False, indent=2)



def formatear_bloques(bloques: list[dict]) -> str:
    """Convierte la lista de bloques en texto con marcas de tiempo."""

    lineas = []
    for b in bloques:
        lineas.append(f"[{b['inicio']} - {b['fin']}] {b['texto']}")
    return "\n".join(lineas)




def _esperar_archivo_estable(ruta: str, max_espera: int = 15, paso: int = 3) -> bool:
    """Espera hasta que el archivo deje de crecer (tamaño estable).

    Devuelve True si se estabilizó antes de `max_espera` segundos.
    """
    try:
        size_prev = os.path.getsize(ruta)
    except OSError:
        return False
    restante = max_espera
    while restante > 0:
        sleep(min(paso, restante))
        restante -= paso
        try:
            size_now = os.path.getsize(ruta)
        except OSError:
            return False
        if size_now == size_prev:
            return True
        size_prev = size_now
    return False


def obtener_pendientes(carpeta: str, procesados: Dict[str, dict]) -> list[str]:
    """Devuelve la lista de archivos pendientes (más recientes primero).

    Lógica:
    - Ordena por hora de archivo descendente (más reciente primero).
    - Omite la pieza más reciente (índice 0) y toma las siguientes hasta 50.
    - Filtra las que ya estén en ``procesados``.
    """

    candidatos: list[tuple[str, datetime]] = []
    for f in os.listdir(carpeta):
        if not f.lower().endswith((".mp4", ".ogg")):
            continue
        ruta = os.path.join(carpeta, f)
        try:
            hora = extraer_hora_desde_nombre(ruta)
        except Exception:
            continue
        candidatos.append((ruta, hora))

    candidatos.sort(key=lambda x: x[1], reverse=True)

    # Si el más reciente es .ogg, se procesa; de lo contrario, se salta el primero.
    start_idx = 0
    if candidatos and not candidatos[0][0].lower().endswith(".ogg"):
        start_idx = 1

    # Considerar hasta los últimos 50 elementos a partir del índice calculado
    top = [ruta for ruta, _ in candidatos[start_idx:start_idx + 50]]
    pendientes = [ruta for ruta in top if ruta not in procesados]

    # Solo uno por corrida: devolver el más reciente entre los seguros
    if pendientes:
        return [pendientes[0]]
    return []


def limpiar_registros_antiguos(registro: Dict[str, dict],
                               tiempos: Dict[str, float]) -> None:
    """Elimina entradas más antiguas que ``HOURS_TO_KEEP`` de ambos diccionarios.

    Modifica los diccionarios en sitio.
    """
    limite = datetime.now() - timedelta(hours=HOURS_TO_KEEP)
    keys_a_borrar = []
    for ruta in list(registro.keys()):
        try:
            hora_archivo = extraer_hora_desde_nombre(ruta)
        except Exception:
            continue
        if hora_archivo < limite:
            keys_a_borrar.append(ruta)

    for k in keys_a_borrar:
        registro.pop(k, None)
        tiempos.pop(k, None)


def main(carpeta: str) -> None:
    canal = os.path.basename(os.path.normpath(carpeta))
    registro_archivo = f"transcripciones_{canal}.json"
    tiempos_archivo = f"tiempos_procesamiento_{canal}.json"
    registro = cargar_registro(registro_archivo)
    tiempos = cargar_tiempos(tiempos_archivo)
    pendientes = obtener_pendientes(carpeta, registro)

    for archivo in pendientes:
        inicio = perf_counter()
        bloques, duracion_archivo = procesar_audio_con_pausas(archivo)
        duracion_procesamiento = perf_counter() - inicio
        registro[archivo] = _normalizar_entrada(
            {
                "duracion": duracion_archivo,
                "registros": bloques,
            }
        )
        tiempos[archivo] = duracion_procesamiento
        # Limpiar entradas antiguas (retención 48h) antes de guardar
        limpiar_registros_antiguos(registro, tiempos)
        guardar_registro(registro, registro_archivo)
        guardar_tiempos(tiempos, tiempos_archivo)
        print(
            f"Procesamiento de {archivo} completado en {duracion_procesamiento:.2f} segundos"
        )


if __name__ == "__main__":
    import sys

    if len(sys.argv) != 2:
        print("Uso: python procesar_videos.py <carpeta>")
        sys.exit(1)

    main(sys.argv[1])
