"""Extracción de CSV y Parquet con Polars."""

from collections.abc import Iterator
import csv
from pathlib import Path

import polars as pl
import pyarrow as pa
import pyarrow.csv as pacsv
import pyarrow.dataset as pads

from src.config.config import resolve_path


class CSVExtractor:
    def __init__(
        self,
        ruta: str | Path,
        *,
        separador: str = ",",
        encoding: str = "utf8",
    ):
        self.ruta = resolve_path(ruta)
        self.separador = separador
        self.encoding = encoding

    def extract(self) -> pl.LazyFrame:
        """Prepara la lectura; las columnas se leen como texto."""
        if self.encoding not in ("utf8", "utf8-lossy"):
            return self._extract_encoded()

        return pl.scan_csv(
            self.ruta,
            separator=self.separador,
            encoding=self.encoding,
            infer_schema=False,
            try_parse_dates=False,
            ignore_errors=False,
        )

    def _extract_encoded(self) -> pl.LazyFrame:
        """Lee otras codificaciones por lotes sin cargar todo el CSV."""
        with self.ruta.open(encoding=self.encoding, newline="") as archivo:
            columnas = next(csv.reader(archivo, delimiter=self.separador))

        esquema = pa.schema([(columna, pa.string()) for columna in columnas])
        formato = pads.CsvFileFormat(
            read_options=pacsv.ReadOptions(encoding=self.encoding),
            parse_options=pacsv.ParseOptions(delimiter=self.separador),
            convert_options=pacsv.ConvertOptions(
                column_types=esquema,
                strings_can_be_null=False,
            ),
        )
        dataset = pads.dataset(str(self.ruta), format=formato, schema=esquema)
        return pl.scan_pyarrow_dataset(dataset)

    def extract_batches(
        self,
        batch_size: int = 250_000,
    ) -> Iterator[pl.DataFrame]:
        if batch_size <= 0:
            raise ValueError("El tamaño del lote debe ser mayor que cero.")

        yield from self.extract().collect_batches(chunk_size=batch_size)


class ParquetExtractor:
    def __init__(self, ruta: str | Path):
        self.ruta = resolve_path(ruta)

    def extract(self) -> pl.LazyFrame:
        """Prepara la lectura conservando los tipos del Parquet."""
        return pl.scan_parquet(self.ruta)

    def extract_batches(
        self,
        batch_size: int = 250_000,
    ) -> Iterator[pl.DataFrame]:
        if batch_size <= 0:
            raise ValueError("El tamaño del lote debe ser mayor que cero.")

        yield from self.extract().collect_batches(chunk_size=batch_size)
