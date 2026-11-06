"""Rutas centralizadas del proyecto, sin efectos al importar."""
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
LOG_DIR = PROJECT_ROOT / "logs"
LOG_PATH = LOG_DIR / "subtes-ba-application.log"

DATA_DIR = PROJECT_ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
INTERIM_DIR = DATA_DIR / "interim"
PROCESSED_DIR = DATA_DIR / "processed"

DB_DIR = PROJECT_ROOT / "db"
DATABASE_PATH = DB_DIR / "subtes-ba-database.duckdb"
SCHEMA_PATH = PROJECT_ROOT / "src" / "database" / "schema.sql"

CRONOGRAMA_PATH = RAW_DIR / "cronograma.csv"
CALENDARIO_PATH = RAW_DIR / "calendario.csv"
COMUNAS_ZONAS_PATH = RAW_DIR / "comunas_zonas.csv"
COMUNAS_PATH = RAW_DIR / "comunas_caba.csv"
ESTACIONES_PATH = RAW_DIR / "estaciones_de_subte_caba.csv"
CATEGORIAS_ESTACION_PATH = RAW_DIR / "categorias_estacion.csv"
ESTACIONES_EQUIVALENCIAS_PATH = RAW_DIR / "estaciones_equivalencias.csv"

DIM_FECHA_PARQUET_PATH = PROCESSED_DIR / "calendario.parquet"
DIM_HORA_PARQUET_PATH = PROCESSED_DIR / "cronograma.parquet"
DIM_ESTACION_PARQUET_PATH = PROCESSED_DIR / "estaciones.parquet"


HISTORICOS = [
    {
        "anio": anio,
        "ruta": RAW_DIR / f"historico_{anio}.csv",
        "separador": ";" if anio == 2021 else ",",
        "encoding": "windows-1252" if anio in (2016, 2017) else "utf8",
        "formato_fecha": formato_fecha,
        "normalizar_fecha_cronologica": anio in (2020, 2021),
        "destino": PROCESSED_DIR / f"historico_{anio}.parquet",
        "rechazados": INTERIM_DIR / f"historico_{anio}_rechazados.parquet",
    }
    for anio, formato_fecha in [
        (2014, "%Y-%m-%d"),
        (2015, "%Y-%m-%d"),
        (2016, "%d/%m/%Y"),
        (2017, "%d/%m/%Y"),
        (2018, "%Y-%m-%d"),
        (2019, "%Y-%m-%d"),
        (2020, "%d/%m/%Y"),
        (2021, "%d/%m/%Y"),
    ]
]

# Sistemas de coordenadas declarados para interpretar los WKT de las fuentes.
CRS_ESTACIONES = "EPSG:4326"
CRS_COMUNAS = "EPSG:4326"

def resolve_path(path: str | Path) -> Path:
    """Interpreta rutas relativas respecto de la raiz del proyecto."""
    path = Path(path).expanduser()
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path.resolve()
