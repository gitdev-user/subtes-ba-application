"""Presentación y filtros de los gráficos generales del dashboard."""

from dataclasses import replace
from functools import lru_cache
from threading import RLock
import logging

import duckdb
import pandas as pd
import plotly.graph_objects as go
from dash import Input, Output, html

from src.dashboard.queries import (
    CATEGORIAS, VALIDACIONES, DIAS_RANKING,
    Filtros, consultar_dashboard, consultar_evolucion, consultar_kpis, validar_filtros,
)


logger = logging.getLogger(__name__)
COLORES_CATEGORIA = {"INTERMEDIA": "#27ad79", "INTERCAMBIO": "#efac24",
                     "TRASBORDO FERROVIARIO": "#247aff", "CABECERA": "#9753de"}
COLORES_LINEA = {"LINEA A": "#21b9d2", "LINEA B": "#e64450", "LINEA C": "#287bf0",
                 "LINEA D": "#22ac68", "LINEA E": "#9255c7", "LINEA H": "#e9bd16"}
COLORES_VALIDACION = {"pax_pago": "#15365d", "pax_pases_pagos": "#39b6a8", "pax_franq": "#edbd37"}
ETIQUETAS_CATEGORIA = {"INTERMEDIA": "Intermedia", "INTERCAMBIO": "Intercambio",
                       "TRASBORDO FERROVIARIO": "Trasbordo ferroviario", "CABECERA": "Cabecera"}
MESES = ["Ene", "Feb", "Mar", "Abr", "May", "Jun", "Jul", "Ago", "Sep", "Oct", "Nov", "Dic"]


def numero(valor, decimales=0):
    if pd.isna(valor):
        return "Sin dato"
    return f"{valor:,.{decimales}f}".replace(",", "_").replace(".", ",").replace("_", ".")


def abreviar(valor):
    if pd.isna(valor):
        return "Sin dato"
    return numero(valor / 1_000_000, 1) + " M" if abs(valor) >= 1_000_000 else numero(valor)


def estilizar(figura):
    figura.update_layout(
        template="plotly_white", autosize=True, height=None, width=None,
        font={"family": "Arial, sans-serif", "color": "#132d50", "size": 11},
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", separators=",.",
        margin={"l": 60, "r": 32, "t": 18, "b": 85},
        legend={"orientation": "h", "x": 0, "y": -0.2, "yanchor": "top", "font": {"size": 10}},
    )
    figura.update_xaxes(showgrid=False, automargin=True, zeroline=False)
    figura.update_yaxes(gridcolor="#e7edf2", automargin=True, zeroline=False)
    return figura


def figura_vacia(texto="No hay registros para esta selección"):
    figura = go.Figure()
    figura.add_annotation(text=texto, x=0.5, y=0.5, xref="paper", yref="paper", showarrow=False)
    figura.update_xaxes(visible=False)
    figura.update_yaxes(visible=False)
    return estilizar(figura)


def _escala(valores):
    maximo = valores.abs().max()
    return (1_000_000, "Millones de ingresos") if pd.notna(maximo) and maximo >= 1_000_000 else (1, "Ingresos")


def _etiqueta(valor, nivel):
    if nivel == "categoria":
        return ETIQUETAS_CATEGORIA.get(valor, valor)
    if nivel == "comuna":
        return f"Comuna {valor}"
    if nivel == "linea":
        return valor.replace("LINEA ", "Línea ")
    return valor.title() if nivel == "zona" else valor


def barras_totales(datos, nivel, ranking=False, dias="todos"):
    data = datos.loc[datos["nivel"] == nivel].copy()
    if dias not in DIAS_RANKING:
        raise ValueError("El tipo de día del ranking no es válido.")
    if dias != "todos":
        data["total"] = data["total_" + dias]
    if ranking and nivel == "comuna":
        data = data.set_index("etiqueta").reindex([str(c) for c in range(1, 16)]).rename_axis("etiqueta").reset_index()
    if (data.empty or data["total"].notna().sum() == 0) and not (ranking and nivel == "comuna"):
        return figura_vacia()
    if ranking:
        data["orden"] = data["etiqueta"].astype(int) if nivel == "comuna" else data["etiqueta"]
        data = data.sort_values(["total", "orden"], ascending=[False, True], na_position="last")
        if nivel == "estacion":
            data = data.loc[data["total"].notna()].head(15)
    elif nivel == "categoria":
        data = data.set_index("etiqueta").reindex([c for c in CATEGORIAS if c in set(data["etiqueta"])]).reset_index()
    else:
        data = data.sort_values("etiqueta")
    escala, titulo = _escala(data["total"])
    colores = COLORES_LINEA if nivel == "linea" else COLORES_CATEGORIA if nivel == "categoria" else {}
    etiquetas = [
        f"{fila.etiqueta}<br>{ETIQUETAS_CATEGORIA.get(fila.categoria_estacion, fila.categoria_estacion)}"
        if nivel == "estacion" else _etiqueta(fila.etiqueta, nivel)
        for fila in data.itertuples()
    ]
    fig = go.Figure(go.Bar(
        x=data["total"] / escala, y=etiquetas, orientation="h",
        marker_color=[colores.get(v, "#193b65") for v in data["etiqueta"]],
        text=[abreviar(v) for v in data["total"]], textposition="outside", cliponaxis=False,
        customdata=data["total"], hovertemplate="%{y}<br>Ingresos: %{customdata:,.0f}<extra></extra>",
    ))
    fig = estilizar(fig)
    fig.update_xaxes(title=titulo, rangemode="tozero")
    fig.update_yaxes(autorange="reversed", showgrid=False)
    fig.update_layout(showlegend=False, margin={"l": 160 if nivel == "estacion" else 110, "r": 75, "b": 48})
    if ranking:
        fig.update_yaxes(categoryorder="array", categoryarray=etiquetas)
        for etiqueta in data.loc[data["total"].isna(), "etiqueta"]:
            fig.add_annotation(x=0, y=_etiqueta(etiqueta, nivel), text="Sin registros",
                               showarrow=False, xanchor="left", font={"color": "#65758a", "size": 11})
    return fig


def barras_validaciones(datos, nivel, seleccion=None):
    seleccion = tuple(VALIDACIONES) if seleccion is None else tuple(seleccion)
    if any(v not in VALIDACIONES for v in seleccion):
        raise ValueError("El tipo de validación seleccionado no es válido.")
    columnas = [v for v in VALIDACIONES if v in seleccion]
    if not columnas:
        return figura_vacia("Seleccioná al menos un tipo de validación o pase")
    data = datos.loc[datos["nivel"] == nivel].copy()
    data["total"] = data[columnas].sum(axis=1, min_count=1)
    if data.empty or not data["total"].notna().any():
        return figura_vacia()
    if nivel == "categoria":
        orden = [c for c in CATEGORIAS if c in set(data["etiqueta"])]
        data = data.set_index("etiqueta").reindex(orden).reset_index()
    else:
        data = data.sort_values("etiqueta")
    etiquetas = [_etiqueta(v, nivel) for v in data["etiqueta"]]
    escala, titulo = _escala(data["total"])
    fig = go.Figure()
    for columna in columnas:
        fig.add_bar(x=data[columna] / escala, y=etiquetas, orientation="h",
                    name=VALIDACIONES[columna], marker_color=COLORES_VALIDACION[columna],
                    customdata=data[columna],
                    hovertemplate="%{y}<br>%{fullData.name}: %{customdata:,.0f}<extra></extra>")
    fig = estilizar(fig)
    fig.update_layout(barmode="stack", showlegend=False, margin={"l": 110, "r": 110, "b": 50})
    fig.update_xaxes(title=titulo, rangemode="tozero")
    fig.update_yaxes(autorange="reversed", showgrid=False, categoryorder="array", categoryarray=etiquetas)
    for etiqueta, total in zip(etiquetas, data["total"]):
        fig.add_annotation(x=total / escala if pd.notna(total) else 0, y=etiqueta,
                           text=numero(total) if pd.notna(total) else "Sin registros",
                           showarrow=False, xanchor="left", xshift=8,
                           font={"color": "#132d50" if pd.notna(total) else "#65758a", "size": 11})
    return fig


def _limites(catalogos, filtros):
    anios = [filtros.anio] if filtros.anio is not None else catalogos["anios"]
    inicio, fin = pd.Timestamp(f"{min(anios)}-01-01"), pd.Timestamp(f"{max(anios)}-12-31")
    if filtros.fecha_desde:
        inicio = max(inicio, pd.Timestamp(filtros.fecha_desde))
    if filtros.fecha_hasta:
        fin = min(fin, pd.Timestamp(filtros.fecha_hasta))
    return inicio, fin


def temporal(datos, vista, catalogos, filtros, area=False):
    data = datos.loc[datos["nivel"] == vista].copy()
    if data.empty or not data["total"].notna().any():
        return figura_vacia()
    inicio, fin = _limites(catalogos, filtros)
    promedio = vista in ("semana", "estacional")
    if promedio:
        data["eje"] = data["eje"].astype(int)
        eje = range(1, 8) if vista == "semana" else range(1, 5)
    else:
        data["eje"] = pd.to_datetime(data["eje"])
        if vista == "diaria":
            eje = pd.date_range(inicio, fin, freq="D")
        elif vista == "semanal":
            eje = pd.date_range(inicio - pd.Timedelta(days=inicio.weekday()), fin, freq="W-MON")
        else:
            eje = pd.date_range(inicio.replace(day=1), fin, freq="MS")
    data = data.set_index("eje").reindex(eje)
    valores = data["promedio" if promedio else "total"]
    escala, titulo = _escala(valores)
    if promedio:
        titulo = "Millones de ingresos medios diarios" if escala > 1 else "Ingresos medios diarios"
    fig = go.Figure(go.Scatter(
        x=list(eje), y=valores / escala, mode="lines" if area else "lines+markers",
        line={"color": "#112d52", "width": 2}, marker={"size": 5}, connectgaps=False,
        fill="tozeroy" if area else None, fillcolor="rgba(61,153,230,0.15)",
        customdata=valores, hovertemplate="%{x}<br>Ingresos: %{customdata:,.0f}<extra></extra>",
    ))
    fig = estilizar(fig)
    fig.update_yaxes(title=titulo, rangemode="tozero")
    if vista == "semana":
        fig.update_xaxes(tickvals=list(eje), ticktext=["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"])
    elif vista == "estacional":
        fig.update_xaxes(tickvals=list(eje), ticktext=["Verano", "Otoño", "Invierno", "Primavera"])
    elif vista == "mensual":
        if inicio.year == fin.year:
            fig.update_xaxes(tickvals=list(eje), ticktext=[MESES[fecha.month - 1] for fecha in eje])
        else:
            anos = pd.date_range(inicio, fin, freq="YS")
            fig.update_xaxes(tickvals=anos, ticktext=[str(a.year) for a in anos])
    fig.update_layout(showlegend=False, margin={"b": 50})
    return fig


def mapa_calor(datos, categoria="todas"):
    if categoria not in ("todas", *CATEGORIAS):
        raise ValueError("La categoría del mapa de calor no es válida.")
    data = datos.loc[(datos["nivel"] == "mapa") & (datos["categoria"] == categoria)]
    if data.empty or not data["promedio"].notna().any():
        return figura_vacia("No hay datos para esta categoría")
    dias = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]
    matriz = data.pivot(index="dia_semana", columns="hora", values="promedio").reindex(
        index=range(1, 8), columns=range(24))
    fechas = data.pivot(index="dia_semana", columns="hora", values="dias_conocidos").reindex(
        index=range(1, 8), columns=range(24))
    fig = go.Figure(go.Heatmap(
        x=list(range(24)), y=dias, z=matriz.to_numpy(), customdata=fechas.to_numpy(),
        colorscale=[[0, "#eef5ff"], [0.5, "#247aff"], [1, "#102b50"]], zmin=0,
        xgap=1, ygap=1, hoverongaps=False,
        colorbar={"title": {"text": "Ingresos<br>medios"}, "tickformat": ",.0f", "thickness": 12},
        hovertemplate="%{y} · %{x}:00<br>Ingresos medios: %{z:,.1f}<br>Días con datos: %{customdata:,.0f}<extra></extra>",
    ))
    fig = estilizar(fig)
    fig.update_layout(plot_bgcolor="#e5e7eb", margin={"l": 92, "r": 75, "b": 60}, showlegend=False)
    ticks = list(range(0, 24, 3))
    fig.update_xaxes(title="Hora del día", tickvals=ticks, ticktext=[f"{h:02d}:00" for h in ticks],
                     range=[-0.5, 23.5], showgrid=False)
    fig.update_yaxes(title="Día de la semana", categoryorder="array", categoryarray=dias,
                     autorange="reversed", showgrid=False)
    return fig


def composicion(datos, validaciones=None):
    seleccion = tuple(VALIDACIONES) if validaciones is None else tuple(validaciones)
    if any(v not in VALIDACIONES for v in seleccion):
        raise ValueError("El tipo de validación seleccionado no es válido.")
    columnas = [v for v in VALIDACIONES if v in seleccion]
    if not columnas:
        return figura_vacia("Seleccioná al menos un tipo de validación o pase"), 420
    orden = ["NORTE", "OESTE", "CENTRO", "ESTE", "SUR"]
    data = datos.set_index("etiqueta").reindex(orden)
    valores = data[columnas]
    # La escala considera la suma apilada de los tipos seleccionados en cada zona.
    totales = valores.sum(axis=1, min_count=1)
    escala, titulo = _escala(totales)
    fig = go.Figure()
    etiquetas = [z.title() for z in orden]
    for columna in columnas:
        fig.add_bar(x=valores[columna] / escala, y=etiquetas, orientation="h",
                    name=VALIDACIONES[columna],
                    marker_color=COLORES_VALIDACION[columna], customdata=valores[columna],
                    hovertemplate="%{y}<br>%{fullData.name}: %{customdata:,.0f}<extra></extra>")
    fig = estilizar(fig)
    fig.update_layout(barmode="stack", showlegend=False, margin={"l": 100, "r": 110, "b": 50})
    fig.update_xaxes(title=titulo, rangemode="tozero")
    fig.update_yaxes(autorange="reversed", showgrid=False, categoryorder="array", categoryarray=etiquetas)
    for etiqueta, total in zip(etiquetas, totales):
        fig.add_annotation(x=total / escala if pd.notna(total) else 0, y=etiqueta,
                           text=numero(total) if pd.notna(total) else "Sin registros",
                           showarrow=False, xanchor="left", xshift=8,
                           font={"color": "#132d50" if pd.notna(total) else "#65758a", "size": 11})
    return fig, 420


def tarjetas_kpi(fila):
    total = fila["total"]
    dias = fila["dias_conocidos"]
    ferro = fila["total_ferroviario"]
    habiles = fila["total_habiles"]
    participacion_habil = habiles / total * 100 if pd.notna(habiles) and pd.notna(total) and total > 0 else None
    participacion = (0 if pd.isna(ferro) else ferro) / total * 100 if pd.notna(total) and total > 0 else None
    cards = [("Ingresos totales", abreviar(total), "Acumulado histórico · 2014–2021"),
             ("Promedio diario", numero(total / dias) if dias else "Sin dato", "Por día con datos · histórico"),
             ("Ingresos en días hábiles", numero(participacion_habil, 1) + " %" if participacion_habil is not None else "Sin dato", "Lunes a viernes sin feriados / total histórico · 2014–2021"),
             ("Participación ferroviaria", numero(participacion, 1) + " %" if participacion is not None else "Sin dato", "Todos los días: hábiles, fines de semana y feriados · 2014–2021")]
    return [html.Div([html.Span(titulo, className="kpi-label"), html.Strong(valor, className="kpi-value"),
                      html.Small(detalle)], className=f"kpi-card kpi-{i}") for i, (titulo, valor, detalle) in enumerate(cards)]


def registrar_callbacks(app, repository, catalogos):
    @lru_cache(maxsize=1)
    def indicadores_globales(revision):
        return consultar_kpis(repository)

    @app.callback(Output("indicadores", "children"), Output("mensaje-kpis", "children"),
                  Input("filtros-aplicados", "data"))
    def actualizar_kpis(aplicados):
        try:
            return tarjetas_kpi(indicadores_globales(aplicados["revision"]).iloc[0]), ""
        except duckdb.Error:
            logger.exception("No se pudieron consultar los KPI globales")
            return [], "Los indicadores globales no están disponibles. Reiniciá el dashboard para reintentar."

    @lru_cache(maxsize=16)
    def consultar_mensual(filtros, dias, validacion, revision):
        return consultar_evolucion(repository, filtros, dias, validacion)

    @app.callback(Output("grafico-01", "figure"), Output("mensaje-01", "children"),
                  Input("filtros-aplicados", "data"),
                  Input("evolucion-dias", "value"), Input("evolucion-linea", "value"),
                  Input("evolucion-categoria", "value"), Input("evolucion-validacion", "value"),
                  Input("evolucion-fechas", "start_date"), Input("evolucion-fechas", "end_date"))
    def actualizar_evolucion(aplicados, dias, linea, categoria, validacion, desde, hasta):
        try:
            if not isinstance(validacion, str) or validacion not in ("todos", *VALIDACIONES):
                raise ValueError("Seleccioná Todos o un único tipo de validación o pase.")
            if linea != "todas" and linea not in catalogos["lineas"]:
                raise ValueError("La línea seleccionada no es válida.")
            if categoria != "todas" and categoria not in CATEGORIAS:
                raise ValueError("La categoría seleccionada no es válida.")
            valores = dict(aplicados["filtros"])
            for clave in ("lineas", "estaciones", "categorias", "zonas", "comunas"):
                valores[clave] = tuple(valores.get(clave, ()))
            filtros = replace(Filtros(**valores), anio=None,
                              lineas=() if linea == "todas" else (linea,),
                              categorias=() if categoria == "todas" else (categoria,),
                              tipo_dia="todos", feriados="todos",
                              fecha_desde=desde or None, fecha_hasta=hasta or None)
            validar_filtros(filtros)
            datos = consultar_mensual(filtros, dias, validacion, aplicados["revision"])
            figura = temporal(datos, "mensual", {**catalogos, "anios": list(range(2014, 2022))}, filtros, area=True)
            return figura, ""
        except ValueError as error:
            return figura_vacia(), str(error)
        except duckdb.Error:
            logger.exception("No se pudo consultar la evolución mensual")
            return figura_vacia(), "La base no está disponible. Reiniciá el dashboard para reintentar."

    # Una caché compartida evita repetir lecturas entre gráficos con la misma selección.
    # El bloqueo evita consultas duplicadas cuando varios callbacks se inician a la vez.
    consulta_lock = RLock()

    @lru_cache(maxsize=64)
    def consultar_seccion(seccion, filtros):
        return consultar_dashboard(repository, filtros, secciones=(seccion,))[seccion]

    def registrar_grafico(numero, prefijo, seccion, controles):
        salidas = [Output(f"grafico-{numero:02d}", "figure"), Output(f"mensaje-{numero:02d}", "children")]
        if numero == 6:
            salidas.append(Output("frame-06", "style"))

        @app.callback(salidas, Input(f"{prefijo}-anio", "value"),
                      *[Input(control, "value") for control in controles])
        def actualizar(anio, *valores):
            altura = 420
            try:
                dias = "todos" if numero == 3 else valores[0]
                if dias not in DIAS_RANKING:
                    raise ValueError("El tipo de día no es válido.")
                if numero in (4, 5, 6) and (
                    not isinstance(valores[1], list) or any(v not in VALIDACIONES for v in valores[1])
                ):
                    raise ValueError("El tipo de validación seleccionado no es válido.")
                if numero == 3 and valores[0] not in ("todas", *CATEGORIAS):
                    raise ValueError("La categoría seleccionada no es válida.")
                filtros = Filtros(anio=None if anio == "todos" else anio,
                                  tipo_dia=dias if numero in (4, 5, 6) else "todos")
                validar_filtros(filtros)
                with consulta_lock:
                    datos = consultar_seccion(seccion, filtros)
                if numero == 3:
                    figura = mapa_calor(datos, valores[0])
                elif numero in (4, 5):
                    figura = barras_validaciones(datos, "linea" if numero == 4 else "categoria", valores[1])
                elif numero == 6:
                    figura, altura = composicion(datos, valores[1])
                else:
                    figura = barras_totales(datos, "comuna" if numero == 7 else "estacion", True, dias)
                mensaje = ""
            except ValueError as error:
                figura, mensaje = figura_vacia(), str(error)
            except duckdb.Error:
                logger.exception("No se pudo consultar el gráfico %s", numero)
                figura, mensaje = figura_vacia(), "La base no está disponible. Reiniciá el dashboard para reintentar."
            resultado = [figura, mensaje]
            if numero == 6:
                resultado.append({"height": f"{altura}px"})
            return resultado

    registrar_grafico(3, "mapa", "temporal", ["mapa-categoria"])
    registrar_grafico(4, "lineas", "totales", ["lineas-dias", "lineas-validaciones"])
    registrar_grafico(5, "categorias", "totales", ["categorias-dias", "categorias-validaciones"])
    registrar_grafico(6, "composicion", "composicion", ["composicion-dias", "composicion-validaciones"])
    registrar_grafico(7, "comunas", "totales", ["comunas-dias"])
    registrar_grafico(8, "estaciones", "totales", ["estaciones-dias"])
