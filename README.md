# Subtes BA — Análisis histórico de ingresos al subte de Buenos Aires

Aplicación para procesar y analizar los ingresos registrados en las estaciones del subte de Buenos Aires entre **2014 y 2021**.

El proyecto implementa un proceso **ETL** —extracción, transformación y carga— que lee archivos CSV, procesa los datos, genera archivos Parquet y los carga en una base de datos **DuckDB**.

Incluye un Dashboard desarrollado con **Dash y Plotly**, con indicadores globales y gráficos interactivos para explorar los ingresos por año, día, hora, línea, categoría de estación, zona, comuna y tipo de validación.

## 2. Estructura de directorios y archivos

```text
subtes-ba-application/
├── main.py                           # Punto de entrada del programa
├── requirements.txt                  # Dependencias de Python
├── README.md                         # Documentación del proyecto
│
├── data/
│   ├── raw/                          # Archivos CSV originales
│   ├── interim/                      # Registros rechazados durante el procesamiento
│   └── processed/                    # Archivos Parquet procesados
│
├── db/                               # Base de datos DuckDB del proyecto
├── logs/                             # Registros de ejecución y errores
├── preview/                          # Vistas HTML de referencia del Dashboard
│
└── src/
    ├── config/
    │   └── config.py                 # Rutas, archivos fuente y configuración
    │
    ├── database/
    │   ├── __init__.py
    │   ├── connection.py             # Conexiones y transacciones de DuckDB
    │   └── schema.sql                # Definición de las tablas del DW
    │
    ├── repositories/
    │   └── generic_repository.py     # Consultas y operaciones sobre la base
    │
    ├── etl/
    │   ├── extract.py                # Lectura de archivos CSV y Parquet
    │   ├── transform.py              # Funciones de transformación
    │   ├── load.py                   # Escritura de Parquet y carga en DuckDB
    │   └── pipelines/
    │       ├── __init__.py
    │       ├── calendario_pipeline.py
    │       ├── cronograma_pipeline.py
    │       ├── estacion_pipeline.py
    │       ├── historico_pipeline.py
    │       └── dw_pipeline.py        # Carga de dimensiones e históricos
    │
    ├── jobs/
    │   └── job_scheduler.py          # Coordinación de las etapas del ETL
    │
    └── dashboard/
        ├── __init__.py
        ├── app.py                    # Creación e inicio del Dashboard
        ├── layout.py                 # Indicadores, gráficos y controles
        ├── callbacks.py              # Interacciones y actualización de gráficos
        ├── queries.py                # Consultas y agregaciones
        └── assets/
            └── styles.css            # Estilos visuales
```

Las rutas y los nombres de los archivos utilizados por el programa se configuran en `src/config/config.py`.

## 3. Instalación y ejecución

### 3.1. Requisitos

- Python **3.10 o superior**.
- Los archivos CSV originales en `data/raw/`, con los nombres definidos en `src/config/config.py`.

Los siguientes comandos están preparados para **PowerShell en Windows** y deben ejecutarse desde la raíz del proyecto.

### 3.2. Preparar el entorno

Clonar o descargar el repositorio y acceder a su directorio:

```powershell
cd subtes-ba-application
```

Crear un entorno virtual:

```powershell
python -m venv .venv
```

Activar el entorno virtual:

```powershell
.\.venv\Scripts\Activate.ps1
```

Instalar las dependencias:

```powershell
python -m pip install -r requirements.txt
```

### 3.3. Consultar la ayuda

Para consultar las opciones disponibles:

```powershell
python main.py --help
```

También puede utilizarse:

```powershell
python main.py -h
```

### 3.4. Opciones de ejecución

#### Opción 1. Ejecutar todo el proceso de ETL

```powershell
python main.py --opcion 1
```

Ejecuta el procesamiento completo y la carga de la base de datos:

1. Lee los CSV originales de `data/raw/`.
2. Limpia, transforma y valida los datos de calendario, cronograma, estaciones e históricos.
3. Genera los archivos Parquet en `data/processed/` y guarda los registros rechazados de los históricos en `data/interim/`.
4. Elimina y recrea las tablas del Data Warehouse en DuckDB.
5. Carga las dimensiones y los históricos procesados. Los ingresos se agrupan por fecha, intervalo horario y estación.

Esta opción prepara la base para consultar el Dashboard. El Dashboard se inicia por separado mediante la opción 4.

Es la opción predeterminada. Ejecutar:

```powershell
python main.py
```

equivale a ejecutar:

```powershell
python main.py --opcion 1
```

#### Opción 2. Solo procesar archivos

```powershell
python main.py --opcion 2
```

Ejecuta únicamente la etapa de procesamiento:

- Lee los CSV originales.
- Limpia, transforma y valida los datos.
- Genera o reemplaza los archivos Parquet en `data/processed/`.
- Guarda los registros rechazados de los históricos en `data/interim/`.

La base de datos existente se conserva. Esta opción permite preparar los archivos antes de realizar su carga mediante la opción 3.

#### Opción 3. Solo cargar los archivos procesados a la base de datos

```powershell
python main.py --opcion 3
```

Carga los Parquet existentes en `data/processed/`, sin volver a procesar los CSV.

El procedimiento:

1. Elimina y recrea las tablas del Data Warehouse.
2. Carga las dimensiones de fecha, hora y estación.
3. Lee los históricos procesados por lotes.
4. Agrupa los ingresos por fecha, intervalo horario y estación y los carga en la tabla de hechos.

Requiere haber generado previamente todos los Parquet necesarios mediante la opción 1 o 2.

**Las opciones 1 y 3 reconstruyen las tablas y reemplazan los datos previamente cargados en ellas.**

#### Opción 4. Inicial Dashboard

```powershell
python main.py --opcion 4
```

Inicia el Dashboard utilizando la base de datos existente en `db/`.

Una vez iniciado, abrir en el navegador:

```text
http://127.0.0.1:8050
```

El Dashboard muestra los indicadores globales del período 2014–2021 y nueve gráficos con sus controles de selección.

Esta opción utiliza DuckDB en modo de solo lectura: no procesa archivos ni carga o recrea tablas. Requiere una base previamente cargada mediante la opción 1 o 3.

Para detener el servidor:

```text
Ctrl + C
```

### 3.5. Primera ejecución

Con los CSV disponibles en `data/raw/`, ejecutar el ETL completo:

```powershell
python main.py --opcion 1
```

Cuando finalice correctamente, iniciar el Dashboard:

```powershell
python main.py --opcion 4
```

Las ejecuciones registran su actividad en la consola y en los archivos de la carpeta `logs/`.
