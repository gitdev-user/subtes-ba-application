"""Conexiones y transacciones con DuckDB."""

from contextlib import contextmanager, suppress
from pathlib import Path
from typing import Generator

import duckdb

from src.config.config import DATABASE_PATH, resolve_path


class ConexionDB:
    """Configura el acceso sin mantener conexiones abiertas."""

    def __init__(self, ruta: str | Path = DATABASE_PATH, read_only: bool = False):
        self.ruta = ":memory:" if str(ruta) == ":memory:" else resolve_path(ruta)
        self.read_only = read_only

    def connect(self) -> duckdb.DuckDBPyConnection:
        """Abre una conexion nueva; el llamador administra su cierre."""
        if isinstance(self.ruta, Path) and not self.read_only:
            self.ruta.parent.mkdir(parents=True, exist_ok=True)
        return duckdb.connect(database=str(self.ruta), read_only=self.read_only)


class ContextManager:
    """Administra una conexion y una transaccion por bloque."""

    def __init__(self, conexion: ConexionDB):
        self.conexion = conexion

    @contextmanager
    def transaction(self) -> Generator[duckdb.DuckDBPyConnection, None, None]:
        """Confirma al salir correctamente, revierte errores y siempre cierra.

        Consumir los resultados dentro del bloque y dejar propagar los errores.
        No cerrar ni confirmar manualmente la conexion entregada.
        """
        conn = self.conexion.connect()
        try:
            conn.begin()
            try:
                yield conn
                conn.commit()
            except BaseException:
                # Conservar el error original si tambien falla el rollback.
                with suppress(duckdb.Error):
                    conn.rollback()
                raise
        finally:
            conn.close()
