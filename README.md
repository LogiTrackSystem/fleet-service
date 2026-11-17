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
- `POST /vehiculos/` — crear vehículo. La **ubicación base es obligatoria** (`ubicacion_id`, `ubicacion_nombre`, `latitud`, `longitud`, `codigo_pais`, tomados de la ubicación elegida en `GET /ubicaciones`); el vehículo nace con ubicación confiable y se puede asignar de inmediato
- `GET /vehiculos/{id}` — obtener vehículo por id
- `GET /conductores/` — listar conductores
- `POST /conductores/` — crear conductor

## Ubicación real, cercanía y carga compartida

**Última ubicación real.** Cada vehículo guarda dónde quedó realmente (`latitud`, `longitud`, `codigo_pais`, `ubicacion_actualizada_en`, `ubicacion_fuente`, `ubicacion_confiable`). Quien la escribe es Tracking al terminar un viaje (`entrega`) o al interrumpirse (`interrupcion`); el gestor de flota registra la ubicación base de los vehículos que ya existían (`registro_gestor`, solo con el vehículo libre). Una posición más vieja que la guardada se ignora, y mientras un vehículo viaja su ubicación figura como no fiable (nunca se inventa una).

- `PUT /vehiculos/{id}/ubicacion` — fija la ubicación (`409 VEHICULO_EN_VIAJE` si un gestor intenta moverlo en pleno viaje).
- `GET /vehiculos/{id}/ocupacion` — peso y volumen reservados, disponibles y cargas a bordo.

**Elección por cercanía.** `POST /reservas/` acepta `origen` (`latitud`, `longitud`, `codigo_pais`) y `excluir_vehiculos`. Después de filtrar por compatibilidad, disponibilidad y capacidad, elige el vehículo con menor distancia **en línea recta** a ese origen (empate: menor capacidad, luego placa). Sin ubicación fiable queda de último recurso. Sin `origen` mantiene el criterio anterior (menor capacidad suficiente). La respuesta incluye `reposicion.desde` (de dónde saldría) y `decision`.

**Carga compartida.** `POST /reservas/compartida` suma un envío al viaje de un vehículo en curso, bajo candado de la fila del vehículo: valida peso, volumen, HAZMAT (siempre exclusivo) y tipo de carga (refrigerada y general no se mezclan). Idempotente por `envio_id`. `POST /reservas/liberar` solo libera el vehículo y el conductor cuando sale la **última** carga. `POST /reservas/conciliar` recalcula los contadores de peso/volumen desde las reservas activas; bloquea todos los vehículos mientras corre, así que conviene usarlo fuera de horas pico (durante esos instantes una reserva nueva responde 409 y Routing la reintenta). `PUT /vehiculos/{id}/ubicacion` rechaza (`aplicada: false`) el reenvío de la misma posición cuando el vehículo ya salió con otra carga. `DB_LOCK_TIMEOUT_MS` (15000 por defecto, 0 = sin límite) acota la espera por candados de fila.

**Variables nuevas**
- `MAX_REPOSICION_KM` (por defecto 1500; 0 = sin tope): distancia máxima en línea recta del vehículo vacío hasta el origen.
- `REPOSICION_INTERNACIONAL` (por defecto `false`): si es `false`, un vehículo vacío no cruza fronteras para recoger.

**Migración** `d4e8a1c7b952`: solo agrega columnas y reemplaza el índice único de "una reserva por vehículo" por "una reserva exclusiva por vehículo" (las reservas activas existentes quedan como vehículo completo).

---

<!-- entrega-final -->

## Descripción

Vehículos, conductores y reservas atómicas de vehículo por envío; calcula la viabilidad de un pedido y su división entre varios vehículos.

- **Puerto local:** 8000   ·   **Despliegue activo:** <https://logitrack-fleet.onrender.com> (`/health` y `/metrics` públicos)
- **Imagen Docker:** `<usuario-dockerhub>/logitrack-fleet`   ·   **Repositorio de CI/CD:** `LogiTrackSystem/pipelines`

## Variables de entorno

Copia `.env.example` como `.env` y completa los valores. El `.env` **no se sube** al repositorio.

| Variable | Para qué sirve |
|---|---|
| `DATABASE_URL` | Conexión a la base PostgreSQL del servicio (`postgresql://usuario:clave@host:5432/<base>`). Es un secreto. |
| `INTERNAL_API_KEY` | Clave compartida entre el gateway y los servicios: exige la cabecera `X-Internal-Key` en todas las rutas salvo `/health` y `/metrics`. Vacía = sin restricción (solo local). Es un secreto. |
| `MAX_REPOSICION_KM` | Tope de km en línea recta entre el vehículo y el origen del envío; 0 = sin tope. |
| `REPOSICION_INTERNACIONAL` | `false` = un vehículo vacío no cruza fronteras para ir a recoger. |
| `DB_LOCK_TIMEOUT_MS` | Espera máxima (ms) por un candado de fila antes de fallar; 0 = sin límite. |

## Documentación de la API

- **Local** (sin `INTERNAL_API_KEY`): <http://localhost:8000/docs> (Swagger) y `http://localhost:8000/openapi.json`.
- **Producción:** el servicio solo atiende peticiones que llegan por el gateway (con `INTERNAL_API_KEY` activa su `/docs` no es público); la documentación de todas las rutas está en <https://logitrack-gateway.onrender.com/docs>.

## Base de datos

- Migraciones con Alembic (`alembic/`): `alembic upgrade head` (el `Dockerfile` ya lo ejecuta al arrancar).
- `db/esquema.sql`: esquema completo de `fleet_db` generado desde las migraciones.
- `db/datos_ejemplo.sql`: datos de ejemplo ficticios para pruebas manuales.
- Respaldo y restauración: ver `db/README.md`.

## Pruebas

Con el entorno virtual activo y `pip install -r requirements-dev.txt`:

```
pytest tests/unit                    # 2 pruebas unitarias
pytest tests/integration             # 1 prueba de integración
pytest --cov=app --cov-report=term   # toda la suite con cobertura
```

| Prueba | Qué verifica |
|---|---|
| Unitaria 1 | `division.planificar` |
| Unitaria 2 | `elegibilidad.errores_de_elegibilidad` |
| Integración | alta de un vehículo, consulta por placa y cambio de estado |

Archivos: `tests/unit/` y `tests/integration/` (test_planificar_division.py, test_elegibilidad_conductor.py, test_flujo_vehiculo.py). Cobertura de `app/` medida: **≈ 85 %**; en cada push y Pull Request GitHub Actions la recalcula y guarda `coverage.xml` como artefacto (`cobertura-fleet`).

## Métricas y monitoreo

Expone `GET /metrics` (formato Prometheus: `http_requests_total` y `http_request_duration_*`). Prometheus y el dashboard de Grafana están en el repositorio `logitrack-monitoring`.

## CI/CD

- `.github/workflows/pr.yml`: en cada push (rama distinta de `main`) y en cada Pull Request a `main` ejecuta el CI reutilizable (lint, pruebas con cobertura, `docker build` y prueba de arranque).
- `.github/workflows/deploy.yml`: al fusionar en `main`, y solo con las pruebas en verde, publica la imagen en Docker Hub y despliega en Render (con verificación de `/health` y rollback manual).
- Detalle y estrategia de ramas: `CICD.md` en el repositorio `LogiTrackSystem/pipelines`.

