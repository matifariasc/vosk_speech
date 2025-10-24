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
    print(f"Procesando archivo: {archivo}")
    """Devuelve la transcripción en bloques con información de tiempo y medio.

    Se admiten archivos en formato MP4 y OGG.
    """

    extension = os.path.splitext(archivo)[1].lower()
    if extension not in {".mp4", ".ogg"}:
        raise ValueError("Solo se pueden procesar archivos MP4 u OGG")

    fd, wav_temp = tempfile.mkstemp(prefix="vosk_tmp_", suffix=".wav")
    os.close(fd)
    duracion_archivo_seg = 0.0
    wf = None
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
        duracion_archivo_seg = wf.getnframes() / float(wf.getframerate())

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

        def _crear_bloque(inicio_rel: float, fin_rel: float, texto: str) -> dict:
            duracion_rel = round(fin_rel - inicio_rel, 3)
            inicio_abs = (
                hora_inicio + timedelta(seconds=inicio_rel)
            ).strftime("%H:%M:%S.%f")[:-3]
            fin_abs = (
                hora_inicio + timedelta(seconds=fin_rel)
            ).strftime("%H:%M:%S.%f")[:-3]
            return {
                "texto": texto.strip(),
                "inicio": inicio_abs,
                "fin": fin_abs,
                "fecha": fecha,
                "duracion": duracion_rel,
                "medio": medio,
            }

        for i, palabra in enumerate(palabras):
            start = palabra["start"]
            end = palabra["end"]
            word = palabra["word"]

            if actual["inicio"] is None:
                actual["inicio"] = start

            if i > 0:
                pausa = start - palabras[i-1]["end"]
                if pausa > PAUSA_MAX and actual["fin"] is not None:
                    bloques.append(
                        _crear_bloque(actual["inicio"], actual["fin"], actual["texto"])
                    )
                    actual = {"inicio": start, "fin": None, "texto": ""}

            actual["fin"] = end
            actual["texto"] += word + " "

        # Agregar último bloque
        if actual["texto"].strip() and actual["fin"] is not None:
            bloques.append(
                _crear_bloque(actual["inicio"], actual["fin"], actual["texto"])
            )

    finally:
        try:
            # Cerrar si quedó abierto y limpiar temp
            if wf is not None:
                try:
                    wf.close()
                except Exception:
                    pass
            if os.path.exists(wav_temp):
                os.remove(wav_temp)
        except Exception:
            pass

    for b in bloques:
        print(f"[{b['inicio']} - {b['fin']}] {b['texto']}")

    return bloques, round(duracion_archivo_seg, 3)

if __name__ == "__main__":
    import sys
    if len(sys.argv) != 2:
        print(
            "Uso: python generador_audio.py <video.mp4|audio.ogg>  "
            "# se aceptan MP4 y OGG"
        )
    else:
        procesar_audio_con_pausas(sys.argv[1])
