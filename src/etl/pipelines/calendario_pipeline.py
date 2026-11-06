import logging
from pathlib import Path

import polars as pl

from src.config.config import CALENDARIO_PATH, DIM_FECHA_PARQUET_PATH, RAW_DIR
from src.etl.extract import CSVExtractor
from src.etl.load import ParquetLoader
from src.etl.transform import Transformer


logger = logging.getLogger(__name__)


class CalendarioPipeline:
    def __init__(self):
        self.extractor = CSVExtractor(CALENDARIO_PATH)
        self.feriados_extractor = CSVExtractor(
            RAW_DIR / "calendario_feriados_2014_2021.csv"
        )
        self.transformer = Transformer()
        self.parquet_loader = ParquetLoader(DIM_FECHA_PARQUET_PATH)

    def prepare(self) -> Path:
        """Limpia, valida y guarda la dimensión en Parquet."""
        data = self.extractor.extract()

        columns = [
            "fecha", "anio", "trimestre", "mes",
            "dia", "dia_semana", "es_fin_semana",
        ]

        if set(data.collect_schema().names()) != set(columns):
            raise ValueError("El calendario tiene columnas inesperadas.")

        rules = {
            column: [
                self.transformer.strip,
                self.transformer.empty_to_null,
            ]
            for column in columns
        }

        # Esta dimensión es pequeña; puede materializarse en memoria.
        data = self.transformer.transform(data, rules).collect()
        data = data.unique()

        if data.is_empty() or any(data.null_count().row(0)):
            raise ValueError("El calendario está vacío o tiene campos vacíos.")

        numeric_columns = [
            "anio", "trimestre", "mes", "dia", "dia_semana",
        ]

        data = data.with_columns(
            pl.col("fecha").str.strptime(
                pl.Date, format="%Y-%m-%d", strict=True
            ),
            pl.col(numeric_columns).cast(pl.Int16),
            pl.col("es_fin_semana")
            .str.to_lowercase()
            .replace_strict(
                {"true": True, "false": False},
                return_dtype=pl.Boolean,
            ),
        )

        if data["fecha"].is_duplicated().any():
            raise ValueError("Existen registros contradictorios para una fecha.")

        fecha = pl.col("fecha")

        expected = {
            "anio": fecha.dt.year(),
            "trimestre": fecha.dt.quarter(),
            "mes": fecha.dt.month(),
            "dia": fecha.dt.day(),
            "dia_semana": fecha.dt.weekday(),
            "es_fin_semana": fecha.dt.weekday() >= 6,
        }

        for column, expression in expected.items():
            if data.select((pl.col(column) != expression).any()).item():
                raise ValueError(f"{column} no coincide con la fecha.")

        feriados = (
            self.feriados_extractor.extract()
            .select(
                pl.col("fecha")
                .str.strip_chars()
                .str.strptime(pl.Date, format="%Y-%m-%d", strict=True)
            )
            .unique()
            .with_columns(pl.lit(True).alias("es_feriado"))
            .collect()
        )

        data = (
            data.join(feriados, on="fecha", how="left", validate="m:1")
            .with_columns(pl.col("es_feriado").fill_null(False))
            .sort("fecha")
            .with_row_index("id", offset=1)
            .with_columns(pl.col("id").cast(pl.Int32))
            .select(["id", *columns, "es_feriado"])
        )

        ruta = self.parquet_loader.load(data)
        logger.info(
            "Calendario guardado | registros=%s | archivo=%s | carpeta=%s",
            data.height,
            ruta.name,
            ruta.parent,
        )
        return ruta

    def run(self) -> Path:
        """Genera el Parquet de la dimensión sin cargar la base de datos."""
        return self.prepare()
