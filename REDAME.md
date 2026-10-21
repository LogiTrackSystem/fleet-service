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
