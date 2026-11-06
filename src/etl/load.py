# src/etl/load.py

from collections.abc import Iterable
from pathlib import Path

import polars as pl

from src.config.config import resolve_path
from src.repositories.generic_repository import GenericRepository


class ParquetLoader:
    def __init__(self, ruta: str | Path):
        self.ruta = resolve_path(ruta)

    def load(self, data: pl.DataFrame | pl.LazyFrame) -> Path:
        self.ruta.parent.mkdir(parents=True, exist_ok=True)

        if isinstance(data, pl.LazyFrame):
            data.sink_parquet(self.ruta, compression="zstd")
        else:
            data.write_parquet(self.ruta, compression="zstd")

        return self.ruta


class DBLoader:
    def __init__(self, repository: GenericRepository):
        self.repository = repository

    def load(
        self,
        data: pl.DataFrame,
        table: str,
        schema: str = "dw",
    ) -> int:
        return self.repository.save(
            data.to_pandas(),
            table=table,
            schema=schema,
        )

    def load_historico(self, lotes: Iterable[pl.DataFrame], anio: int) -> int:
        """Consume los lotes de un año en una única transacción del repositorio."""
        return self.repository.save_historico_batches(lotes=lotes, anio=anio)

    def load_parquet(
        self,
        ruta: str | Path,
        table: str,
        schema: str = "dw",
    ) -> int:
        ruta = resolve_path(ruta)

        if not ruta.is_file():
            raise FileNotFoundError(ruta)

        return self.repository.save_parquet(
            ruta,
            table=table,
            schema=schema,
        )
