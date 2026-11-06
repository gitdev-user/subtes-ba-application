import logging
from pathlib import Path

import polars as pl

from src.config.config import CRONOGRAMA_PATH, DIM_HORA_PARQUET_PATH
from src.etl.extract import CSVExtractor
from src.etl.load import ParquetLoader
from src.etl.transform import Transformer


logger = logging.getLogger(__name__)


class CronogramaPipeline:
    def __init__(self):
        self.extractor = CSVExtractor(CRONOGRAMA_PATH)
        self.transformer = Transformer()
        self.parquet_loader = ParquetLoader(DIM_HORA_PARQUET_PATH)

    def prepare(self) -> Path:
        """Limpia, valida y guarda los 96 intervalos horarios."""
        data = self.extractor.extract()

        columns = [
            "hora_desde",
            "hora_hasta",
            "hora",
            "minuto",
        ]

        if not set(columns).issubset(data.collect_schema().names()):
            raise ValueError("Faltan columnas requeridas en el cronograma.")
        # Proyectar los campos vigentes permite leer también el CSV anterior.
        data = data.select(columns)

        rules = {
            column: [
                self.transformer.strip,
                self.transformer.normalize_spaces,
                self.transformer.empty_to_null,
            ]
            for column in columns
        }

        data = self.transformer.transform(data, rules).collect()
        data = data.unique()

        if data.is_empty() or any(data.null_count().row(0)):
            raise ValueError("El cronograma está vacío o tiene campos vacíos.")

        time_columns = [
            "hora_desde", "hora_hasta",
        ]

        data = data.with_columns(
            pl.col(time_columns).str.strptime(
                pl.Time, format="%H:%M:%S", strict=True
            ),
            pl.col("hora", "minuto").cast(pl.Int16),
        )

        # Polars representa Time como nanosegundos desde medianoche.
        minuto_ns = 60 * 1_000_000_000
        dia_ns = 1440 * minuto_ns
        intervalo_ns = 15 * minuto_ns

        inicios = data["hora_desde"].cast(pl.Int64).to_list()

        if (
            data.height != 96
            or set(inicios) != set(range(0, dia_ns, intervalo_ns))
        ):
            raise ValueError("Se esperan 96 intervalos, uno cada 15 minutos.")

        desde_ns = pl.col("hora_desde").cast(pl.Int64)
        minutos = desde_ns // minuto_ns

        expected = {
            "hora_hasta": (desde_ns + intervalo_ns) % dia_ns,
            "hora": minutos // 60,
            "minuto": minutos % 60,
        }

        for column, expression in expected.items():
            incorrectos = pl.col(column).cast(pl.Int64) != expression

            if data.select(incorrectos.any()).item():
                raise ValueError(
                    f"{column} no coincide con el intervalo horario."
                )

        # IDs estables: 00:00 = 1, 00:15 = 2, ..., 23:45 = 96.
        data = (
            data.with_columns(
                (minutos // 15 + 1).cast(pl.Int32).alias("id")
            )
            .select(["id", *columns])
            .sort("id")
        )

        ruta = self.parquet_loader.load(data)
        logger.info(
            "Cronograma guardado | registros=%s | archivo=%s | carpeta=%s",
            data.height,
            ruta.name,
            ruta.parent,
        )
        return ruta

    def run(self) -> Path:
        """Genera el Parquet de la dimensión sin cargar la base de datos."""
        return self.prepare()
