CREATE SCHEMA IF NOT EXISTS dw;

CREATE TABLE IF NOT EXISTS dw.tabla_dim_hora (
    id            INTEGER PRIMARY KEY,
    hora_desde    TIME NOT NULL,
    hora_hasta    TIME NOT NULL,
    hora          SMALLINT NOT NULL,
    minuto        SMALLINT NOT NULL
);

CREATE TABLE IF NOT EXISTS dw.tabla_dim_fecha (
    id           INTEGER PRIMARY KEY,
    fecha         DATE NOT NULL UNIQUE,
    anio          SMALLINT NOT NULL,
    trimestre     SMALLINT NOT NULL,
    mes           SMALLINT NOT NULL,
    dia           SMALLINT NOT NULL,
    dia_semana    SMALLINT NOT NULL,
    es_fin_semana BOOLEAN NOT NULL,
    es_feriado    BOOLEAN NOT NULL
);

CREATE SEQUENCE IF NOT EXISTS dw.seq_dim_estacion START 1;

CREATE TABLE IF NOT EXISTS dw.tabla_dim_estacion (

    id                      INTEGER PRIMARY KEY,
    nombre_estacion         VARCHAR NOT NULL,
    categoria_estacion      VARCHAR,
    linea_subte             VARCHAR NOT NULL,
    comuna                  VARCHAR NOT NULL,
    barrios_comuna          VARCHAR NOT NULL,
    zona                    VARCHAR NOT NULL,
    geometria_estacion_wkt  VARCHAR NOT NULL
);

CREATE TABLE IF NOT EXISTS dw.tabla_fact_historico_subtes (
    fecha_id       INTEGER NOT NULL,
    hora_id        INTEGER NOT NULL,
    id_estacion    INTEGER NOT NULL,

    pax_pago        BIGINT,
    pax_pases_pagos BIGINT,
    pax_franq       BIGINT,
    pax_total       BIGINT,

    PRIMARY KEY (fecha_id, hora_id, id_estacion),

    FOREIGN KEY (fecha_id)
        REFERENCES dw.tabla_dim_fecha (id),

    FOREIGN KEY (hora_id)
        REFERENCES dw.tabla_dim_hora (id),

    FOREIGN KEY (id_estacion)
        REFERENCES dw.tabla_dim_estacion (id)
);
