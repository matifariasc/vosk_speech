"""Procesa multiples videos generando un archivo JSON con las transcripciones.

El script recorre una carpeta que contiene archivos MP4 con un nombre de la forma
```
<id>_YYYY-MM-DD_HH-MM-SS.mp4
```
y utiliza ``generador_audio.procesar_audio_con_pausas`` para obtener el texto
de cada uno. Los resultados se guardan en ``transcripciones.json``. Si una
entrada ya existe en el JSON, el video no se vuelve a procesar. Solo se
procesaran archivos cuya hora se encuentre dentro de las primeras 24 horas a
partir del primer archivo pendiente encontrado.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta
from typing import Dict

from generador_audio import procesar_audio_con_pausas, extraer_hora_desde_nombre


REGISTRO = "transcripciones.json"


def cargar_registro(ruta: str) -> Dict[str, str]:
    """Carga el archivo JSON de registro si existe."""

    if os.path.exists(ruta):
        with open(ruta, "r", encoding="utf-8") as fh:
            return json.load(fh)
    return {}


def guardar_registro(registro: Dict[str, str], ruta: str) -> None:
    """Guarda el registro de transcripciones a disco."""

    with open(ruta, "w", encoding="utf-8") as fh:
        json.dump(registro, fh, ensure_ascii=False, indent=2)


def obtener_pendientes(carpeta: str, procesados: Dict[str, str]) -> list[str]:
    """Devuelve la lista de archivos pendientes a procesar."""

    todos = [os.path.join(carpeta, f) for f in os.listdir(carpeta) if f.endswith(".mp4")]
    todos.sort()

    pendientes = []
    inicio = None
    for archivo in todos:
        if archivo in procesados:
            continue

        hora_archivo = extraer_hora_desde_nombre(archivo)
        if inicio is None:
            inicio = hora_archivo

        if hora_archivo - inicio < timedelta(hours=24):
            pendientes.append(archivo)

    return pendientes


def main(carpeta: str) -> None:
    registro = cargar_registro(REGISTRO)
    pendientes = obtener_pendientes(carpeta, registro)

    for archivo in pendientes:
        bloques = procesar_audio_con_pausas(archivo)
        texto = " ".join(b["texto"] for b in bloques)
        registro[archivo] = texto
        guardar_registro(registro, REGISTRO)


if __name__ == "__main__":
    import sys

    if len(sys.argv) != 2:
        print("Uso: python procesar_videos.py <carpeta>")
        sys.exit(1)

    main(sys.argv[1])

