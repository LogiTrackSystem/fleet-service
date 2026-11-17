-- Datos de ejemplo de fleet_db: 3 vehículos (uno por tipo) y su conductor fijo.
-- Aplicar DESPUÉS de esquema.sql. Los códigos de conductor los asigna la secuencia de la base.
BEGIN;

INSERT INTO vehiculos (id, placa, tipo, capacidad_kg, capacidad_m3, anio, estado, capacidad_refrigeracion, certificado_hazmat,
                       latitud, longitud, codigo_pais, ubicacion_nombre, ubicacion_actualizada_en, ubicacion_fuente, ubicacion_confiable)
VALUES
 ('11111111-aaaa-4aaa-8aaa-000000000001', 'DEM001', 'furgoneta',    1000.00, 8.00,  2022, 'active', false, false,
  8.748000, -75.881400, 'CO', 'Montería', now(), 'registro_gestor', true),
 ('11111111-aaaa-4aaa-8aaa-000000000002', 'DEM002', 'camion',       5000.00, 30.00, 2021, 'active', false, false,
  6.244200, -75.581200, 'CO', 'Medellín', now(), 'registro_gestor', true),
 ('11111111-aaaa-4aaa-8aaa-000000000003', 'DEM003', 'tractocamion', 20000.00, 60.00, 2020, 'active', true, true,
  4.711000, -74.072100, 'CO', 'Bogotá', now(), 'registro_gestor', true);

INSERT INTO conductores (id, nombre, licencia_numero, categorias_licencia, certificacion_hazmat, anios_experiencia, vehiculo_id, estado)
VALUES
 ('22222222-bbbb-4bbb-8bbb-000000000001', 'Ana Pérez (ejemplo)',     'LIC-DEMO-001', 'B1,C1', false, 3, '11111111-aaaa-4aaa-8aaa-000000000001', 'available'),
 ('22222222-bbbb-4bbb-8bbb-000000000002', 'Luis Gómez (ejemplo)',    'LIC-DEMO-002', 'C2',    false, 5, '11111111-aaaa-4aaa-8aaa-000000000002', 'available'),
 ('22222222-bbbb-4bbb-8bbb-000000000003', 'Marta Rojas (ejemplo)',   'LIC-DEMO-003', 'C3',    true,  8, '11111111-aaaa-4aaa-8aaa-000000000003', 'available');

COMMIT;
