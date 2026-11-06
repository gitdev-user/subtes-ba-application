import logging
from contextlib import ExitStack
from datetime import date, datetime
from pathlib import Path

import polars as pl
import pyarrow.parquet as pq

from src.config.config import (
    DIM_FECHA_PARQUET_PATH,
    DIM_HORA_PARQUET_PATH,
    DIM_ESTACION_PARQUET_PATH,
    resolve_path,
)
from src.etl.extract import CSVExtractor, ParquetExtractor
from src.etl.transform import Transformer


logger = logging.getLogger(__name__)

CANTIDADES = [
    "PAX_PAGO", "PAX_PASES_PAGOS", "PAX_FRANQ", "PAX_TOTAL",
]


class HistoricoPipeline:
    """Normaliza los históricos por año y guarda procesados y rechazados en Parquet."""

    def __init__(self, historicos: list[dict], batch_size: int = 250_000):
        if batch_size <= 0:
            raise ValueError("El tamaño del lote debe ser positivo.")

        self.historicos = list(historicos)
        self.batch_size = batch_size
        self.transformer = Transformer()

    def _normalizar_clave_estacion(self, data):
        """Aplica la misma limpieza a las claves de ambos lados del join."""
        data = data.with_columns(
            pl.col("_estacion_clave").replace({
                "SAENZ PE<D1>A": "SAENZ PEÑA",
            })
        )

        return self.transformer.transform(data, {
            "_estacion_clave": [
                self.transformer.uppercase,
                self.transformer.remove_accents,
                self.transformer.remove_symbols,
                self.transformer.normalize_spaces,
                self.transformer.strip,
                self.transformer.empty_to_null,
            ],
        })

    def _cargar_dimensiones(self):
        fechas = ParquetExtractor(DIM_FECHA_PARQUET_PATH).extract().select(
            pl.col("id").alias("fecha_id"),
            pl.col("fecha").cast(pl.Date).alias("FECHA"),
        ).collect()

        horas = ParquetExtractor(DIM_HORA_PARQUET_PATH).extract().select(
            pl.col("id").alias("hora_id"),
            pl.col("hora_desde").cast(pl.Time).alias("DESDE"),
            pl.col("hora_hasta").cast(pl.Time).alias("_fin"),
        ).collect()

        estaciones = ParquetExtractor(
            DIM_ESTACION_PARQUET_PATH
        ).extract().select(
            pl.col("id").alias("id_estacion"),
            pl.col("linea_subte")
            .str.strip_chars().str.to_uppercase()
            .str.replace(r"^LINEA[\s_]*", "").alias("LINEA"),
            pl.col("nombre_estacion_equivalencia").alias("_estacion_clave"),
        ).collect()
        estaciones = self._normalizar_clave_estacion(estaciones)

        return fechas, horas, estaciones

    @staticmethod
    def _candidatos_fecha(valor: str | None, anio: int) -> list[date]:
        """Devuelve interpretaciones válidas, sin elegir por orden de formato."""
        if valor is None:
            return []

        valor = valor.strip()
        formatos = (
            ("%d/%m/%Y", "%m/%d/%Y")
            if "/" in valor else ("%Y-%m-%d", "%Y-%d-%m")
        )
        candidatos = set()
        for formato in formatos:
            try:
                fecha = datetime.strptime(valor, formato).date()
            except ValueError:
                continue
            if fecha.year == anio:
                candidatos.add(fecha)
        return sorted(candidatos)

    def _resolver_fechas_cronologicas(
        self, extractor: CSVExtractor, *, anio: int
    ) -> pl.DataFrame:
        """Primera pasada: resuelve bloques cronológicos dentro de cada línea.

        Solo materializa cambios de FECHA y sus posiciones. Los valores sin
        interpretación o con varias soluciones quedan nulos. Si no existe una
        secuencia no decreciente, falla antes de abrir los archivos de salida.
        Los CSV alternan grupos de líneas que repiten las fechas de cada mes.
        """
        lectura = extractor.extract()
        columna = next(
            column for column in lectura.collect_schema().names()
            if column.strip().upper() == "FECHA"
        )
        bloques_por_linea = {}
        offset = 0
        anteriores = {}
        for lote in lectura.select(
            pl.col(columna).alias("FECHA"),
            self._clave_linea_fecha(lectura.collect_schema().names()),
        ).collect_batches(
            chunk_size=self.batch_size
        ):
            if lote.is_empty():
                continue
            for grupo in lote.with_row_index("_fila", offset=offset).partition_by(
                "_linea_fecha", maintain_order=True
            ):
                linea = grupo["_linea_fecha"][0]
                cambios = grupo.filter(
                    (pl.col("_fila") == grupo["_fila"][0])
                    | pl.col("FECHA").ne_missing(pl.col("FECHA").shift(1))
                ).select("_fila", "FECHA").rows()
                if linea in anteriores and cambios[0][1] == anteriores[linea]:
                    cambios = cambios[1:]
                bloques_por_linea.setdefault(linea, []).extend(cambios)
                anteriores[linea] = grupo["FECHA"][-1]
            offset += lote.height

        filas = []
        lineas = []
        fechas = []
        for linea, bloques in bloques_por_linea.items():
            resueltas = self._resolver_bloques_fecha(bloques, anio=anio, linea=linea)
            filas.extend(fila for fila, _ in bloques)
            lineas.extend([linea] * len(bloques))
            fechas.extend(resueltas)

        logger.info(
            "Fechas cronológicas | año=%s | bloques=%s | resueltos=%s | sin_resolver=%s",
            anio, len(filas), sum(fecha is not None for fecha in fechas),
            sum(fecha is None for fecha in fechas),
        )
        return pl.DataFrame({
            "_fila": pl.Series(filas, dtype=pl.UInt64),
            "_linea_fecha": pl.Series(lineas, dtype=pl.String),
            "_FECHA_NORMALIZADA": pl.Series(fechas, dtype=pl.Date),
        }).sort("_fila")

    @staticmethod
    def _clave_linea_fecha(columnas: list[str]) -> pl.Expr:
        columna = next(
            (column for column in columnas if column.strip().upper() == "LINEA"),
            None,
        )
        if columna is None:
            return pl.lit("").alias("_linea_fecha")
        return (
            pl.col(columna).str.strip_chars().str.to_uppercase()
            .str.replace(r"^LINEA[\s_]*", "").fill_null("")
            .alias("_linea_fecha")
        )

    def _resolver_bloques_fecha(self, bloques, *, anio: int, linea: str):
        """Propaga las alternativas hacia delante y atrás, sin inventar fechas."""
        candidatos = [self._candidatos_fecha(valor, anio) for _, valor in bloques]
        validos = [i for i, opciones in enumerate(candidatos) if opciones]

        # Fechas alcanzables desde el inicio. No se exige continuidad diaria.
        anteriores = None
        alcanzables = {}
        for i in validos:
            opciones = candidatos[i]
            if anteriores is not None:
                opciones = [fecha for fecha in opciones if fecha >= min(anteriores)]
            if not opciones:
                raise ValueError(
                    f"Histórico {anio}: orden cronológico incompatible "
                    f"en la línea {linea!r}, fila {bloques[i][0] + 1}: "
                    f"{bloques[i][1]!r}."
                )
            alcanzables[i] = opciones
            anteriores = opciones

        # Restringir también desde el final evita una elección voraz ambigua.
        resueltas = [None] * len(bloques)
        siguientes = None
        for i in reversed(validos):
            opciones = alcanzables[i]
            if siguientes is not None:
                opciones = [fecha for fecha in opciones if fecha <= max(siguientes)]
            if len(opciones) == 1:
                resueltas[i] = opciones[0]
            siguientes = opciones

        return resueltas

    def _agregar_fechas_resueltas(
        self, lote: pl.DataFrame, resoluciones: pl.DataFrame, offset: int
    ) -> pl.DataFrame:
        """Asigna por posición: un mismo texto puede tener distintos contextos."""
        return (
            lote.with_row_index("_fila", offset=offset)
            .with_columns(
                pl.col("_fila").cast(pl.UInt64),
                self._clave_linea_fecha(lote.columns),
            )
            .set_sorted("_fila")
            .join_asof(
                resoluciones, on="_fila", by="_linea_fecha", strategy="backward",
                # Ambas entradas están ordenadas por posición global.
                check_sortedness=False,
            )
            .drop("_fila", "_linea_fecha")
        )

    def _limpiar(self, data, formato_fecha: str, *, fecha_normalizada: bool = False):
        data = data.rename({
            column: column.strip().upper()
            for column in data.columns
        })

        renombres = {
            "PAX_PAGOS": "PAX_PAGO",
            "PAX_FREQ": "PAX_FRANQ",
            "TOTAL": "PAX_TOTAL",
        }
        data = data.rename({
            origen: destino
            for origen, destino in renombres.items()
            if origen in data.columns
        })

        columns = [
            "FECHA", "DESDE", "HASTA", "LINEA", "ESTACION", "MOLINETE",
            *CANTIDADES,
        ]
        missing = set(columns) - set(data.columns)
        if missing:
            raise ValueError(f"Faltan columnas en el histórico: {sorted(missing)}")

        # PERIODO, V1 e ID_ESTACION no intervienen en la asociación ni deduplicación.
        seleccion = columns + (["_FECHA_NORMALIZADA"] if fecha_normalizada else [])
        data = data.select(seleccion)

        data = self.transformer.transform(data, {
            column: [self.transformer.strip, self.transformer.empty_to_null]
            for column in columns
        }).filter(
            ~pl.all_horizontal(pl.all().is_null())
        ).unique(maintain_order=True)

        data = self.transformer.transform(data, {
            column: [self.transformer.normalize_spaces, self.transformer.uppercase]
            for column in columns
        }).with_columns(
            pl.col(columns).replace(["NA", "N/A", "NULL"], None)
        ).filter(
            ~pl.all_horizontal(pl.all().is_null())
        )

        # Reparar variantes conocidas antes de quitar símbolos de la clave.
        correcciones = {
            "SAENZ PE\u00a4A": "SAENZ PEÑA",
            "SAENZ PE\u00b1A": "SAENZ PEÑA",
            "SAENZ PE\u00c3\u0083\u00c2\u00b1A": "SAENZ PEÑA",
            "SAENZ PE\u00c3\u00b1A": "SAENZ PEÑA",
            "SAENZ PE\ufffdA": "SAENZ PEÑA",
            "SAENZ PE<D1>A": "SAENZ PEÑA",
            "AG\u0081ERO": "AGÜERO",
            "AG\u00b3ERO": "AGÜERO",
            "AG\u00c3\u0083\u00c2\u00bcERO": "AGÜERO",
            "AG\u00c3\u00bcERO": "AGÜERO",
            "AG\ufffdERO": "AGÜERO",
        }
        data = data.with_columns(pl.col("ESTACION").replace(correcciones))

        # Aceptar enteros como '7.0' sin redondear cantidades fraccionarias.
        # Hacerlo antes de detectar valores que no pueden convertirse a enteros.
        data = data.with_columns(pl.col(CANTIDADES).str.replace(r"\.0+$", ""))

        # Conservar el texto original para identificar los rechazados.
        data = data.with_columns(
            pl.concat_str("FECHA", "DESDE", separator=" ").alias("_desde_original"),
            pl.concat_str("FECHA", "HASTA", separator=" ").alias("_hasta_original"),
            pl.col("ESTACION").alias("_estacion_clave"),
            pl.any_horizontal([
                pl.col(column).is_not_null()
                & pl.col(column).cast(pl.Int64, strict=False).is_null()
                for column in CANTIDADES
            ]).alias("_cantidad_invalida"),
        )
        data = self._normalizar_clave_estacion(data)

        fecha_expr = (
            pl.col("_FECHA_NORMALIZADA")
            if fecha_normalizada
            else pl.col("FECHA").str.strptime(pl.Date, formato_fecha, strict=False)
        )
        data = data.with_columns(
            fecha_expr.alias("FECHA"),
            pl.col("DESDE", "HASTA").str.strptime(
                pl.Time, "%H:%M:%S", strict=False
            ),
            pl.col("LINEA").str.replace(r"^LINEA[\s_]*", ""),
            pl.col(CANTIDADES).cast(pl.Int64, strict=False),
        )
        if fecha_normalizada:
            data = data.drop("_FECHA_NORMALIZADA")
        return data.unique(maintain_order=True)

    def _resolver_estaciones(
        self,
        data: pl.DataFrame,
        estaciones: pl.DataFrame,
    ) -> pl.DataFrame:
        """Resuelve nombres exactos o contenidos, siempre dentro de la línea."""
        claves = ["LINEA", "_estacion_clave"]

        nombres = (
            data.select(claves)
            .unique()
            .filter(pl.col("_estacion_clave").is_not_null())
        )

        dimension = (
            estaciones.select(*claves, "id_estacion")
            .filter(
                pl.col("_estacion_clave").is_not_null()
                & (pl.col("_estacion_clave") != "")
            )
            .unique()
        )

        # Mantener las coincidencias exactas existentes.
        exactos = nombres.join(
            dimension,
            on=claves,
            how="inner",
            validate="m:1",
        )

        pendientes = nombres.join(
            exactos.select(claves),
            on=claves,
            how="anti",
        )

        patrones = (
            dimension.rename({
                "LINEA": "_linea_dimension",
                "_estacion_clave": "_equivalencia",
            })
            .with_columns(
                pl.col("_equivalencia")
                .str.escape_regex()
                .alias("_patron")
            )
        )

        # Cruzar solo los nombres pendientes, no todas las filas del histórico.
        candidatos = (
            pendientes.join(patrones, how="cross")
            .filter(
                (pl.col("LINEA") == pl.col("_linea_dimension"))
                & pl.col("_estacion_clave").str.contains(pl.col("_patron"))
            )
            .select(*claves, "id_estacion")
            .unique()
        )

        # Los nombres ambiguos quedan sin ID para rechazarlos después.
        aproximados = (
            candidatos.group_by(claves)
            .agg(
                pl.col("id_estacion").n_unique().alias("_coincidencias"),
                pl.col("id_estacion").first(),
            )
            .filter(pl.col("_coincidencias") == 1)
            .select(*claves, "id_estacion")
        )

        mapa = pl.concat([
            exactos.select(*claves, "id_estacion"),
            aproximados,
        ])

        return data.join(mapa, on=claves, how="left", validate="m:1")

    def _asociar(self, data, fechas, horas, estaciones, *, anio: int):
        data = self._resolver_estaciones(data, estaciones)

        data = (
            data.join(fechas, on="FECHA", how="left", validate="m:1")
            .join(horas, on="DESDE", how="left", validate="m:1")
        )

        # Validar el final exacto o el formato histórico un minuto anterior.
        minuto_ns = 60 * 1_000_000_000
        diferencia = (
            pl.col("_fin").cast(pl.Int64)
            - pl.col("HASTA").cast(pl.Int64)
        ) % (1440 * minuto_ns)

        valido = (
            pl.all_horizontal(
                pl.col("fecha_id", "hora_id", "id_estacion").is_not_null()
            )
            & (pl.col("FECHA").dt.year() == anio)
            & diferencia.is_in([0, minuto_ns])
            & pl.col("MOLINETE").is_not_null()
            & ~pl.col("_cantidad_invalida")
            & ~pl.any_horizontal(
                pl.col(CANTIDADES) < 0
            ).fill_null(False)
        ).fill_null(False)

        rechazados = data.filter(~valido).select(
            pl.col("_desde_original").alias("fecha_hora_desde"),
            pl.col("_hasta_original").alias("fecha_hora_hasta"),
            pl.col("LINEA").alias("linea"),
            pl.col("ESTACION").alias("estacion"),
        )

        hechos = data.filter(valido).select(
            "fecha_id",
            "hora_id",
            "id_estacion",
            pl.col("FECHA").dt.combine(
                pl.col("DESDE")
            ).alias("fecha_hora_desde"),
            (
                pl.col("FECHA").dt.combine(pl.col("_fin"))
                + pl.duration(
                    days=(pl.col("_fin") <= pl.col("DESDE")).cast(pl.Int32)
                )
            ).alias("fecha_hora_hasta"),
            pl.col("MOLINETE").alias("molinete"),
            *[
                pl.col(column).alias(column.lower())
                for column in CANTIDADES
            ],
        ).unique(maintain_order=True)

        return hechos, rechazados

    def _procesar_archivo(self, fuente: dict, dimensiones) -> Path:
        anio = fuente["anio"]
        extractor = CSVExtractor(
            fuente["ruta"],
            separador=fuente["separador"],
            encoding=fuente.get("encoding", "utf8"),
        )
        destino = resolve_path(fuente["destino"])
        rechazos_path = resolve_path(fuente["rechazados"])

        logger.info("Iniciando histórico | año=%s | archivo=%s", anio, extractor.ruta)

        normalizar = anio in (2020, 2021) and fuente.get(
            "normalizar_fecha_cronologica", False
        )
        resoluciones = (
            self._resolver_fechas_cronologicas(extractor, anio=anio)
            if normalizar else None
        )
        offset = 0
        writer = writer_rechazos = None
        total = total_rechazados = 0

        with ExitStack() as stack:
            for numero, lote in enumerate(
                extractor.extract_batches(self.batch_size), start=1
            ):
                if normalizar:
                    lote = self._agregar_fechas_resueltas(lote, resoluciones, offset)
                offset += lote.height
                limpio = self._limpiar(
                    lote, fuente["formato_fecha"], fecha_normalizada=normalizar
                )
                hechos, rechazados = self._asociar(limpio, *dimensiones, anio=anio)

                tabla = hechos.to_arrow()
                tabla_rechazos = rechazados.to_arrow()

                if writer is None:
                    writer = stack.enter_context(
                        pq.ParquetWriter(
                            destino, tabla.schema, compression="zstd"
                        )
                    )
                    writer_rechazos = stack.enter_context(
                        pq.ParquetWriter(
                            rechazos_path,
                            tabla_rechazos.schema,
                            compression="zstd",
                        )
                    )

                writer.write_table(tabla)
                writer_rechazos.write_table(tabla_rechazos)

                total += hechos.height
                total_rechazados += rechazados.height

                logger.info(
                    "Año=%s | lote=%s | leídos=%s | guardados=%s | rechazados=%s",
                    anio, numero, lote.height, hechos.height, rechazados.height,
                )

        if writer is None:
            raise ValueError(f"El histórico {anio} no contiene lotes para procesar.")

        logger.info(
            "Histórico guardado | año=%s | registros=%s | archivo=%s",
            anio, total, destino,
        )
        logger.info(
            "Rechazados guardados | año=%s | registros=%s | archivo=%s",
            anio, total_rechazados, rechazos_path,
        )

        return destino

    def prepare(self) -> list[Path]:
        dimensiones = self._cargar_dimensiones()
        return [
            self._procesar_archivo(fuente, dimensiones)
            for fuente in self.historicos
        ]

    def run(self) -> list[Path]:
        return self.prepare()
