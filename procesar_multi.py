"""Orquestador multi-canal para el procesador de videos.

Lee una configuración JSON con la lista de canales y ejecuta el procesamiento
para cada uno, de forma paralela o secuencial según configuración.

Ejemplo de configuración::

  {
    "media_base": "/srv/media",
    "channels": ["Canal13", "chv", "mega", "tvn"],
    "parallel": 4
  }

Uso:
  python procesar_multi.py [ruta_config_json]

Si no se entrega ruta, intenta cargar "channels.json" en el directorio actual.
"""

from __future__ import annotations

import json
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List

import procesar_videos as pv


def cargar_config(ruta: str) -> Dict[str, Any]:
    with open(ruta, "r", encoding="utf-8") as fh:
        cfg = json.load(fh)
    if not isinstance(cfg.get("channels"), list) or not cfg["channels"]:
        raise ValueError("Config inválida: 'channels' debe ser lista no vacía")
    return cfg


def procesar_canal(base: str, canal: str) -> str:
    carpeta = os.path.join(base, canal)
    if not os.path.isdir(carpeta):
        return f"Canal {canal}: carpeta no existe: {carpeta}"
    pv.main(carpeta)
    return f"Canal {canal}: OK"


def main(config_path: str) -> None:
    cfg = cargar_config(config_path)
    base = cfg.get("media_base", "/srv/media")
    canales: List[str] = cfg["channels"]
    parallel = int(cfg.get("parallel", min(4, len(canales))))
    parallel = max(1, min(parallel, len(canales)))

    print(f"Procesando {len(canales)} canales (parallel={parallel}) desde {base}")
    with ThreadPoolExecutor(max_workers=parallel) as ex:
        futs = {ex.submit(procesar_canal, base, c): c for c in canales}
        for fut in as_completed(futs):
            canal = futs[fut]
            try:
                msg = fut.result()
            except Exception as e:  # noqa: BLE001
                msg = f"Canal {canal}: ERROR: {e}"
            print(msg)


if __name__ == "__main__":
    import sys

    cfg_path = sys.argv[1] if len(sys.argv) > 1 else "channels.json"
    if not os.path.exists(cfg_path):
        print(
            "Uso: python procesar_multi.py <config.json>  # falta archivo de configuración"
        )
        raise SystemExit(1)
    main(cfg_path)

