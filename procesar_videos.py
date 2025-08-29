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
- Omite el archivo más reciente (posible archivo en escritura).
- Procesa desde la penúltima hacia atrás, hasta un máximo de 50 archivos.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta
from time import perf_counter
from typing import Dict, List


from generador_audio import (
    procesar_audio_con_pausas,
    extraer_hora_desde_nombre,
)

# Política de retención: mantener solo las últimas 48 horas por canal
HOURS_TO_KEEP = 48

def cargar_registro(ruta: str) -> Dict[str, List[dict]]:
    """Carga el archivo JSON de registro si existe."""

    if os.path.exists(ruta):
        with open(ruta, "r", encoding="utf-8") as fh:
            return json.load(fh)
    return {}


def guardar_registro(registro: Dict[str, List[dict]], ruta: str) -> None:
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




def obtener_pendientes(carpeta: str, procesados: Dict[str, List[dict]]) -> list[str]:
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

    seguros = [ruta for ruta, _ in candidatos[1:1 + 50]]
    pendientes = [ruta for ruta in seguros if ruta not in procesados]
    return pendientes


def limpiar_registros_antiguos(registro: Dict[str, List[dict]],
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
        bloques = procesar_audio_con_pausas(archivo)
        duracion = perf_counter() - inicio
        registro[archivo] = bloques
        tiempos[archivo] = duracion
        # Limpiar entradas antiguas (retención 48h) antes de guardar
        limpiar_registros_antiguos(registro, tiempos)
        guardar_registro(registro, registro_archivo)
        guardar_tiempos(tiempos, tiempos_archivo)
        print(f"Procesamiento de {archivo} completado en {duracion:.2f} segundos")


if __name__ == "__main__":
    import sys

    if len(sys.argv) != 2:
        print("Uso: python procesar_videos.py <carpeta>")
        sys.exit(1)

    main(sys.argv[1])
