from vosk import Model, KaldiRecognizer
import wave
import subprocess
import json
from datetime import datetime, timedelta
import os

PAUSA_MAX = 0.5  # segundos para cortar frase

def extraer_hora_desde_nombre(nombre_archivo):
    """Devuelve la fecha y hora como :class:`datetime` a partir del nombre."""

    partes = os.path.basename(nombre_archivo).split("_")
    fecha_str = partes[1]  # "YYYY-MM-DD"
    hora_str = partes[2]  # "21-00-08.mp4"
    return datetime.strptime(
        f"{fecha_str} {hora_str.replace('.mp4', '')}", "%Y-%m-%d %H-%M-%S"
    )

def procesar_audio_con_pausas(archivo_video, modelo_path="vosk-model-es-0.42"):
    """Devuelve la transcripción en bloques con información de tiempo y medio."""

    wav_temp = "temp.wav"
    subprocess.run(["ffmpeg", "-y", "-i", archivo_video, "-ar", "16000", "-ac", "1", "-f", "wav", wav_temp],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    wf = wave.open(wav_temp, "rb")
    model = Model(modelo_path)
    rec = KaldiRecognizer(model, wf.getframerate())
    rec.SetWords(True)

    hora_inicio = extraer_hora_desde_nombre(archivo_video)
    fecha = hora_inicio.strftime("%Y-%m-%d")
    medio = os.path.basename(os.path.dirname(archivo_video))
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

    os.remove(wav_temp)

    for b in bloques:
        print(f"[{b['inicio']} - {b['fin']}] {b['texto']}")

    return bloques

if __name__ == "__main__":
    import sys
    if len(sys.argv) != 2:
        print("Uso: python generador_audio.py <video.mp4>")
    else:
        procesar_audio_con_pausas(sys.argv[1])
