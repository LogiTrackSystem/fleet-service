from fastapi import FastAPI
from .routers import vehicles, conductores

app = FastAPI(title="Fleet Service")
app.include_router(vehicles.router)
app.include_router(conductores.router)

@app.get("/health")
def health():
    return {"status": "ok", "service": "fleet-service"}