"""Una página con KPI globales y filtros locales en los gráficos."""

from collections import Counter
from dataclasses import asdict

from dash import dcc, html

from src.dashboard.queries import CATEGORIAS, DIAS_RANKING, VALIDACIONES, Filtros


def campo(titulo, componente):
    return html.Div([html.Label(titulo, htmlFor=componente.id), componente], className="filter-field")


def selector(id, opciones, valor=None, multiple=False, placeholder=None):
    return dcc.Dropdown(id=id, options=opciones, value=valor, multi=multiple,
                        clearable=multiple, placeholder=placeholder)


def filtro_anio(id):
    return campo("Año", selector(id, [{"label": "Todos", "value": "todos"}] + [
        {"label": str(anio), "value": anio} for anio in range(2014, 2022)
    ], "todos"))


def filtro_dia(id):
    return campo("Tipo de día", selector(id, [
        {"label": label, "value": key} for key, label in DIAS_RANKING.items()
    ], "todos"))


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
        html.Div(html.Div(dcc.Loading(dcc.Graph(
            id=f"grafico-{numero:02d}", responsive=True,
            style={"height": "100%", "width": "100%", "minWidth": 0},
            config={"displaylogo": False, "locale": "es"},
        ), type="circle", color="#17345c", delay_show=250,
            parent_style={"height": "100%"}, style={"height": "100%"}),
                 className="chart-frame", id=f"frame-{numero:02d}"),
                 className="chart-viewport" + (" composition-viewport" if numero == 6 else "")),
        html.Div(id=f"mensaje-{numero:02d}", role="status", className="status-message"),
    ], className="chart-card" + (" chart-wide" if ancho else ""))


def contexto_red(catalogos):
    """Describe el catálogo de estaciones, independientemente de los filtros."""
    estaciones = catalogos["estaciones"]
    categorias = Counter(
        estacion["categoria_estacion"] or "SIN CATEGORÍA"
        for estacion in estaciones
    )
    orden = [*CATEGORIAS, *sorted(set(categorias) - set(CATEGORIAS))]
    periodo = f"{catalogos['anios'][0]}–{catalogos['anios'][-1]}"
    datos = [
        (len(estaciones), "Estaciones del catálogo"),
        (len(catalogos["lineas"]), "Líneas"),
        (periodo, "Período con registros"),
        ("15 min", "Resolución de los datos"),
    ]
    return html.Section([
        html.H2("La red en contexto", id="contexto-red-titulo"),
        html.P("Información del catálogo · valores fijos, independientes de los filtros",
               className="network-subtitle"),
        html.Dl([
            html.Div([
                html.Dt(etiqueta),
                html.Dd(str(valor)),
            ], className="network-stat")
            for valor, etiqueta in datos
        ], className="network-stats"),
        html.Div([
            html.H3("Estaciones por categoría"),
            html.Ul([
                html.Li([
                    html.Span(categoria.capitalize()),
                    html.Strong(str(categorias[categoria])),
                ], className=f"network-category network-category-{indice}")
                for indice, categoria in enumerate(orden)
            ], className="network-categories"),
        ], className="network-breakdown"),
        html.P([
            html.Strong(
                f"Cobertura del catálogo de estaciones: {len(catalogos['zonas'])} zonas"
                f" · {len(catalogos['comunas'])} comunas"
            ),
            html.Span("Se cuentan únicamente las zonas y comunas representadas en las estaciones del catálogo."),
        ], className="network-territory"),
    ], className="network-context", **{"aria-labelledby": "contexto-red-titulo"})


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
        contexto_red(catalogos),
        html.Div([
            html.P("Indicadores globales · 2014–2021 · No cambian con los filtros", className="applied-summary"),
            html.Div(id="mensaje-kpis", role="status", className="status-message"),
            dcc.Loading(html.Section(id="indicadores", className="kpi-grid",
                                    **{"aria-label": "Indicadores principales"}), delay_show=250),
            html.P(f"Cobertura histórica · {catalogos['desde']} a {catalogos['hasta']}",
                   id="cobertura", className="coverage-note"),
            html.Main([
                tarjeta(1, "Evolución mensual de los ingresos", ancho=True, controles=[
                    campo("Desde / Hasta", dcc.DatePickerRange(
                        id="evolucion-fechas", min_date_allowed="2014-01-01", max_date_allowed="2021-12-31",
                        start_date="2014-01-01", end_date="2021-12-31",
                        display_format="DD/MM/YYYY", first_day_of_week=1, clearable=True,
                        start_date_placeholder_text="Desde", end_date_placeholder_text="Hasta",
                    )),
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
                ], detalle="Ingresos mensuales entre las fechas Desde y Hasta, ambas inclusive. Al limpiar el rango se muestra todo el histórico."),
                tarjeta(2, "Forma de los picos de ingresos", ancho=True, controles=[
                    campo("Año", selector("picos-anio", [
                        {"label": "Todos", "value": "todos"},
                        *[{"label": str(anio), "value": anio} for anio in range(2014, 2022)],
                    ], "todos")),
                    campo("Tipo de día", selector("picos-dias", [
                        {"label": label, "value": key} for key, label in DIAS_RANKING.items()
                    ], "semana")),
                    campo("Intervalo", selector("picos-intervalo", [
                        {"label": "15 min", "value": 15},
                        {"label": "30 min", "value": 30},
                        {"label": "1 hora", "value": 60},
                    ], 15)),
                    campo("Categoría de estación", selector("picos-categoria", [
                        {"label": "Todas", "value": "todas"},
                        *[{"label": categoria.capitalize(), "value": categoria} for categoria in CATEGORIAS],
                    ], "todas")),
                ], detalle=(
                    "Perfil de 00:00 a 24:00. Promedio de ingresos por estación/día "
                    "en cada intervalo, normalizado al máximo de cada curva = 100. "
                    "Matutina: 06:00–10:00; vespertina: 16:00–20:00. "
                    "Compara formas, no volúmenes absolutos. Los bloques de 30 y 60 minutos suman los intervalos "
                    "originales de 15 minutos; los bloques incompletos no se convierten en cero. "
                    "La cobertura puede variar por horario (ver detalle al pasar el cursor)."
                )),
                tarjeta(3, "Ingresos por día de la semana y hora", controles=[
                    filtro_anio("mapa-anio"),
                    campo("Categoría de estación", selector("mapa-categoria", [
                        {"label": "Todas las categorías", "value": "todas"}
                    ] + [{"label": c.title(), "value": c} for c in CATEGORIAS], "todas")),
                ], detalle="Promedio diario por día y hora. Azul más intenso indica mayores ingresos; gris indica ausencia de datos."),
                tarjeta(4, "Ingresos totales por línea", controles=[
                    filtro_anio("lineas-anio"), filtro_dia("lineas-dias"), filtro_validaciones("lineas-validaciones")],
                        detalle="Cada segmento representa un tipo de validación. Al lado se muestra el total seleccionado por línea."),
                tarjeta(5, "Ingresos totales por categoría", controles=[
                    filtro_anio("categorias-anio"), filtro_dia("categorias-dias"), filtro_validaciones("categorias-validaciones")],
                        detalle="Cada segmento representa un tipo de validación. Al lado se muestra el total seleccionado por categoría."),
                tarjeta(6, "Ingresos totales por zona", controles=[
                    filtro_anio("composicion-anio"), filtro_dia("composicion-dias"),
                    filtro_validaciones("composicion-validaciones"),
                ], detalle="Cada segmento representa un tipo de validación. Al lado se muestra el total seleccionado por zona."),
                tarjeta(7, "Ranking de las comunas con mayor ingreso total", controles=[
                    filtro_anio("comunas-anio"),
                    campo("Tipo de día", selector("comunas-dias", [
                        {"label": label, "value": key} for key, label in DIAS_RANKING.items()
                    ], "todos")),
                ], detalle="Comunas ordenadas de mayor a menor ingreso total."),
                tarjeta(8, "Ranking de las 15 estaciones con mayor ingreso total", controles=[
                    filtro_anio("estaciones-anio"),
                    campo("Tipo de día", selector("estaciones-dias", [
                        {"label": label, "value": key} for key, label in DIAS_RANKING.items()
                    ], "todos")),
                ], detalle="Estaciones ordenadas por ingreso total, identificadas por nombre, línea y categoría."),
            ], className="charts-grid"),
        ]),
        html.Footer([
            html.P("Día hábil: lunes a viernes sin feriados. Día no hábil: sábados, domingos y feriados."),
            html.P("Ingresos registrados, no personas únicas ni viajes completos."),
        ], className="footer"),
    ], className="dashboard")
