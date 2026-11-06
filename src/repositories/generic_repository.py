from collections.abc import Iterable
from pathlib import Path

import duckdb
import pandas as pd
import polars as pl

from src.config.config import SCHEMA_PATH, resolve_path
from src.database import ContextManager


class GenericRepository:

    SCHEMA_PATH = SCHEMA_PATH

    def __init__(self, context_manager: ContextManager):
        self.context_manager = context_manager

    def save(
        self,
        data: pd.DataFrame,
        table: str,
        schema: str = "dw",
    ) -> int:
        if data.empty:
            return 0

        # Escapar identificadores SQL.
        schema = schema.replace('"', '""')
        table = table.replace('"', '""')

        with self.context_manager.transaction() as conn:
            conn.register("datos", data)

            conn.execute(
                f"""
                INSERT INTO "{schema}"."{table}" BY NAME
                SELECT * FROM datos
                """
            )

        return len(data)

    def save_parquet(
        self,
        ruta: str | Path,
        table: str,
        schema: str = "dw",
        columns: list[str] | None = None,
    ) -> int:
        """Inserta un Parquet por nombre; los conflictos revierten toda la carga.

        Permite seleccionar columnas para excluir atributos ajenos a la tabla.
        No actualiza ni omite claves existentes al recargar dimensiones.
        """
        ruta = resolve_path(ruta)
        if not ruta.is_file():
            raise FileNotFoundError(ruta)
        if columns is not None and not columns:
            raise ValueError("Debe seleccionarse al menos una columna.")

        schema = schema.replace('"', '""')
        table = table.replace('"', '""')
        seleccion = "*" if columns is None else ", ".join(
            '"' + column.replace('"', '""') + '"' for column in columns
        )

        with self.context_manager.transaction() as conn:
            cantidad = conn.execute(
                f'INSERT INTO "{schema}"."{table}" BY NAME '
                f"SELECT {seleccion} FROM read_parquet(?)",
                [str(ruta)],
            ).fetchone()[0]

        return cantidad

    def save_historico_parquet(self, ruta: str | Path, anio: int) -> int:
        """Agrupa y reemplaza los hechos de un año en una única transacción.

        Requiere dimensiones cargadas con los mismos IDs que los Parquet.
        Rechaza archivos vacíos y fechas sin dimensión o ajenas al año pedido.
        Devuelve la cantidad de hechos agrupados insertados.
        """
        ruta = resolve_path(ruta)
        if not ruta.is_file():
            raise FileNotFoundError(ruta)

        with self.context_manager.transaction() as conn:
            conn.execute(
                """
                CREATE TEMP TABLE historico_temporal AS
                SELECT fecha_id, hora_id, id_estacion,
                       pax_pago, pax_pases_pagos, pax_franq, pax_total
                FROM read_parquet(?)
                """,
                [str(ruta)],
            ).fetchall()

            cantidad = self._insertar_historico_temporal(conn, anio)

        return cantidad

    def save_historico_batches(
        self, lotes: Iterable[pl.DataFrame], anio: int
    ) -> int:
        """Carga todos los lotes en una temporal y luego agrupa el año completo.

        La lectura, la carga temporal y el reemplazo comparten transacción.
        Un error al consumir el iterador también revierte toda la operación.
        """
        columnas = [
            "fecha_id", "hora_id", "id_estacion",
            "pax_pago", "pax_pases_pagos", "pax_franq", "pax_total",
        ]
        with self.context_manager.transaction() as conn:
            conn.execute(
                """
                CREATE TEMP TABLE historico_temporal (
                    fecha_id INTEGER,
                    hora_id INTEGER,
                    id_estacion INTEGER,
                    pax_pago BIGINT,
                    pax_pases_pagos BIGINT,
                    pax_franq BIGINT,
                    pax_total BIGINT
                )
                """
            ).fetchall()
            for lote in lotes:
                if lote.is_empty():
                    continue
                conn.register("lote_historico", lote.select(columnas).to_arrow())
                try:
                    # Consumir el resultado antes de liberar el origen Arrow.
                    conn.execute(
                        "INSERT INTO historico_temporal BY NAME "
                        "SELECT * FROM lote_historico"
                    ).fetchall()
                finally:
                    conn.unregister("lote_historico")

            cantidad = self._insertar_historico_temporal(conn, anio)

        return cantidad

    def _insertar_historico_temporal(
        self, conn: duckdb.DuckDBPyConnection, anio: int
    ) -> int:
        """Valida y agrupa usando la conexión de la transacción llamadora."""
        cantidad_temporal = conn.execute(
            "SELECT COUNT(*) FROM historico_temporal"
        ).fetchall()[0][0]
        if cantidad_temporal == 0:
            raise ValueError("El histórico está vacío; no se reemplazó el año.")

        fechas_invalidas = conn.execute(
            """
            SELECT COUNT(*)
            FROM historico_temporal AS h
            LEFT JOIN dw.tabla_dim_fecha AS f ON f.id = h.fecha_id
            WHERE f.id IS NULL OR f.anio IS DISTINCT FROM ?
            """,
            [anio],
        ).fetchall()[0][0]
        if fechas_invalidas:
            raise ValueError(
                f"Hay {fechas_invalidas} registros con fechas sin dimensión "
                f"o ajenas al año {anio}."
            )

        conn.execute(
            """
            DELETE FROM dw.tabla_fact_historico_subtes
            WHERE fecha_id IN (
                SELECT id FROM dw.tabla_dim_fecha WHERE anio = ?
            )
            """,
            [anio],
        ).fetchall()
        return conn.execute(
            """
            INSERT INTO dw.tabla_fact_historico_subtes BY NAME
            SELECT fecha_id, hora_id, id_estacion,
                   SUM(pax_pago) AS pax_pago,
                   SUM(pax_pases_pagos) AS pax_pases_pagos,
                   SUM(pax_franq) AS pax_franq,
                   SUM(pax_total) AS pax_total
            FROM historico_temporal
            GROUP BY fecha_id, hora_id, id_estacion
            """
        ).fetchall()[0][0]

    def query(self, sql: str, params: list | None = None) -> pd.DataFrame:
        """Ejecuta SQL parametrizado y materializa el resultado antes de cerrar."""
        with self.context_manager.transaction() as conn:
            return conn.execute(sql, params if params is not None else []).df()

    def read(self, table: str, schema: str = "dw") -> pd.DataFrame:
        schema = schema.replace('"', '""')
        table = table.replace('"', '""')

        with self.context_manager.transaction() as conn:
            return conn.execute(
                f'SELECT * FROM "{schema}"."{table}"'
            ).df()

    def create_tables(self) -> None:
        """Ejecuta el esquema para crear las tablas faltantes."""
        schema_sql = self.SCHEMA_PATH.read_text(encoding="utf-8-sig")

        if not schema_sql.strip():
            raise ValueError("El archivo schema.sql esta vacio.")

        with self.context_manager.transaction() as conn:
            conn.execute(schema_sql)

    def drop_tables(self) -> None:

        statements = (
            "DROP TABLE IF EXISTS dw.tabla_fact_historico_subtes",
            "DROP TABLE IF EXISTS dw.tabla_dim_estacion",
            "DROP TABLE IF EXISTS dw.tabla_dim_fecha",
            "DROP TABLE IF EXISTS dw.tabla_dim_hora",
            "DROP SEQUENCE IF EXISTS dw.seq_dim_estacion",
        )

        with self.context_manager.transaction() as conn:
            for statement in statements:
                conn.execute(statement)
