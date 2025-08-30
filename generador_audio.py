from vosk import Model, KaldiRecognizer
import wave
import subprocess
import json
from datetime import datetime, timedelta
import os
import tempfile
import threading

_MODEL_CACHE = {}
_MODEL_LOCK = threading.Lock()

def _get_model(modelo_path: str) -> Model:
    """Carga y cachea el modelo Vosk por proceso.

    Evita recargar el modelo en cada archivo (costoso y verboso en logs).
    """
    m = _MODEL_CACHE.get(modelo_path)
    if m is not None:
        return m
    # Evitar condiciones de carrera en carga inicial
    with _MODEL_LOCK:
        m = _MODEL_CACHE.get(modelo_path)
        if m is None:
            m = Model(modelo_path)
            _MODEL_CACHE[modelo_path] = m
        return m

PAUSA_MAX = 0.5  # segundos para cortar frase

def extraer_hora_desde_nombre(nombre_archivo):
    """Devuelve la fecha y hora como :class:`datetime` a partir del nombre."""

    base, _ = os.path.splitext(os.path.basename(nombre_archivo))
    partes = base.split("_")
    if len(partes) < 3:
        raise ValueError(f"Nombre de archivo invalido: {nombre_archivo}")
    fecha_str = partes[1]
    hora_str = partes[2]
    return datetime.strptime(f"{fecha_str} {hora_str}", "%Y-%m-%d %H-%M-%S")

def procesar_audio_con_pausas(archivo, modelo_path="vosk-model-es-0.42"):
    """Devuelve la transcripción en bloques con información de tiempo y medio.

    Se admiten archivos en formato MP4 y OGG.
    """

    extension = os.path.splitext(archivo)[1].lower()
    if extension not in {".mp4", ".ogg"}:
        raise ValueError("Solo se pueden procesar archivos MP4 u OGG")

    fd, wav_temp = tempfile.mkstemp(prefix="vosk_tmp_", suffix=".wav")
    os.close(fd)
    try:
        proc = subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-i",
                archivo,
                "-ar",
                "16000",
                "-ac",
                "1",
                "-f",
                "wav",
                wav_temp,
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        if proc.returncode != 0:
            raise RuntimeError("ffmpeg fallo al convertir a wav")

        wf = wave.open(wav_temp, "rb")
        try:
            model = _get_model(modelo_path)
            rec = KaldiRecognizer(model, wf.getframerate())
            rec.SetWords(True)
        except Exception:
            wf.close()
            raise
        
        hora_inicio = extraer_hora_desde_nombre(archivo)
        fecha = hora_inicio.strftime("%Y-%m-%d")
        medio = os.path.basename(os.path.dirname(archivo))
        palabras = []

        while True:
            data = wf.readframes(4000)
            if len(data) == 0:
                break
            if rec.AcceptWaveform(data):
                res = json.loads(rec.Result())
                palabras.extend(res.get("result", []))

        bloques = []
        actual = {"inicio": None, "fin": None, "texto": ""}

        for i, palabra in enumerate(palabras):
            start = palabra["start"]
            end = palabra["end"]
            word = palabra["word"]

            if actual["inicio"] is None:
                actual["inicio"] = start

            if i > 0:
                pausa = start - palabras[i-1]["end"]
                if pausa > PAUSA_MAX:
                    # Guardar bloque anterior
                    bloque = {
                        "texto": actual["texto"].strip(),
                        "inicio": (
                            hora_inicio + timedelta(seconds=actual["inicio"])
                        ).strftime("%H:%M:%S.%f")[:-3],
                        "fin": (
                            hora_inicio + timedelta(seconds=actual["fin"])
                        ).strftime("%H:%M:%S.%f")[:-3],
                        "fecha": fecha,
                        "medio": medio,
                    }
                    bloques.append(bloque)
                    actual = {"inicio": start, "texto": ""}

            actual["texto"] += word + " "
            actual["fin"] = end

        # Agregar último bloque
        if actual["texto"].strip():
            bloques.append(
                {
                    "texto": actual["texto"].strip(),
                    "inicio": (
                        hora_inicio + timedelta(seconds=actual["inicio"])
                    ).strftime("%H:%M:%S.%f")[:-3],
                    "fin": (
                        hora_inicio + timedelta(seconds=actual["fin"])
                    ).strftime("%H:%M:%S.%f")[:-3],
                    "fecha": fecha,
                    "medio": medio,
                }
            )

    finally:
        try:
            # Cerrar si quedó abierto y limpiar temp
            try:
                wf.close()  # type: ignore[name-defined]
            except Exception:
                pass
            if os.path.exists(wav_temp):
                os.remove(wav_temp)
        except Exception:
            pass

    for b in bloques:
        print(f"[{b['inicio']} - {b['fin']}] {b['texto']}")

    return bloques

if __name__ == "__main__":
    import sys
    if len(sys.argv) != 2:
        print(
            "Uso: python generador_audio.py <video.mp4|audio.ogg>  "
            "# se aceptan MP4 y OGG"
        )
    else:
        procesar_audio_con_pausas(sys.argv[1])
