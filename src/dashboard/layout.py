"""Una página con KPI globales y filtros locales en los gráficos."""

from dataclasses import asdict

from dash import dcc, html

from src.dashboard.queries import CATEGORIAS, DIAS_RANKING, VALIDACIONES, Filtros


def campo(titulo, componente):
    return html.Div([html.Label(titulo, htmlFor=componente.id), componente], className="filter-field")


def selector(id, opciones, valor=None, multiple=False, placeholder=None):
    return dcc.Dropdown(id=id, options=opciones, value=valor, multi=multiple,
                        clearable=multiple, placeholder=placeholder)


def filtro_validaciones(id):
    return html.Fieldset([
        html.Legend("Tipos de validación o pase"),
        dcc.Checklist(id=id, options=[
            {"label": label, "value": key} for key, label in VALIDACIONES.items()
        ], value=list(VALIDACIONES), inline=True),
    ], className="validation-filter")


def tarjeta(numero, titulo, *, controles=None, detalle=None, ancho=False):
    return html.Article([
        html.H2([html.Span(f"{numero:02d}", className="chart-number"), titulo]),
        html.Div(controles, className="chart-controls") if controles else None,
        html.P(detalle, className="chart-description") if detalle else None,
        html.Div(html.Div(dcc.Graph(
            id=f"grafico-{numero:02d}", responsive=True,
            style={"height": "100%", "width": "100%", "minWidth": 0},
            config={"displaylogo": False, "locale": "es"},
        ), className="chart-frame", id=f"frame-{numero:02d}"),
                 className="chart-viewport" + (" composition-viewport" if numero == 7 else "")),
        html.Div(id="mensaje-01", role="status", className="status-message") if numero == 1 else None,
    ], className="chart-card" + (" chart-wide" if ancho else ""))


def crear_layout(catalogos):
    periodo = f"{catalogos['anios'][0]}–{catalogos['anios'][-1]}"
    return html.Div([
        dcc.Store(id="filtros-aplicados", data={"filtros": asdict(Filtros()), "revision": 0}),
        html.Header([
            html.Div([html.Span("SUBTES", className="brand-name"), html.Span("BA", className="brand-badge")], className="brand"),
            html.Div([html.H1("Evolución histórica de los ingresos al subte"),
                      html.P(f"Buenos Aires · {periodo}")], className="page-title"),
            html.Span("DATOS HISTÓRICOS", className="data-badge"),
        ], className="topbar"),
        dcc.Loading([
            html.P("Indicadores globales · 2014–2021 · No cambian con los filtros", className="applied-summary"),
            html.Div(id="mensaje-kpis", role="status", className="status-message"),
            html.Section(id="indicadores", className="kpi-grid", **{"aria-label": "Indicadores principales"}),
            html.P(id="cobertura", className="coverage-note"),
            html.Div(id="mensaje-consulta", role="status", className="status-message"),
            html.Main([
                tarjeta(1, "Evolución mensual de los ingresos", ancho=True, controles=[
                    campo("Año", selector("evolucion-anio", [{"label": "Todos los años", "value": "todos"}] + [
                        {"label": str(anio), "value": anio} for anio in range(2014, 2022)
                    ], "todos")),
                    campo("Tipo de día", selector("evolucion-dias", [
                        {"label": label, "value": key} for key, label in DIAS_RANKING.items()
                    ], "todos")),
                    campo("Línea", selector("evolucion-linea", [{"label": "Todas las líneas", "value": "todas"}] + [
                        {"label": linea, "value": linea} for linea in catalogos["lineas"]
                    ], "todas")),
                    campo("Categoría de estación", selector("evolucion-categoria", [
                        {"label": "Todas las categorías", "value": "todas"}
                    ] + [{"label": c.title(), "value": c} for c in CATEGORIAS], "todas")),
                    campo("Tipo de validación o pase", selector("evolucion-validacion", [
                        {"label": "Todos", "value": "todos"}
                    ] + [{"label": label, "value": key} for key, label in VALIDACIONES.items()], "todos")),
                ], detalle="Ingresos mensuales según los filtros seleccionados."),
                tarjeta(2, "Ingresos totales por hora y categoría de estación", controles=[
                    campo("Tipo de día", selector("horario-dias", [
                        {"label": label, "value": key} for key, label in DIAS_RANKING.items()
                    ], "todos")),
                ], detalle="Cada curva muestra los ingresos acumulados por hora de una categoría de estación."),
                tarjeta(3, "Ingresos por día de la semana y hora", controles=[
                    campo("Categoría de estación", selector("mapa-categoria", [
                        {"label": "Todas las categorías", "value": "todas"}
                    ] + [{"label": c.title(), "value": c} for c in CATEGORIAS], "todas")),
                ], detalle="Promedio diario por día y hora. Azul más intenso indica mayores ingresos; gris indica ausencia de datos."),
                tarjeta(4, "Ingresos totales por línea", controles=[filtro_validaciones("lineas-validaciones")],
                        detalle="Cada segmento representa un tipo de validación. Al lado se muestra el total seleccionado por línea."),
                tarjeta(5, "Ingresos totales por categoría", controles=[filtro_validaciones("categorias-validaciones")],
                        detalle="Cada segmento representa un tipo de validación. Al lado se muestra el total seleccionado por categoría."),
                tarjeta(6, "Comparativa de ingresos totales para Estaciones con Trasbordo Ferroviario vs Estaciones sin Transbordo Ferroviario", controles=[
                    campo("Tipo de día", selector("ferroviario-dias", [
                        {"label": label, "value": key} for key, label in DIAS_RANKING.items()
                    ], "todos")),
                ], detalle="Cada porción muestra la participación de su grupo en los ingresos totales seleccionados."),
                tarjeta(7, "Ingresos totales por zona", controles=[
                    filtro_validaciones("composicion-validaciones"),
                ], detalle="Cada segmento representa un tipo de validación. Al lado se muestra el total seleccionado por zona."),
                tarjeta(8, "Ranking de las comunas con mayor ingreso total", controles=[
                    campo("Tipo de día", selector("comunas-dias", [
                        {"label": label, "value": key} for key, label in DIAS_RANKING.items()
                    ], "todos")),
                ], detalle="Comunas ordenadas de mayor a menor ingreso total."),
                tarjeta(9, "Ranking de las 15 estaciones con mayor ingreso total", controles=[
                    campo("Tipo de día", selector("estaciones-dias", [
                        {"label": label, "value": key} for key, label in DIAS_RANKING.items()
                    ], "todos")),
                ], detalle="Estaciones ordenadas por ingreso total, identificadas por nombre, línea y categoría."),
            ], className="charts-grid"),
        ], type="circle", color="#17345c", delay_show=250),
        html.Footer([
            html.P("Día hábil: lunes a viernes sin feriados. Día no hábil: sábados, domingos y feriados."),
            html.P("Ingresos registrados, no personas únicas ni viajes completos."),
        ], className="footer"),
    ], className="dashboard")
