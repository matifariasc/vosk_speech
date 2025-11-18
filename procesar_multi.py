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
import time
from queue import Queue
from threading import Lock, Thread
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


def procesar_en_cola(
    base: str, canales_cfg: List[Tuple[str, bool]], parallel: int, loop_minutes: float
) -> None:
    """Ejecuta con cola FIFO estilo worker-pool.

    Encola todos los canales en orden y va agregando nuevamente el listado completo
    cada ``loop_minutes``. Si ``loop_minutes`` es 0, procesa solo una vuelta.
    """

    cola: Queue = Queue()
    lock = Lock()
    busy_count = 0

    def worker() -> None:
        while True:
            item = cola.get()
            if item is None:
                cola.task_done()
                break
            ciclo, idx = item  # idx solo para preservar el orden de llegada
            canal, send = canales_cfg[idx]
            with lock:
                # Contamos el worker como ocupado
                nonlocal busy_count
                busy_count += 1
                ocupados = busy_count
                libres = max(0, parallel - ocupados)
            print(f"[ciclo {ciclo}] INICIO {canal} (ocupados={ocupados}, libres={libres})")
            try:
                msg = procesar_canal(base, canal, send)
            except Exception as e:  # noqa: BLE001
                msg = f"Canal {canal}: ERROR: {e}"
            with lock:
                busy_count -= 1
                ocupados = busy_count
                libres = max(0, parallel - ocupados)
            print(f"[ciclo {ciclo}] {msg} (ocupados={ocupados}, libres={libres})")
            cola.task_done()

    threads = [Thread(target=worker, daemon=True) for _ in range(parallel)]
    for t in threads:
        t.start()

    ciclo = 0
    try:
        while True:
            ciclo += 1
            for idx in range(len(canales_cfg)):
                cola.put((ciclo, idx))
            if loop_minutes <= 0:
                break
            time.sleep(loop_minutes * 60)
    except KeyboardInterrupt:
        print("Interrumpido; esperando a que terminen trabajos en curso...")
    finally:
        # Esperamos que se drene la cola antes de apagar los workers
        cola.join()
        for _ in threads:
            cola.put(None)
        for t in threads:
            t.join()


def main(config_path: str) -> None:
    cfg = cargar_config(config_path)
    base = cfg.get("media_base", "/srv/media")
    canales_cfg = _normalizar_canales(cfg["channels"])
    nombres = [c[0] for c in canales_cfg]
    parallel = int(cfg.get("parallel", min(4, len(canales_cfg))))
    parallel = max(1, parallel)  # permitir más hilos que canales, quedan en espera
    loop_minutes = float(cfg.get("loop_minutes", 0))

    print(
        f"Procesando {len(nombres)} canales (parallel={parallel}, loop_minutes={loop_minutes}) desde {base}"
    )
    procesar_en_cola(base, canales_cfg, parallel, loop_minutes)


if __name__ == "__main__":
    import sys

    cfg_path = sys.argv[1] if len(sys.argv) > 1 else "channels.json"
    if not os.path.exists(cfg_path):
        print(
            "Uso: python procesar_multi.py <config.json>  # falta archivo de configuración"
        )
        raise SystemExit(1)
    main(cfg_path)
