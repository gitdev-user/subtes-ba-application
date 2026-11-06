# src/jobs/job_scheduler.py

import logging
from datetime import datetime
from time import perf_counter

from src.config.config import (
    COMUNAS_ZONAS_PATH,
    COMUNAS_PATH,
    ESTACIONES_PATH,
    CATEGORIAS_ESTACION_PATH,
    ESTACIONES_EQUIVALENCIAS_PATH,
    CRS_ESTACIONES,
    CRS_COMUNAS,
    HISTORICOS,
)
from src.etl.extract import CSVExtractor
from src.database import ConexionDB, ContextManager
from src.repositories.generic_repository import GenericRepository
from src.etl.load import DBLoader
from src.etl.pipelines.dw_pipeline import DWPipeline
from src.etl.pipelines.calendario_pipeline import CalendarioPipeline
from src.etl.pipelines.cronograma_pipeline import CronogramaPipeline
from src.etl.pipelines.estacion_pipeline import EstacionPipeline
from src.etl.pipelines.historico_pipeline import HistoricoPipeline

logger = logging.getLogger(__name__)

class JobScheduler:
    """Coordina el procesamiento a Parquet y la carga del DW en DuckDB."""

    OPCIONES = {
        1: "Ejecutar todo el proceso de ETL",
        2: "Solo procesar archivos",
        3: "Solo cargar los archivos procesados a la base de datos",
    }

    def _pipelines_procesamiento(self) -> list:
        extractores_estaciones = [
            CSVExtractor(COMUNAS_ZONAS_PATH),
            CSVExtractor(COMUNAS_PATH, separador=";"),
            CSVExtractor(ESTACIONES_PATH),
            CSVExtractor(CATEGORIAS_ESTACION_PATH),
            CSVExtractor(ESTACIONES_EQUIVALENCIAS_PATH),
        ]

        return [
            CalendarioPipeline(),
            CronogramaPipeline(),
            EstacionPipeline(
                extractores=extractores_estaciones,
                crs_estaciones=CRS_ESTACIONES,
                crs_comunas=CRS_COMUNAS,
            ),
            HistoricoPipeline(historicos=HISTORICOS, batch_size=500_000),
        ]

    def _ejecutar_pipeline(self, pipeline) -> None:
        nombre = type(pipeline).__name__
        logger.info("Iniciando %s", nombre)
        pipeline.run()
        logger.info("Finalizado %s", nombre)

    def _procesar(self) -> None:
        for pipeline in self._pipelines_procesamiento():
            self._ejecutar_pipeline(pipeline)

    def _cargar(self) -> None:
        repository = GenericRepository(ContextManager(ConexionDB()))
        logger.info("Eliminando y recreando las tablas de DuckDB")
        repository.drop_tables()
        repository.create_tables()
        self._ejecutar_pipeline(
            DWPipeline(loader=DBLoader(repository), batch_size=250_000)
        )

    def run(self, opcion: int = 1) -> None:
        if opcion not in self.OPCIONES:
            raise ValueError(
                "Opción inválida. Usar 1: procesar y cargar todo, "
                "2: solo procesar, o 3: solo cargar."
            )

        inicio = datetime.now().astimezone()
        inicio_contador = perf_counter()
        estado = "INCOMPLETO"

        logger.info(
            "Inicio del proceso | opcion=%s | descripcion=%s | inicio=%s",
            opcion,
            self.OPCIONES[opcion],
            inicio.isoformat(timespec="seconds"),
        )

        try:
            if opcion in (1, 2):
                self._procesar()

            if opcion in (1, 3):
                self._cargar()

            estado = "COMPLETADO"

        except Exception:
            logger.exception("Falló el proceso | opcion=%s", opcion)
            raise

        finally:
            fin = datetime.now().astimezone()
            duracion = perf_counter() - inicio_contador

            logger.info(
                "Fin del proceso | opcion=%s | estado=%s | "
                "inicio=%s | fin=%s | duracion_segundos=%.2f",
                opcion,
                estado,
                inicio.isoformat(timespec="seconds"),
                fin.isoformat(timespec="seconds"),
                duracion,
            )
