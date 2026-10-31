from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

from flask import Flask, abort, jsonify, render_template, request, send_from_directory
from werkzeug.utils import secure_filename

from converter import convert

BASE = Path(__file__).resolve().parent
OUTPUTS = BASE / "outputs"
KEPUBIFY = BASE / "tools" / "kepubify.exe"
app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 80 * 1024 * 1024


@app.get("/")
def home():
    return render_template("index.html", kepub_ready=KEPUBIFY.exists())


@app.post("/convert")
def process():
    upload = request.files.get("file")
    if not upload or not upload.filename or Path(upload.filename).suffix.lower() != ".pdf":
        return jsonify(error="Selecciona un archivo PDF válido."), 400
    name = secure_filename(upload.filename) or "libro.pdf"
    fmt = request.form.get("format", "kepub")
    if fmt not in ("epub", "kepub"):
        return jsonify(error="Formato de salida no válido."), 400
    if fmt == "kepub" and not KEPUBIFY.exists():
        return jsonify(error="Falta kepubify. Ejecuta instalar.ps1 para habilitar KEPUB."), 503
    with TemporaryDirectory() as temp:
        source = Path(temp) / name
        upload.save(source)
        try:
            job = uuid4().hex
            path, info = convert(
                source, OUTPUTS / job,
                title=request.form.get("title", "")[:180],
                author=request.form.get("author", "")[:180],
                keep_images=request.form.get("images") == "on",
                cover=request.form.get("cover") == "on",
                chapters=request.form.get("chapters") == "on",
                format=fmt, kepubify=KEPUBIFY,
                translation=request.form.get("translation", "none"),
            )
            return jsonify(download=f"/download/{job}/{path.name}", filename=path.name, **info)
        except Exception as exc:
            return jsonify(error=str(exc)), 422


@app.get("/download/<job>/<name>")
def download(job, name):
    if len(job) != 32 or any(ch not in "0123456789abcdef" for ch in job):
        abort(404)
    if not name.endswith((".epub", ".kepub.epub")):
        abort(404)
    return send_from_directory(OUTPUTS / job, name, as_attachment=True)


@app.errorhandler(413)
def too_large(_):
    return jsonify(error="El PDF supera el límite de 80 MB."), 413


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8765, debug=False)
