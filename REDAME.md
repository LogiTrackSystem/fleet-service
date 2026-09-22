# Fleet Service

Microservicio de LogiTrack encargado de la gestión de vehículos y conductores.

## Stack
FastAPI + SQLAlchemy + Alembic + PostgreSQL.

## Levantar en local
1. `python -m venv venv && venv\Scripts\activate`
2. `pip install -r requirements.txt`
3. Copiar `.env.example` a `.env` y completar con tus credenciales locales.
4. Crear la base de datos `fleet_db` en tu PostgreSQL local.
5. `alembic upgrade head`
6. `uvicorn app.main:app --reload --port 8000`

## Endpoints
- `GET /health`
- `GET /vehiculos/` — listar vehículos
- `POST /vehiculos/` — crear vehículo
- `GET /vehiculos/{id}` — obtener vehículo por id
- `GET /conductores/` — listar conductores
- `POST /conductores/` — crear conductor