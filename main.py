# main.py

import argparse
import logging
from src.config.config import LOG_PATH
from src.jobs.job_scheduler import JobScheduler


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Procesamiento, carga y dashboard histórico de Subtes BA."
    )
    parser.add_argument(
        "--opcion",
        type=int,
        choices=[1, 2, 3, 4],
        default=1,
        help=(
            "1: Ejecutar todo el proceso de ETL (predeterminado); "
            "2: Solo procesar archivos; "
            "3: Solo cargar los archivos procesados a la base de datos; "
            "4: Inicial Dashboard. "
            "Las opciones 1 y 3 eliminan y recrean las tablas de DuckDB."
        ),
    )
    args = parser.parse_args()

    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        handlers=[
            logging.FileHandler(LOG_PATH, encoding="utf-8"),
            logging.StreamHandler(),
        ],
    )

    if args.opcion == 4:
        from src.dashboard.app import iniciar_dashboard

        iniciar_dashboard()
    else:
        JobScheduler().run(opcion=args.opcion)


if __name__ == "__main__":
    main()
