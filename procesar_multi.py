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
from typing import Any, Dict, List, Tuple

import procesar_videos as pv


def cargar_config(ruta: str) -> Dict[str, Any]:
    with open(ruta, "r", encoding="utf-8") as fh:
        cfg = json.load(fh)
    if not isinstance(cfg.get("channels"), list) or not cfg["channels"]:
        raise ValueError("Config inválida: 'channels' debe ser lista no vacía")
    return cfg


def _normalizar_canales(raw: List[Any]) -> List[Tuple[str, bool]]:
    """Convierte la configuración cruda en tuplas (nombre, send_to_api)."""
    canales: List[Tuple[str, bool]] = []
    for item in raw:
        if isinstance(item, str):
            canales.append((item, False))
            continue
        if isinstance(item, dict):
            nombre = item.get("name") or item.get("channel") or item.get("medio")
            if not nombre or not isinstance(nombre, str):
                raise ValueError("Canal inválido: falta nombre en entrada de objeto")
            valor = item.get("send_to_api")
            if valor is None:
                valor = item.get("cuos") or item.get("enviar")
            canales.append((nombre, bool(valor)))
            continue
        raise ValueError("Entrada de canal debe ser string o dict con 'name'")
    return canales


def procesar_canal(base: str, canal: str, send_to_api: bool) -> str:
    carpeta = os.path.join(base, canal)
    if not os.path.isdir(carpeta):
        return f"Canal {canal}: carpeta no existe: {carpeta}"
    pv.main(carpeta, send_to_api=send_to_api)
    return f"Canal {canal}: OK"


def main(config_path: str) -> None:
    cfg = cargar_config(config_path)
    base = cfg.get("media_base", "/srv/media")
    canales_cfg = _normalizar_canales(cfg["channels"])
    nombres = [c[0] for c in canales_cfg]
    parallel = int(cfg.get("parallel", min(4, len(canales_cfg))))
    parallel = max(1, min(parallel, len(canales_cfg)))

    print(f"Procesando {len(nombres)} canales (parallel={parallel}) desde {base}")
    with ThreadPoolExecutor(max_workers=parallel) as ex:
        futs = {
            ex.submit(procesar_canal, base, canal, send): canal
            for canal, send in canales_cfg
        }
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
