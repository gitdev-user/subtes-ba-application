import logging
from pathlib import Path

import polars as pl
from pyproj import Transformer as CRSTransformer
from shapely import STRtree, from_wkt, to_wkt
from shapely.ops import transform as transform_geometry

from src.config.config import DIM_ESTACION_PARQUET_PATH
from src.etl.extract import CSVExtractor
from src.etl.load import ParquetLoader
from src.etl.transform import Transformer


logger = logging.getLogger(__name__)


class EstacionPipeline:
    def __init__(
        self,
        extractores: list[CSVExtractor],
        *,
        crs_estaciones: str,
        crs_comunas: str,
    ):
        if len(extractores) != 5:
            raise ValueError(
                "Se requieren extractores de zonas, comunas, "
                "estaciones, categorías y equivalencias, en ese orden."
            )

        self.extractores = dict(zip(
            ["zonas", "comunas", "estaciones", "categorias", "equivalencias"],
            extractores,
        ))

        self.transformer = Transformer()
        self.parquet_loader = ParquetLoader(DIM_ESTACION_PARQUET_PATH)
        self.crs_estaciones = crs_estaciones
        self.crs_comunas = crs_comunas

    def _read(self, fuente: str, columns: list[str]) -> pl.DataFrame:
        data = self.extractores[fuente].extract().select(columns)

        conservar_simbolos = {"categorias", "barrios"}
        rules = {}

        for column in columns:
            if column == "geometry":
                continue

            operations = [
                self.transformer.uppercase,
                self.transformer.remove_accents,
            ]

            if column not in conservar_simbolos:
                operations.append(self.transformer.remove_symbols)

            operations.extend([
                self.transformer.normalize_spaces,
                self.transformer.strip,
                self.transformer.empty_to_null,
            ])

            rules[column] = operations

        data = self.transformer.transform(data, rules).collect().unique()

        if data.is_empty() or any(data.null_count().row(0)):
            raise ValueError(f"{fuente}: hay datos vacíos.")

        return data

    @staticmethod
    def _validate_key(data: pl.DataFrame, column: str) -> None:
        values = data[column]

        if (
            values.is_null().any()
            or values.is_duplicated().any()
            or (values <= 0).any()
        ):
            raise ValueError(f"Clave inválida o duplicada: {column}")

    @staticmethod
    def _geometries(data, crs, tipos):
        geometries = from_wkt(data["geometry"].to_list())

        transformer = CRSTransformer.from_crs(
            crs, "EPSG:4326", always_xy=True
        )

        result = []

        for geometry in geometries:
            if (
                geometry is None
                or geometry.is_empty
                or not geometry.is_valid
                or geometry.geom_type not in tipos
            ):
                raise ValueError("Geometría vacía, inválida o de tipo incorrecto.")

            geometry = transform_geometry(
                transformer.transform, geometry
            )

            if geometry.is_empty or not geometry.is_valid:
                raise ValueError("Geometría inválida después de reproyectar.")

            result.append(geometry)

        return result

    def _asignar_comunas(self, estaciones, comunas):
        puntos = self._geometries(
            estaciones, self.crs_estaciones, {"Point"}
        )
        poligonos = self._geometries(
            comunas, self.crs_comunas, {"Polygon", "MultiPolygon"}
        )

        indice = STRtree(poligonos)
        comunas_ids = comunas["comuna"].to_list()
        asignaciones = []

        for estacion_id, punto in zip(estaciones["id"], puntos):
            coincidencias = indice.query(punto, predicate="intersects")

            if len(coincidencias) != 1:
                raise ValueError(
                    f"Estación {estacion_id}: se esperaba una comuna, "
                    f"se encontraron {len(coincidencias)}."
                )

            asignaciones.append(comunas_ids[int(coincidencias[0])])

        return estaciones.with_columns(
            pl.Series("comuna", asignaciones, dtype=pl.Int16),
            pl.Series(
                "geometria_estacion_wkt",
                to_wkt(puntos, rounding_precision=-1),
                dtype=pl.String,
            ),
        )

    def prepare(self) -> Path:
        # 1. Normalizar zonas y comunas y unir por número de comuna.
        zonas = self._read("zonas", ["comuna", "zona"]).with_columns(
            pl.col("comuna").cast(pl.Int16)
        )

        comunas = self._read(
            "comunas", ["comuna", "barrios", "geometry"]
        ).with_columns(
            pl.col("comuna").cast(pl.Int16)
        )

        self._validate_key(zonas, "comuna")
        self._validate_key(comunas, "comuna")

        if set(zonas["comuna"]) != set(comunas["comuna"]):
            raise ValueError("Los catálogos de comunas no coinciden.")

        comunas = zonas.join(
            comunas, on="comuna", how="left", validate="1:1"
        ).rename({"barrios": "barrios_comuna"})

        # 2. Normalizar estaciones conservando su ID original.
        estaciones = self._read(
            "estaciones", ["id", "estacion", "linea", "geometry"]
        ).with_columns(
            pl.col("id").cast(pl.Int32),
            pl.col("linea").str.replace(r"^LINEA[\s_]*", ""),
        )

        self._validate_key(estaciones, "id")

        if not estaciones["linea"].is_in(
            ["A", "B", "C", "D", "E", "H"]
        ).all():
            raise ValueError("Hay líneas desconocidas.")

        estaciones = estaciones.with_columns(
            (pl.lit("LINEA ") + pl.col("linea")).alias("linea_subte")
        ).rename({"estacion": "nombre_estacion"})

        # 3. Asociar estaciones y comunas mediante las coordenadas.
        estaciones = self._asignar_comunas(estaciones, comunas)

        final = estaciones.join(
            comunas.select(
                "comuna", "barrios_comuna", "zona"
            ),
            on="comuna",
            how="left",
            validate="m:1",
        )

        # 4. Incorporar categorías por ID.
        categorias = self._read(
            "categorias", ["id", "categorias"]
        ).with_columns(
            pl.col("id").cast(pl.Int32)
        ).rename({
            "categorias": "categoria_estacion",
        })

        self._validate_key(categorias, "id")

        final = final.join(
            categorias, on="id", how="left", validate="1:1"
        )

        # 5. Incorporar el nombre equivalente validando el ID y la línea.
        equivalencias = self._read(
            "equivalencias", ["id", "linea", "equivalencia"]
        ).with_columns(
            pl.col("id").cast(pl.Int32),
            pl.col("linea").str.replace(r"^LINEA[\s_]*", ""),
        ).rename({
            "equivalencia": "nombre_estacion_equivalencia",
        })

        self._validate_key(equivalencias, "id")

        if equivalencias.select(
            "linea", "nombre_estacion_equivalencia"
        ).is_duplicated().any():
            raise ValueError("Hay equivalencias ambiguas dentro de una misma línea.")

        final = final.join(
            equivalencias, on=["id", "linea"], how="left", validate="1:1"
        )

        # 6. Seleccionar los atributos del Parquet de estaciones.
        final = (
            final.with_columns(pl.col("comuna").cast(pl.String))
            .select(
                "id",
                "nombre_estacion",
                "nombre_estacion_equivalencia",
                "categoria_estacion",
                "linea_subte",
                "comuna",
                "barrios_comuna",
                "zona",
                "geometria_estacion_wkt",
            )
            .sort("id")
        )

        if any(final.null_count().row(0)):
            raise ValueError("Hay estaciones con atributos sin resolver.")

        ruta = self.parquet_loader.load(final)
        logger.info(
            "Estaciones guardadas | registros=%s | archivo=%s | carpeta=%s",
            final.height,
            ruta.name,
            ruta.parent,
        )
        return ruta

    def run(self) -> Path:
        """Genera el Parquet de la dimensión sin cargar la base de datos."""
        return self.prepare()
