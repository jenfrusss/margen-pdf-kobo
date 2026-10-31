from pathlib import Path
import subprocess
import json
from datetime import datetime, timezone
from tempfile import TemporaryDirectory
from threading import Lock, Event, Thread
from uuid import uuid4

from flask import Flask, abort, jsonify, render_template, request, send_from_directory
from werkzeug.utils import secure_filename

from converter import convert
from book_tools import analyze_pdf
from kobo_device import connected_kobos, copy_to_kobo, eject_kobo

BASE = Path(__file__).resolve().parent
OUTPUTS = BASE / "outputs"
UPLOADS = BASE / "uploads"
KEPUBIFY = BASE / "tools" / "kepubify.exe"
DEVICE_LOCK = Lock()
JOBS_LOCK = Lock()
JOBS = {}
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
            extra = {"epub_download": f"/download/{job}/{path.stem.removesuffix('.kepub')}.epub"} if fmt == "kepub" else {}
            return jsonify(download=f"/download/{job}/{path.name}", job=job, filename=path.name, **info, **extra)
        except Exception as exc:
            return jsonify(error=str(exc)), 422


@app.post("/analyze")
def analyze():
    upload = request.files.get("file")
    if not upload or not upload.filename or Path(upload.filename).suffix.lower() != ".pdf":
        return jsonify(error="Selecciona un PDF válido."), 400
    token = uuid4().hex
    folder = UPLOADS / token
    folder.mkdir(parents=True)
    source = folder / (secure_filename(upload.filename) or "libro.pdf")
    upload.save(source)
    try:
        return jsonify(token=token, filename=source.name, **analyze_pdf(source))
    except Exception as exc:
        source.unlink(missing_ok=True)
        folder.rmdir()
        return jsonify(error=str(exc)), 422


def _run_job(job, source, options, overrides, cancel):
    state = JOBS[job]
    def update(done, total, stage):
        with JOBS_LOCK:
            state.update(progress=min(95, round(done / max(total, 1) * 90)), stage=stage)
    try:
        path, info = convert(source, OUTPUTS / job,
            title=options.get("title", "")[:180], author=options.get("author", "")[:180],
            keep_images=options.get("images", True), cover=options.get("cover", True),
            chapters=options.get("chapters", True), format=options.get("format", "kepub"),
            kepubify=KEPUBIFY, translation=options.get("translation", "none"),
            ocr=options.get("ocr", True), overrides=overrides, progress=update, cancelled=cancel)
        extra = {"epub_download": f"/download/{job}/{path.stem.removesuffix('.kepub')}.epub"} if options.get("format", "kepub") == "kepub" else {}
        with JOBS_LOCK:
            state.update(status="done", progress=100, stage="Listo", download=f"/download/{job}/{path.name}", filename=path.name, **info, **extra)
    except InterruptedError:
        with JOBS_LOCK:
            state.update(status="cancelled", stage="Cancelado")
    except Exception as exc:
        with JOBS_LOCK:
            state.update(status="error", stage="Error", error=str(exc))
    finally:
        (OUTPUTS / job).mkdir(parents=True, exist_ok=True)
        (OUTPUTS / job / "status.json").write_text(json.dumps({key: value for key, value in state.items() if key != "cancel"}, ensure_ascii=False), encoding="utf-8")
        source.unlink(missing_ok=True)
        source.parent.rmdir()


@app.post("/start")
def start_job():
    data = request.get_json(silent=True) or {}
    token = data.get("token", "")
    filename = data.get("filename", "")
    if not isinstance(token, str) or len(token) != 32 or any(ch not in "0123456789abcdef" for ch in token):
        return jsonify(error="Archivo temporal no válido."), 400
    if not isinstance(filename, str) or Path(filename).name != filename:
        return jsonify(error="Nombre no válido."), 400
    source = UPLOADS / token / filename
    if not source.is_file():
        return jsonify(error="El PDF ya no está disponible. Cárgalo otra vez."), 404
    options = data.get("options", {})
    if not isinstance(options, dict) or options.get("format", "kepub") not in ("epub", "kepub") or options.get("translation", "none") not in ("none", "es-en", "en-es"):
        return jsonify(error="Opciones no válidas."), 400
    if options.get("format", "kepub") == "kepub" and not KEPUBIFY.exists():
        return jsonify(error="Falta kepubify. Ejecuta instalar.ps1."), 503
    overrides = data.get("overrides", {})
    if not isinstance(overrides, dict):
        return jsonify(error="Cambios de vista previa no válidos."), 400
    with JOBS_LOCK:
        if token in JOBS:
            return jsonify(error="Este archivo ya se está procesando."), 409
        cancel = Event()
        JOBS[token] = {"job": token, "status": "running", "progress": 0, "stage": "Preparando", "source": filename,
                       "created": datetime.now(timezone.utc).isoformat(), "cancel": cancel}
    Thread(target=_run_job, args=(token, source, options, overrides, cancel), daemon=True).start()
    return jsonify(job=token), 202


@app.get("/jobs/<job>")
def job_status(job):
    if job in JOBS:
        with JOBS_LOCK:
            return jsonify({key: value for key, value in JOBS[job].items() if key != "cancel"})
    path = OUTPUTS / job / "status.json"
    if len(job) == 32 and all(ch in "0123456789abcdef" for ch in job) and path.is_file():
        return jsonify(json.loads(path.read_text(encoding="utf-8")))
    abort(404)


@app.post("/jobs/<job>/cancel")
def cancel_job(job):
    with JOBS_LOCK:
        state = JOBS.get(job)
        if not state or state["status"] != "running":
            return jsonify(error="El proceso ya terminó."), 409
        state["cancel"].set()
    return jsonify(message="Cancelación solicitada.")


@app.get("/history")
def history():
    records = []
    for path in sorted(OUTPUTS.glob("*/status.json"), key=lambda item: item.stat().st_mtime, reverse=True)[:30]:
        try:
            records.append(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            continue
    return jsonify(jobs=records)


@app.get("/download/<job>/<name>")
def download(job, name):
    if len(job) != 32 or any(ch not in "0123456789abcdef" for ch in job):
        abort(404)
    if not name.endswith((".epub", ".kepub.epub")):
        abort(404)
    return send_from_directory(OUTPUTS / job, name, as_attachment=True)


@app.get("/devices")
def devices():
    return jsonify(devices=connected_kobos())


@app.post("/send-to-kobo")
def send_to_kobo():
    data = request.get_json(silent=True) or {}
    job = data.get("job", "")
    filename = data.get("filename", "")
    device_id = data.get("device", "")
    if not isinstance(job, str) or len(job) != 32 or any(ch not in "0123456789abcdef" for ch in job):
        return jsonify(error="Libro no válido."), 400
    if not isinstance(filename, str) or Path(filename).name != filename or not filename.endswith(".epub"):
        return jsonify(error="Nombre de libro no válido."), 400
    if not isinstance(device_id, str):
        return jsonify(error="Selecciona un Kobo válido."), 400
    try:
        with DEVICE_LOCK:
            path = copy_to_kobo(OUTPUTS / job / filename, device_id)
        return jsonify(path=path)
    except (ValueError, OSError) as exc:
        return jsonify(error=str(exc)), 422


@app.post("/eject-kobo")
def eject_device():
    data = request.get_json(silent=True) or {}
    device_id = data.get("device", "")
    if not isinstance(device_id, str):
        return jsonify(error="Selecciona un Kobo válido."), 400
    try:
        with DEVICE_LOCK:
            eject_kobo(device_id)
        return jsonify(message="Kobo expulsado con seguridad. Ya puedes desconectarlo.")
    except (ValueError, OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
        return jsonify(error=str(exc)), 422


@app.errorhandler(413)
def too_large(_):
    return jsonify(error="El PDF supera el límite de 80 MB."), 413


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8765, debug=False)
