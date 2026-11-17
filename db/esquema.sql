-- Esquema de fleet_db (fleet-service): SQL generado por 'alembic upgrade head --sql' a partir de alembic/versions.
-- Crea todas las tablas, secuencias y restricciones. No contiene datos.
BEGIN;

CREATE TABLE alembic_version (
    version_num VARCHAR(32) NOT NULL, 
    CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num)
);

-- Running upgrade  -> a7b69aeffaea

CREATE TABLE vehiculos (
    id UUID NOT NULL, 
    placa VARCHAR(10) NOT NULL, 
    tipo VARCHAR(50) NOT NULL, 
    capacidad_kg NUMERIC(10, 2) NOT NULL, 
    capacidad_m3 NUMERIC(10, 2), 
    anio INTEGER, 
    vencimiento_seguro DATE, 
    estado VARCHAR(20) NOT NULL, 
    capacidad_refrigeracion BOOLEAN NOT NULL, 
    certificado_hazmat BOOLEAN NOT NULL, 
    PRIMARY KEY (id), 
    UNIQUE (placa)
);

CREATE TABLE conductores (
    id UUID NOT NULL, 
    nombre VARCHAR(150) NOT NULL, 
    licencia_numero VARCHAR(50) NOT NULL, 
    categorias_licencia VARCHAR(100), 
    certificacion_hazmat BOOLEAN NOT NULL, 
    vehiculo_id UUID, 
    horas_semanales NUMERIC(5, 2), 
    estado VARCHAR(20) NOT NULL, 
    PRIMARY KEY (id), 
    FOREIGN KEY(vehiculo_id) REFERENCES vehiculos (id), 
    UNIQUE (licencia_numero)
);

INSERT INTO alembic_version (version_num) VALUES ('a7b69aeffaea') RETURNING alembic_version.version_num;

-- Running upgrade a7b69aeffaea -> 2c5eba2acca5

CREATE SEQUENCE IF NOT EXISTS seq_codigo_conductor START WITH 1000000001 MINVALUE 1000000001 MAXVALUE 9999999999;

ALTER TABLE conductores ADD COLUMN codigo_conductor BIGINT DEFAULT nextval('seq_codigo_conductor') NOT NULL;

ALTER TABLE conductores ADD CONSTRAINT uq_conductores_codigo_conductor UNIQUE (codigo_conductor);

ALTER SEQUENCE seq_codigo_conductor OWNED BY conductores.codigo_conductor;

ALTER TABLE conductores ADD COLUMN anios_experiencia INTEGER DEFAULT '0' NOT NULL;

ALTER TABLE vehiculos ADD COLUMN capacidad_tanque_l NUMERIC(6, 2);

ALTER TABLE vehiculos ADD COLUMN consumo_km_por_litro NUMERIC(5, 2);

ALTER TABLE vehiculos ADD COLUMN tipo_combustible VARCHAR(20);

UPDATE alembic_version SET version_num='2c5eba2acca5' WHERE alembic_version.version_num = 'a7b69aeffaea';

-- Running upgrade 2c5eba2acca5 -> a5cc19f885bb

ALTER TABLE conductores ADD CONSTRAINT uq_conductores_vehiculo_id UNIQUE (vehiculo_id);

UPDATE alembic_version SET version_num='a5cc19f885bb' WHERE alembic_version.version_num = '2c5eba2acca5';

-- Running upgrade a5cc19f885bb -> 3a7fe1bab681

CREATE TABLE reservas_flota (
    id UUID NOT NULL, 
    envio_id UUID NOT NULL, 
    vehiculo_id UUID NOT NULL, 
    conductor_id UUID NOT NULL, 
    estado VARCHAR(20) DEFAULT 'reservada' NOT NULL, 
    creado_en TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    liberado_en TIMESTAMP WITH TIME ZONE, 
    PRIMARY KEY (id), 
    FOREIGN KEY(vehiculo_id) REFERENCES vehiculos (id), 
    FOREIGN KEY(conductor_id) REFERENCES conductores (id)
);

CREATE UNIQUE INDEX uq_reserva_activa_por_envio ON reservas_flota (envio_id) WHERE estado = 'reservada';

CREATE UNIQUE INDEX uq_reserva_activa_por_vehiculo ON reservas_flota (vehiculo_id) WHERE estado = 'reservada';

UPDATE alembic_version SET version_num='3a7fe1bab681' WHERE alembic_version.version_num = 'a5cc19f885bb';

-- Running upgrade 3a7fe1bab681 -> d4e8a1c7b952

ALTER TABLE vehiculos ADD COLUMN latitud NUMERIC(9, 6);

ALTER TABLE vehiculos ADD COLUMN longitud NUMERIC(9, 6);

ALTER TABLE vehiculos ADD COLUMN codigo_pais VARCHAR(2);

ALTER TABLE vehiculos ADD COLUMN ubicacion_id UUID;

ALTER TABLE vehiculos ADD COLUMN ubicacion_nombre VARCHAR(150);

ALTER TABLE vehiculos ADD COLUMN ubicacion_actualizada_en TIMESTAMP WITH TIME ZONE;

ALTER TABLE vehiculos ADD COLUMN ubicacion_fuente VARCHAR(20);

ALTER TABLE vehiculos ADD COLUMN ubicacion_confiable BOOLEAN DEFAULT false NOT NULL;

ALTER TABLE vehiculos ADD COLUMN peso_reservado_kg NUMERIC(12, 2) DEFAULT 0 NOT NULL;

ALTER TABLE vehiculos ADD COLUMN volumen_reservado_m3 NUMERIC(12, 2) DEFAULT 0 NOT NULL;

ALTER TABLE reservas_flota ADD COLUMN peso_kg NUMERIC(12, 2);

ALTER TABLE reservas_flota ADD COLUMN volumen_m3 NUMERIC(12, 2);

ALTER TABLE reservas_flota ADD COLUMN tipo_carga VARCHAR(20);

ALTER TABLE reservas_flota ADD COLUMN es_hazmat BOOLEAN DEFAULT false NOT NULL;

ALTER TABLE reservas_flota ADD COLUMN modo VARCHAR(12) DEFAULT 'exclusiva' NOT NULL;

ALTER TABLE reservas_flota ADD COLUMN distancia_origen_km NUMERIC(10, 2);

ALTER TABLE reservas_flota ADD COLUMN decision JSONB;

UPDATE reservas_flota r
           SET peso_kg = v.capacidad_kg, volumen_m3 = v.capacidad_m3
          FROM vehiculos v
         WHERE r.vehiculo_id = v.id AND r.estado = 'reservada' AND r.peso_kg IS NULL;

UPDATE vehiculos v
           SET peso_reservado_kg = v.capacidad_kg, volumen_reservado_m3 = COALESCE(v.capacidad_m3, 0)
         WHERE EXISTS (SELECT 1 FROM reservas_flota r WHERE r.vehiculo_id = v.id AND r.estado = 'reservada');

ALTER TABLE vehiculos ADD CONSTRAINT ck_vehiculos_peso_reservado CHECK (peso_reservado_kg >= 0 AND peso_reservado_kg <= capacidad_kg);

ALTER TABLE vehiculos ADD CONSTRAINT ck_vehiculos_volumen_reservado CHECK (volumen_reservado_m3 >= 0 AND (capacidad_m3 IS NULL OR volumen_reservado_m3 <= capacidad_m3));

DROP INDEX uq_reserva_activa_por_vehiculo;

CREATE UNIQUE INDEX uq_reserva_exclusiva_por_vehiculo ON reservas_flota (vehiculo_id) WHERE estado = 'reservada' AND modo = 'exclusiva';

CREATE INDEX ix_reservas_vehiculo_estado ON reservas_flota (vehiculo_id, estado);

UPDATE alembic_version SET version_num='d4e8a1c7b952' WHERE alembic_version.version_num = '3a7fe1bab681';

COMMIT;

