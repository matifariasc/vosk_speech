import json
import os
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse, parse_qs

REGISTRO = "transcripciones.json"
BASE_URL = "http://integra.ispaccess.conectamedia.cl:5232//Canal13/"


def cargar_registro():
    if os.path.exists(REGISTRO):
        with open(REGISTRO, "r", encoding="utf-8") as fh:
            return json.load(fh)
    return {}


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path != "/":
            self.send_error(404)
            return
        qs = parse_qs(parsed.query)
        archivo = qs.get("file", [None])[0]
        registro = cargar_registro()
        if archivo:
            datos = registro.get(archivo)
            if datos is None:
                self.send_error(404, "Archivo no encontrado")
                return
            respuesta = {
                "file": archivo,
                "url": BASE_URL + os.path.basename(archivo),
                "registros": datos,
            }
        else:
            respuesta = [
                {
                    "file": k,
                    "url": BASE_URL + os.path.basename(k),
                    "registros": v,
                }
                for k, v in registro.items()
            ]
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.end_headers()
        self.wfile.write(json.dumps(respuesta, ensure_ascii=False, indent=2).encode("utf-8"))


def run(port: int = 8000) -> None:
    server = HTTPServer(("", port), Handler)
    print(f"Servidor escuchando en http://localhost:{port}")
    server.serve_forever()


if __name__ == "__main__":
    from sys import argv

    port = int(argv[1]) if len(argv) > 1 else 8000
    run(port)
