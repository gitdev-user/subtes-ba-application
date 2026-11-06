"""Aplicación Dash local: python main.py --opcion 4."""

import logging
from pathlib import Path

import duckdb
from dash import Dash, html

from src.database import ConexionDB, ContextManager
from src.repositories.generic_repository import GenericRepository
from src.dashboard.callbacks import registrar_callbacks
from src.dashboard.layout import crear_layout
from src.dashboard.queries import obtener_catalogos


def crear_app(repository=None) -> Dash:
    """Consulta el DW en modo de solo lectura y registra los controles."""
    repository = repository if repository is not None else GenericRepository(
        ContextManager(ConexionDB(read_only=True))
    )
    app = Dash(
        __name__, title="Subtes BA · Afluencia histórica",
        assets_folder=str(Path(__file__).parent / "assets"),
        update_title="Consultando afluencia…",
    )
    try:
        catalogos = obtener_catalogos(repository)
    except (duckdb.Error, ValueError):
        logging.getLogger(__name__).exception("No se pudo abrir el dashboard")
        app.layout = html.Main([
            html.P("SUBTES BA", className="brand-name"),
            html.H1("La base de datos no está disponible."),
            html.P("Comprobá que la carga haya terminado y cerrá conexiones de escritura, "
                   "por ejemplo DBeaver. Luego reiniciá el dashboard."),
            html.P(["Para cargar los Parquet existentes: ", html.Code("python main.py --opcion 3")]),
        ], className="startup-message")
        return app
    app.layout = crear_layout(catalogos)
    registrar_callbacks(app, repository, catalogos)
    return app


def iniciar_dashboard():
    """Inicia solamente el servidor, sin ejecutar el ETL ni recrear tablas."""
    crear_app().run(debug=False, host="127.0.0.1", port=8050)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    iniciar_dashboard()
