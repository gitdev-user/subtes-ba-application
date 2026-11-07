"""Perfiles de ingresos por categoría, estación y fecha."""

from functools import lru_cache
import logging

import duckdb
import plotly.graph_objects as go
from dash import Input, Output

from src.dashboard.queries import CATEGORIAS, DIAS_RANKING

logger = logging.getLogger(__name__)
COLORES_CATEGORIA = ("#27ad79", "#efac24", "#247aff", "#9753de")



def consultar_picos(repository, anio, dias, intervalo=15, categoria="todas"):
    """Agrega cada estación/día y conserva como nulos los bloques incompletos."""
    if anio != "todos" and (type(anio) is not int or not 2014 <= anio <= 2021):
        raise ValueError("Seleccioná Todos o un año entre 2014 y 2021.")
    if dias not in DIAS_RANKING:
        raise ValueError("El tipo de día no es válido.")
    if type(intervalo) is not int or intervalo not in (15, 30, 60):
        raise ValueError("Seleccioná un intervalo de 15, 30 o 60 minutos.")
    if categoria not in ("todas", *CATEGORIAS):
        raise ValueError("La categoría seleccionada no es válida.")
    condicion = {
        "todos": "TRUE",
        "semana": "NOT f.es_fin_semana AND NOT f.es_feriado",
        "descanso": "f.es_fin_semana OR f.es_feriado",
    }[dias]
    condiciones = ["f.anio BETWEEN 2014 AND 2021", f"({condicion})", "e.categoria_estacion IS NOT NULL"]
    params = []
    if anio != "todos":
        condiciones.append("f.anio = ?")
        params.append(anio)
    if categoria != "todas":
        condiciones.append("e.categoria_estacion = ?")
        params.append(categoria)
    factor = intervalo // 15
    # A 15 minutos la clave primaria ya identifica una observación estación/día.
    # Evitar reagrupar millones de filas que ya tienen la granularidad pedida.
    bloques = (
        "SELECT fecha, estacion_id, grupo, cuarto AS intervalo, cantidad FROM datos"
        if factor == 1 else f"""
            SELECT fecha, estacion_id, grupo, cuarto // {factor} AS intervalo,
                   CASE WHEN COUNT(*) = {factor} AND COUNT(cantidad) = {factor}
                        THEN SUM(cantidad) END AS cantidad
            FROM datos GROUP BY fecha, estacion_id, grupo, cuarto // {factor}
        """
    )
    base = f"""
        WITH datos AS (
            SELECT f.fecha, e.id AS estacion_id, e.categoria_estacion AS grupo,
                   t.hora * 4 + t.minuto // 15 AS cuarto, h.pax_total AS cantidad
            FROM dw.tabla_fact_historico_subtes h
            JOIN dw.tabla_dim_fecha f ON f.id = h.fecha_id
            JOIN dw.tabla_dim_hora t ON t.id = h.hora_id
            JOIN dw.tabla_dim_estacion e ON e.id = h.id_estacion
            WHERE {' AND '.join(condiciones)}
        ), bloques AS (
            {bloques}
        )
    """
    perfil = repository.query(base + """
        SELECT grupo, intervalo, AVG(cantidad) AS promedio, COUNT(cantidad) AS observaciones
        FROM bloques GROUP BY grupo, intervalo ORDER BY intervalo
    """, params)
    return perfil


def figura_picos(perfil, intervalo):
    from src.dashboard.callbacks import estilizar, figura_vacia

    curva = go.Figure()
    eje = range(1440 // intervalo)
    etiquetas = [f"{i * intervalo // 60:02d}:{i * intervalo % 60:02d}" for i in eje]
    for categoria, color in zip(CATEGORIAS, COLORES_CATEGORIA):
        datos = perfil.loc[perfil["grupo"] == categoria]
        if datos.empty or not (datos["promedio"] > 0).any():
            continue
        datos = datos.set_index("intervalo").reindex(eje)
        curva.add_scatter(
            x=[i * intervalo / 60 for i in eje], y=datos["promedio"] / datos["promedio"].max() * 100,
            mode="lines", name=categoria.capitalize(), connectgaps=False,
            line={"color": color, "width": 2},
            customdata=list(zip(etiquetas, datos["promedio"], datos["observaciones"])),
            hovertemplate=("%{customdata[0]}<br>Índice: %{y:.1f}"
                           "<br>Ingresos medios por estación/día: %{customdata[1]:,.1f}"
                           "<br>Observaciones conocidas: %{customdata[2]:,.0f}<extra>%{fullData.name}</extra>"),
        )
    if not curva.data:
        return figura_vacia()
    estilizar(curva)
    for inicio, fin, texto, color in (
        (6, 10, "Matutina · 06–10", "#247aff"),
        (16, 20, "Vespertina · 16–20", "#edb43c"),
    ):
        curva.add_vrect(x0=inicio, x1=fin, fillcolor=color, opacity=0.1, line_width=0, layer="below")
        curva.add_annotation(x=(inicio + fin) / 2, y=1.08, yref="paper", text=texto, showarrow=False)
    curva.update_xaxes(title="Hora del día", range=[0, 24], tickvals=list(range(0, 25, 2)),
                       ticktext=[f"{hora:02d}:00" for hora in range(0, 25, 2)])
    curva.update_yaxes(title="Índice (máximo de cada curva = 100)", range=[0, 110])
    curva.update_layout(margin={"t": 40, "b": 100})
    return curva


def registrar_picos(app, repository):
    from src.dashboard.callbacks import figura_vacia

    @lru_cache(maxsize=32)
    def consultar(anio, dias, intervalo):
        return consultar_picos(repository, anio, dias, intervalo)

    @app.callback(
        Output("grafico-02", "figure"), Output("mensaje-02", "children"),
        Input("picos-anio", "value"), Input("picos-dias", "value"),
        Input("picos-intervalo", "value"), Input("picos-categoria", "value"),
    )
    def actualizar(anio, dias, intervalo, categoria):
        try:
            if categoria not in ("todas", *CATEGORIAS):
                raise ValueError("La categoría seleccionada no es válida.")
            perfil = consultar(anio, dias, intervalo)
            if categoria != "todas":
                perfil = perfil.loc[perfil["grupo"] == categoria]
            return figura_picos(perfil, intervalo), ""
        except ValueError as error:
            return figura_vacia(), str(error)
        except duckdb.Error:
            logger.exception("No se pudieron consultar los picos")
            return figura_vacia(), "No se pudo consultar la base. Reiniciá el dashboard para reintentar."
