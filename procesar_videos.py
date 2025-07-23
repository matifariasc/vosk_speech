"""Procesa múltiples videos generando un archivo JSON con las transcripciones.

El script recorre una carpeta que contiene archivos MP4 con un nombre de la
forma::

   <id>_YYYY-MM-DD_HH-MM-SS.mp4

Para cada archivo se invoca ``generador_audio.procesar_audio_con_pausas`` y se
almacena la lista de bloques devuelta. El resultado completo se guarda en
``transcripciones.json``. Si una entrada ya existe en el JSON, el video no se
vuelve a procesar. Solo se procesan archivos cuya hora se encuentre dentro de
las 24 horas previas al momento de ejecución del script.
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



REGISTRO = "transcripciones.json"
REGISTRO_TIEMPOS = "tiempos_procesamiento.json"


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
    """Devuelve la lista de archivos pendientes a procesar.

    Solo se consideran aquellos cuya hora esté dentro de las últimas 24 horas
    en relación al momento de ejecución del script.
    """

    todos = [
        os.path.join(carpeta, f) for f in os.listdir(carpeta) if f.endswith(".mp4")
    ]
    todos.sort()

    limite = datetime.now() - timedelta(hours=24)
    pendientes: list[str] = []
    for archivo in todos:
        if archivo in procesados:
            continue

        hora_archivo = extraer_hora_desde_nombre(archivo)

        if hora_archivo >= limite:
            pendientes.append(archivo)

    return pendientes


def main(carpeta: str) -> None:
    registro = cargar_registro(REGISTRO)
    tiempos = cargar_tiempos(REGISTRO_TIEMPOS)
    pendientes = obtener_pendientes(carpeta, registro)

    for archivo in pendientes:
        inicio = perf_counter()
        bloques = procesar_audio_con_pausas(archivo)
        duracion = perf_counter() - inicio
        registro[archivo] = bloques
        tiempos[archivo] = duracion
        guardar_registro(registro, REGISTRO)
        guardar_tiempos(tiempos, REGISTRO_TIEMPOS)
        print(f"Procesamiento de {archivo} completado en {duracion:.2f} segundos")


if __name__ == "__main__":
    import sys

    if len(sys.argv) != 2:
        print("Uso: python procesar_videos.py <carpeta>")
        sys.exit(1)

    main(sys.argv[1])

