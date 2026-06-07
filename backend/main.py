"""
Tizada Automática IFK Sports - Backend
True Shape Nesting con algoritmo NFP
"""

import os
import io
import json
import math
import asyncio
from typing import List, Dict, Optional, Tuple
from fastapi import FastAPI, UploadFile, File, Form, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
import uvicorn

from nesting import NestingEngine
from svg_parser import SVGParser
from image_exporter import ImageExporter

app = FastAPI(title="Tizada Automática IFK Sports")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Servir frontend estático
frontend_path = os.path.join(os.path.dirname(__file__), "..", "frontend")
if os.path.exists(frontend_path):
    app.mount("/static", StaticFiles(directory=os.path.join(frontend_path, "static")), name="static")

# Estado de jobs activos
active_jobs: Dict[str, dict] = {}
job_websockets: Dict[str, List[WebSocket]] = {}


@app.get("/")
async def root():
    index_path = os.path.join(frontend_path, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return {"status": "Tizada API corriendo"}


@app.post("/api/parse-svgs")
async def parse_svgs(files: List[UploadFile] = File(...)):
    """
    Recibe SVGs, extrae contornos y devuelve info de cada pieza
    """
    parser = SVGParser()
    piezas = []

    for file in files:
        content = await file.read()
        try:
            info = parser.parse(content, file.filename)
            piezas.append({
                "filename": file.filename,
                "nombre_sugerido": info["nombre_sugerido"],
                "talle_sugerido": info["talle_sugerido"],
                "ancho_mm": round(info["ancho_mm"], 1),
                "alto_mm": round(info["alto_mm"], 1),
                "area_mm2": round(info["area_mm2"], 0),
                "contorno_ok": info["contorno_ok"],
                "svg_data": content.decode("utf-8", errors="replace"),
            })
        except Exception as e:
            piezas.append({
                "filename": file.filename,
                "error": str(e),
                "contorno_ok": False,
            })

    return {"piezas": piezas}


@app.post("/api/iniciar-tizada")
async def iniciar_tizada(request: dict):
    """
    Inicia el proceso de nesting en background
    Devuelve un job_id para seguir el progreso via WebSocket
    """
    import uuid
    import threading

    job_id = str(uuid.uuid4())[:8]
    active_jobs[job_id] = {"status": "iniciando", "progreso": 0, "mensaje": "Iniciando..."}
    job_websockets[job_id] = []

    # Correr en thread separado
    def run_job():
        try:
            _ejecutar_tizada(job_id, request)
        except Exception as e:
            active_jobs[job_id]["status"] = "error"
            active_jobs[job_id]["error"] = str(e)
            _notify(job_id)

    thread = threading.Thread(target=run_job, daemon=True)
    thread.start()

    return {"job_id": job_id}


def _notify(job_id: str):
    """Notifica a todos los websockets conectados al job"""
    import asyncio
    data = json.dumps(active_jobs.get(job_id, {}))
    for ws in job_websockets.get(job_id, []):
        try:
            asyncio.run(ws.send_text(data))
        except Exception:
            pass


def _update_job(job_id: str, **kwargs):
    if job_id in active_jobs:
        active_jobs[job_id].update(kwargs)
    _notify(job_id)


def _ejecutar_tizada(job_id: str, request: dict):
    """Ejecuta el proceso completo de nesting"""
    import tempfile

    piezas_config = request.get("piezas", [])  # [{svg_data, nombre, talle, cantidad}]
    ancho_rollo_mm = request.get("ancho_rollo_mm", 1600)
    largo_max_mm = request.get("largo_max_mm", 3500)
    espacio_mm = request.get("espacio_mm", 7)
    perfil_color = request.get("perfil_color", "sRGB")

    _update_job(job_id, status="procesando", progreso=5, mensaje="Parseando SVGs...")

    parser = SVGParser()
    engine = NestingEngine(
        ancho_rollo_mm=ancho_rollo_mm,
        espacio_mm=espacio_mm,
    )

    # 1. Parsear todas las piezas
    piezas_parsed = []
    total = len(piezas_config)
    for i, p in enumerate(piezas_config):
        if p.get("cantidad", 0) <= 0:
            continue
        try:
            svg_bytes = p["svg_data"].encode("utf-8")
            info = parser.parse(svg_bytes, p.get("filename", "pieza.svg"))
            piezas_parsed.append({
                "nombre": p.get("nombre", "pieza"),
                "talle": p.get("talle", ""),
                "cantidad": int(p.get("cantidad", 1)),
                "contorno": info["contorno"],  # lista de (x,y) en mm
                "ancho_mm": info["ancho_mm"],
                "alto_mm": info["alto_mm"],
                "svg_data": p["svg_data"],
            })
        except Exception as e:
            print(f"Error parseando {p.get('filename')}: {e}")

        pct = 5 + int((i + 1) / total * 15)
        _update_job(job_id, progreso=pct, mensaje=f"Parseando pieza {i+1}/{total}...")

    if not piezas_parsed:
        _update_job(job_id, status="error", error="No se pudieron parsear las piezas")
        return

    _update_job(job_id, progreso=22, mensaje="Calculando nesting...")

    # 2. Ejecutar nesting
    layout = engine.nest(piezas_parsed, progress_callback=lambda p, m: _update_job(
        job_id, progreso=22 + int(p * 0.5), mensaje=m
    ))

    metros_total = layout["alto_total_mm"] / 1000
    n_hojas = layout["n_hojas"]

    _update_job(
        job_id,
        progreso=72,
        mensaje=f"Generando imágenes ({n_hojas} hoja(s))...",
        metros_total=round(metros_total, 2),
        n_hojas=n_hojas,
    )

    # 3. Generar JPGs
    exporter = ImageExporter(dpi=300, perfil_color=perfil_color)
    output_dir = tempfile.mkdtemp()
    archivos_generados = []

    for i, hoja in enumerate(layout["hojas"]):
        pct = 72 + int((i + 1) / n_hojas * 20)
        metros_hoja = hoja["alto_mm"] / 1000
        _update_job(job_id, progreso=pct, mensaje=f"Renderizando hoja {i+1}/{n_hojas}...")

        nombre_archivo = f"tizada_{i+1:02d}_de_{n_hojas:02d}_{metros_hoja:.2f}m.jpg"
        ruta = os.path.join(output_dir, nombre_archivo)

        exporter.exportar_hoja(
            hoja=hoja,
            ancho_mm=ancho_rollo_mm,
            ruta_salida=ruta,
        )
        archivos_generados.append({
            "nombre": nombre_archivo,
            "ruta": ruta,
            "metros": round(metros_hoja, 2),
        })

    _update_job(
        job_id,
        status="completado",
        progreso=100,
        mensaje="¡Tizada lista!",
        metros_total=round(metros_total, 2),
        n_hojas=n_hojas,
        archivos=archivos_generados,
        output_dir=output_dir,
    )


@app.websocket("/ws/{job_id}")
async def websocket_progress(websocket: WebSocket, job_id: str):
    await websocket.accept()
    if job_id not in job_websockets:
        job_websockets[job_id] = []
    job_websockets[job_id].append(websocket)

    try:
        # Enviar estado actual inmediatamente
        if job_id in active_jobs:
            await websocket.send_text(json.dumps(active_jobs[job_id]))

        # Mantener conexión
        while True:
            try:
                await asyncio.wait_for(websocket.receive_text(), timeout=1.0)
            except asyncio.TimeoutError:
                # Enviar ping / estado actual
                if job_id in active_jobs:
                    await websocket.send_text(json.dumps(active_jobs[job_id]))
                    if active_jobs[job_id].get("status") in ("completado", "error"):
                        break
    except WebSocketDisconnect:
        pass
    finally:
        if job_id in job_websockets and websocket in job_websockets[job_id]:
            job_websockets[job_id].remove(websocket)


@app.get("/api/descargar/{job_id}/{nombre_archivo}")
async def descargar_archivo(job_id: str, nombre_archivo: str):
    job = active_jobs.get(job_id)
    if not job or job.get("status") != "completado":
        return JSONResponse({"error": "Job no encontrado o no completado"}, status_code=404)

    for arch in job.get("archivos", []):
        if arch["nombre"] == nombre_archivo:
            return FileResponse(
                arch["ruta"],
                filename=nombre_archivo,
                media_type="image/jpeg",
            )

    return JSONResponse({"error": "Archivo no encontrado"}, status_code=404)


@app.get("/api/job/{job_id}")
async def get_job_status(job_id: str):
    job = active_jobs.get(job_id)
    if not job:
        return JSONResponse({"error": "Job no encontrado"}, status_code=404)
    # No devolver rutas internas
    safe = {k: v for k, v in job.items() if k not in ("output_dir",)}
    if "archivos" in safe:
        safe["archivos"] = [{"nombre": a["nombre"], "metros": a["metros"]} for a in safe["archivos"]]
    return safe


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))
