"""Presentación y filtros del dashboard estratégico de nueve gráficos."""

from dataclasses import replace
from functools import lru_cache
import logging

import duckdb
import pandas as pd
import plotly.graph_objects as go
from dash import Input, Output, html

from src.dashboard.queries import (
    CATEGORIAS, VALIDACIONES, DIAS_RANKING, GRUPO_FERROVIARIO, GRUPO_RESTO,
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


def torta_ferroviaria(indicadores):
    total = indicadores["total"]
    if pd.isna(total) or total <= 0:
        return figura_vacia("No hay ingresos positivos para calcular participaciones")
    ferroviario = indicadores["total_ferroviario"]
    ferroviario = 0 if pd.isna(ferroviario) else ferroviario
    fig = go.Figure(go.Pie(
        labels=[GRUPO_FERROVIARIO, GRUPO_RESTO], values=[ferroviario, total - ferroviario],
        marker={"colors": ["#247aff", "#7d91af"], "line": {"color": "white", "width": 2}},
        sort=False, hole=0, textinfo="percent", textposition="inside",
        hovertemplate="%{label}<br>Ingresos: %{value:,.0f}<br>%{percent}<extra></extra>",
    ))
    return estilizar(fig)


def _limites(catalogos, filtros):
    anios = [filtros.anio] if filtros.anio is not None else catalogos["anios"]
    return pd.Timestamp(f"{min(anios)}-01-01"), pd.Timestamp(f"{max(anios)}-12-31")


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
            eje = pd.date_range(inicio, fin, freq="MS")
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
            fig.update_xaxes(tickvals=list(eje), ticktext=MESES)
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


def perfil_horario(datos, dias="todos"):
    if dias not in DIAS_RANKING:
        raise ValueError("El tipo de día del perfil horario no es válido.")
    data = datos.copy()
    if dias != "todos":
        data["total"] = data["total_" + dias]
    if data.empty or not data["total"].notna().any():
        return figura_vacia("No hay registros para el tipo de día y los filtros aplicados")
    escala, titulo = _escala(data["total"])
    eje = list(range(24))
    fig = go.Figure()
    for categoria in CATEGORIAS:
        filas = data.loc[data["categoria"] == categoria]
        if filas.empty or not filas["total"].notna().any():
            continue
        valores = filas.set_index("eje")["total"].reindex(eje)
        fig.add_scatter(x=eje, y=valores / escala, mode="lines", connectgaps=False,
                        name=ETIQUETAS_CATEGORIA[categoria], line={"color": COLORES_CATEGORIA[categoria], "width": 2},
                        customdata=valores, hovertemplate="%{x}:00<br>Ingresos: %{customdata:,.0f}<extra>%{fullData.name}</extra>")
    fig = estilizar(fig)
    ticks = list(range(0, 24, 3))
    fig.update_xaxes(tickvals=ticks, ticktext=[f"{t:02d}:00" for t in ticks], title="Hora del día", range=[0, 23])
    fig.update_yaxes(title=titulo, rangemode="tozero")
    fig.update_layout(margin={"b": 110})
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
    participacion = (0 if pd.isna(ferro) else ferro) / total * 100 if pd.notna(total) and total > 0 else None
    cards = [("Ingresos totales", abreviar(total), "Acumulado histórico · 2014–2021"),
             ("Promedio diario", numero(total / dias) if dias else "Sin dato", "Por día con datos · histórico"),
             ("Estaciones observadas", numero(fila["estaciones"]), "Con registros en todo el histórico"),
             ("Participación ferroviaria", numero(participacion, 1) + " %" if participacion is not None else "Sin dato", "Ingresos en estaciones ferroviarias · histórico")]
    return [html.Div([html.Span(titulo, className="kpi-label"), html.Strong(valor, className="kpi-value"),
                      html.Small(detalle)], className=f"kpi-card kpi-{i}") for i, (titulo, valor, detalle) in enumerate(cards)]


def renderizar(datos, filtros, catalogos, *, horario_dias="todos", mapa_categoria="todas", validaciones=None,
               comunas_dias="todos", estaciones_dias="todos", ferroviario_dias="todos",
               lineas_validaciones=None, categorias_validaciones=None):
    if ferroviario_dias not in DIAS_RANKING:
        raise ValueError("El tipo de día del gráfico ferroviario no es válido.")
    fila = datos["indicadores"].iloc[0]
    fila_pie = fila.copy()
    if ferroviario_dias != "todos":
        categorias = datos["totales"].loc[datos["totales"]["nivel"] == "categoria"]
        ferroviarias = categorias.loc[categorias["etiqueta"] == "TRASBORDO FERROVIARIO"]
        columna = "total_" + ferroviario_dias
        fila_pie["total"] = categorias[columna].sum(min_count=1)
        fila_pie["total_ferroviario"] = ferroviarias[columna].sum(min_count=1)
    figura_composicion, altura = composicion(datos["composicion"], validaciones)
    figuras = [temporal(datos["temporal"], "mensual", catalogos, filtros, area=True),
               perfil_horario(datos["horario"], horario_dias),
               mapa_calor(datos["temporal"], mapa_categoria),
               barras_validaciones(datos["totales"], "linea", lineas_validaciones),
               barras_validaciones(datos["totales"], "categoria", categorias_validaciones),
               torta_ferroviaria(fila_pie), figura_composicion,
               barras_totales(datos["totales"], "comuna", True, comunas_dias),
               barras_totales(datos["totales"], "estacion", True, estaciones_dias)]
    cobertura = f"Histórico · {numero(fila['estaciones'])} estaciones · {numero(fila['dias'])} días con registros."
    return figuras, cobertura, altura


def registrar_callbacks(app, repository, catalogos):
    # Datos agregados en el servidor. Cambiar una vista no vuelve a leer el DW.
    # Los filtros visibles son locales; el estado base comienza sin restricciones.
    @lru_cache(maxsize=4)
    def consultar(filtros, revision):
        return consultar_dashboard(repository, filtros)

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
                  Input("filtros-aplicados", "data"), Input("evolucion-anio", "value"),
                  Input("evolucion-dias", "value"), Input("evolucion-linea", "value"),
                  Input("evolucion-categoria", "value"), Input("evolucion-validacion", "value"))
    def actualizar_evolucion(aplicados, anio, dias, linea, categoria, validacion):
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
            filtros = replace(Filtros(**valores), anio=None if anio == "todos" else anio,
                              lineas=() if linea == "todas" else (linea,),
                              categorias=() if categoria == "todas" else (categoria,),
                              tipo_dia="todos", feriados="todos")
            validar_filtros(filtros)
            datos = consultar_mensual(filtros, dias, validacion, aplicados["revision"])
            figura = temporal(datos, "mensual", {**catalogos, "anios": list(range(2014, 2022))}, filtros, area=True)
            return figura, ""
        except ValueError as error:
            return figura_vacia(), str(error)
        except duckdb.Error:
            logger.exception("No se pudo consultar la evolución mensual")
            return figura_vacia(), "La base no está disponible. Reiniciá el dashboard para reintentar."

    salidas = [Output("cobertura", "children"), Output("mensaje-consulta", "children")]
    salidas += [Output(f"grafico-{i:02d}", "figure") for i in range(2, 10)]
    salidas += [Output("frame-07", "style")]

    @app.callback(salidas, Input("filtros-aplicados", "data"), Input("horario-dias", "value"),
                  Input("mapa-categoria", "value"),
                  Input("composicion-validaciones", "value"),
                  Input("comunas-dias", "value"), Input("estaciones-dias", "value"), Input("ferroviario-dias", "value"),
                  Input("lineas-validaciones", "value"), Input("categorias-validaciones", "value"))
    def actualizar(aplicados, horario_dias, mapa_categoria, validaciones, comunas_dias, estaciones_dias, ferroviario_dias,
                   lineas_validaciones, categorias_validaciones):
        try:
            if horario_dias not in DIAS_RANKING:
                raise ValueError("El tipo de día del perfil horario no es válido.")
            if mapa_categoria not in ("todas", *CATEGORIAS):
                raise ValueError("La categoría del mapa de calor no es válida.")
            if any(not isinstance(seleccion, list) or any(v not in VALIDACIONES for v in seleccion)
                   for seleccion in (validaciones, lineas_validaciones, categorias_validaciones)):
                raise ValueError("El tipo de validación seleccionado no es válido.")
            valores = dict(aplicados["filtros"])
            for clave in ("lineas", "estaciones", "categorias", "zonas", "comunas"):
                valores[clave] = tuple(valores.get(clave, ()))
            filtros = Filtros(**valores)
            validar_filtros(filtros)
            datos = consultar(filtros, aplicados["revision"])
            figuras, cobertura, altura = renderizar(
                datos, filtros, catalogos, horario_dias=horario_dias, mapa_categoria=mapa_categoria, validaciones=validaciones,
                comunas_dias=comunas_dias, estaciones_dias=estaciones_dias, ferroviario_dias=ferroviario_dias,
                lineas_validaciones=lineas_validaciones, categorias_validaciones=categorias_validaciones)
        except ValueError as error:
            return ["", str(error), *[figura_vacia() for _ in range(8)], {"height": "420px"}]
        except duckdb.Error:
            logger.exception("No se pudo consultar el dashboard")
            return ["", "La base no está disponible. Cerrá otras conexiones y reiniciá el dashboard para reintentar.",
                    *[figura_vacia() for _ in range(8)], {"height": "420px"}]
        return [cobertura, "", *figuras[1:], {"height": f"{altura}px"}]
