import os

from fastapi import FastAPI
from prometheus_fastapi_instrumentator import Instrumentator
from .interno import proteger_servicio
from .routers import vehicles, conductores, reservas

app = FastAPI(title="Fleet Service")
app.include_router(vehicles.router)
proteger_servicio(app)
app.include_router(conductores.router)
app.include_router(reservas.router)

# Métricas para Prometheus (GET /metrics): peticiones por método/estado y tiempos de respuesta
Instrumentator(excluded_handlers=["/metrics"]).instrument(app).expose(app, include_in_schema=False)


@app.get("/health")
def health():
    return {"status": "ok", "service": "fleet-service", "version": os.getenv("APP_VERSION", "dev")}