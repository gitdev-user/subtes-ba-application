import logging

from src.config.config import (
    DIM_FECHA_PARQUET_PATH,
    DIM_HORA_PARQUET_PATH,
    DIM_ESTACION_PARQUET_PATH,
    HISTORICOS,
)
from src.etl.extract import ParquetExtractor
from src.etl.load import DBLoader


logger = logging.getLogger(__name__)


class DWPipeline:
    def __init__(
        self,
        loader: DBLoader,
        batch_size: int = 250_000,
    ):
        if batch_size <= 0:
            raise ValueError("El tamaño del lote debe ser positivo.")

        self.loader = loader
        self.batch_size = batch_size

    def _cargar_dimensiones(self) -> None:
        dimensiones = [
            (DIM_FECHA_PARQUET_PATH, "tabla_dim_fecha"),
            (DIM_HORA_PARQUET_PATH, "tabla_dim_hora"),
            (DIM_ESTACION_PARQUET_PATH, "tabla_dim_estacion"),
        ]

        for ruta, tabla in dimensiones:
            logger.info("Iniciando carga de dimensión | tabla=%s", tabla)

            extractor = ParquetExtractor(ruta)
            data = extractor.extract()

            if tabla == "tabla_dim_hora":
                # Compatible con Parquet anteriores que contienen columnas adicionales.
                data = data.select("id", "hora_desde", "hora_hasta", "hora", "minuto")
            elif tabla == "tabla_dim_estacion":
                data = data.select(
                    "id",
                    "nombre_estacion",
                    "categoria_estacion",
                    "linea_subte",
                    "comuna",
                    "barrios_comuna",
                    "zona",
                    "geometria_estacion_wkt",
                )

            cantidad = self.loader.load(
                data=data.collect(),
                table=tabla,
            )

            logger.info(
                "Dimensión cargada | tabla=%s | registros=%s",
                tabla,
                cantidad,
            )

    def _cargar_historicos(self) -> None:
        for fuente in HISTORICOS:
            anio = fuente["anio"]

            logger.info("Iniciando carga de histórico | año=%s", anio)

            extractor = ParquetExtractor(fuente["destino"])
            lotes = extractor.extract_batches(
                batch_size=self.batch_size,
            )

            cantidad = self.loader.load_historico(
                lotes=lotes,
                anio=anio,
            )

            logger.info(
                "Histórico cargado | año=%s | hechos_agrupados=%s",
                anio,
                cantidad,
            )

    def run(self, *, cargar_dimensiones: bool = True) -> None:
        """Requiere que las tablas de DuckDB estén creadas."""
        if cargar_dimensiones:
            self._cargar_dimensiones()

        self._cargar_historicos()
