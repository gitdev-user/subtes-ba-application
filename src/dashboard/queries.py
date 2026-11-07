"""Agregados del dashboard histórico; SQL parametrizado, sin datos de detalle al cliente."""

from dataclasses import dataclass
from datetime import date

import pandas as pd


CATEGORIAS = ("INTERMEDIA", "INTERCAMBIO", "TRASBORDO FERROVIARIO", "CABECERA")
VALIDACIONES = {"pax_pago": "Pasajes pagos", "pax_pases_pagos": "Pases pagos", "pax_franq": "Franquicias"}
GRUPO_FERROVIARIO = "Trasbordo ferroviario"
GRUPO_RESTO = "Sin trasbordo ferroviario"
DIAS_RANKING = {"todos": "Todos los días", "semana": "Día hábil",
                "descanso": "Día no hábil"}


@dataclass(frozen=True)
class Filtros:
    anio: int | None = None
    lineas: tuple = ()
    estaciones: tuple = ()
    categorias: tuple = ()
    zonas: tuple = ()
    comunas: tuple = ()
    tipo_dia: str = "todos"
    feriados: str = "todos"
    fecha_desde: str | None = None
    fecha_hasta: str | None = None


def validar_filtros(filtros):
    if filtros.anio is not None and (type(filtros.anio) is not int or not 2014 <= filtros.anio <= 2021):
        raise ValueError("Seleccioná Todos o un año entre 2014 y 2021.")
    if filtros.tipo_dia not in ("todos", "semana", "descanso", "fin_semana"):
        raise ValueError("El tipo de día no es válido.")
    if filtros.feriados not in ("todos", "si", "no"):
        raise ValueError("La condición de feriado no es válida.")
    if any(c not in CATEGORIAS for c in filtros.categorias):
        raise ValueError("La categoría seleccionada no es válida.")
    for valor in (filtros.fecha_desde, filtros.fecha_hasta):
        if valor is not None:
            try:
                fecha = date.fromisoformat(valor)
            except (TypeError, ValueError):
                raise ValueError("Seleccioná fechas válidas para el rango.") from None
            if not date(2014, 1, 1) <= fecha <= date(2021, 12, 31):
                raise ValueError("El rango debe estar entre 2014 y 2021.")
    if filtros.fecha_desde and filtros.fecha_hasta and filtros.fecha_desde > filtros.fecha_hasta:
        raise ValueError("La fecha inicial no puede ser posterior a la final.")


def obtener_catalogos(repository):
    cobertura = repository.query("""
        SELECT f.anio, MIN(f.fecha) AS desde, MAX(f.fecha) AS hasta
        FROM dw.tabla_fact_historico_subtes h
        JOIN dw.tabla_dim_fecha f ON f.id = h.fecha_id
        GROUP BY f.anio ORDER BY f.anio
    """)
    if cobertura.empty:
        raise ValueError("No hay registros cargados en la tabla de hechos.")
    estaciones = repository.query("""
        SELECT id, nombre_estacion, linea_subte, categoria_estacion, zona, comuna
        FROM dw.tabla_dim_estacion ORDER BY linea_subte, nombre_estacion
    """)
    return {
        "anios": cobertura["anio"].astype(int).tolist(),
        "desde": pd.Timestamp(cobertura["desde"].min()).date().isoformat(),
        "hasta": pd.Timestamp(cobertura["hasta"].max()).date().isoformat(),
        "lineas": estaciones["linea_subte"].unique().tolist(),
        "zonas": sorted(estaciones["zona"].unique().tolist()),
        "comunas": sorted(estaciones["comuna"].unique().tolist(), key=int),
        "estaciones": estaciones.to_dict("records"),
    }


def _base(filtros):
    validar_filtros(filtros)
    condiciones = ["f.anio BETWEEN 2014 AND 2021"]
    params = []
    if filtros.anio is not None:
        condiciones.append("f.anio = ?")
        params.append(filtros.anio)
    for condicion, valor in (("f.fecha >= ?", filtros.fecha_desde), ("f.fecha <= ?", filtros.fecha_hasta)):
        if valor is not None:
            condiciones.append(condicion)
            params.append(valor)
    for columna, valores in (
        ("e.linea_subte", filtros.lineas), ("e.id", filtros.estaciones),
        ("e.categoria_estacion", filtros.categorias), ("e.zona", filtros.zonas),
        ("e.comuna", filtros.comunas),
    ):
        if valores:
            condiciones.append(f"{columna} IN ({', '.join('?' for _ in valores)})")
            params.extend(valores)
    if filtros.tipo_dia != "todos":
        condiciones.append({"semana": "(NOT f.es_fin_semana AND NOT f.es_feriado)",
                            "descanso": "(f.es_fin_semana OR f.es_feriado)",
                            "fin_semana": "f.es_fin_semana"}[filtros.tipo_dia])
    if filtros.feriados != "todos":
        condiciones.append("f.es_feriado" if filtros.feriados == "si" else "NOT f.es_feriado")
    return f"""
        WITH base AS (
            SELECT f.fecha, f.dia_semana, f.es_fin_semana, f.es_feriado,
                   date_trunc('week', f.fecha) AS semana_fecha,
                   date_trunc('month', f.fecha) AS mes_fecha,
                   CASE WHEN f.mes IN (12,1,2) THEN 1 WHEN f.mes IN (3,4,5) THEN 2
                        WHEN f.mes IN (6,7,8) THEN 3 ELSE 4 END AS temporada,
                   t.hora,
                   e.id AS id_estacion, e.nombre_estacion || ' · ' || replace(e.linea_subte, 'LINEA ', '') AS estacion,
                   e.linea_subte AS linea, e.categoria_estacion AS categoria, e.zona, e.comuna,
                   h.pax_total AS cantidad, h.pax_pago, h.pax_pases_pagos, h.pax_franq
            FROM dw.tabla_fact_historico_subtes h
            JOIN dw.tabla_dim_fecha f ON f.id = h.fecha_id
            JOIN dw.tabla_dim_hora t ON t.id = h.hora_id
            JOIN dw.tabla_dim_estacion e ON e.id = h.id_estacion
            WHERE {' AND '.join(condiciones)}
        )
    """, params


def consultar_evolucion(repository, filtros, dias="todos", validacion="todos"):
    """Serie mensual del gráfico 01 con selección única de validación o total."""
    if dias not in DIAS_RANKING:
        raise ValueError("El tipo de día de la evolución no es válido.")
    columnas = {"todos": "cantidad", **{v: v for v in VALIDACIONES}}
    if not isinstance(validacion, str) or validacion not in columnas:
        raise ValueError("Seleccioná Todos o un único tipo de validación o pase.")
    columna = columnas[validacion]
    base, params = _base(filtros)
    condicion = {"todos": "TRUE", "semana": "NOT es_fin_semana AND NOT es_feriado",
                 "descanso": "es_fin_semana OR es_feriado"}[dias]
    return repository.query(base + f"""
        SELECT 'mensual' AS nivel, CAST(mes_fecha AS VARCHAR) AS eje, SUM({columna}) AS total
        FROM base WHERE {condicion} GROUP BY mes_fecha ORDER BY mes_fecha
    """, params)


def consultar_kpis(repository):
    """Indicadores de todo el histórico 2014–2021, sin filtros de usuario."""
    base, params = _base(Filtros())
    return repository.query(base + """SELECT SUM(cantidad) AS total,
        COUNT(DISTINCT fecha) FILTER(WHERE cantidad IS NOT NULL) AS dias_conocidos,
        SUM(cantidad) FILTER(WHERE NOT es_fin_semana AND NOT es_feriado) AS total_habiles,
        SUM(cantidad) FILTER(WHERE categoria = 'TRASBORDO FERROVIARIO') AS total_ferroviario
        FROM base""", params)


def consultar_dashboard(repository, filtros, secciones=None):
    """Cuatro lecturas agregadas abastecen los gráficos generales y sus selectores.

    Agrega por estación o fecha antes de calcular niveles y días distintos,
    evitando repetir esas operaciones sobre todos los intervalos originales.
    Los nulos se conservan; la composición suma componentes conocidos por zona.
    """
    base, params = _base(filtros)
    completos = "pax_pago IS NOT NULL AND pax_pases_pagos IS NOT NULL AND pax_franq IS NOT NULL"
    consultas = {
        "indicadores": f"""SELECT SUM(cantidad) AS total,
            COUNT(*) AS registros, COUNT(cantidad) AS conocidos,
            COUNT(DISTINCT fecha) AS dias,
            COUNT(DISTINCT fecha) FILTER(WHERE cantidad IS NOT NULL) AS dias_conocidos,
            COUNT(DISTINCT id_estacion) AS estaciones,
            COUNT(DISTINCT id_estacion) FILTER(WHERE categoria = 'TRASBORDO FERROVIARIO') AS estaciones_ferroviarias,
            SUM(cantidad) FILTER(WHERE categoria = 'TRASBORDO FERROVIARIO') AS total_ferroviario,
            COUNT(*) FILTER(WHERE NOT ({completos})) AS incompletos,
            COUNT(*) FILTER(WHERE {completos} AND cantidad IS NOT NULL
                AND cantidad <> pax_pago + pax_pases_pagos + pax_franq) AS discrepancias
            FROM base""",
        "totales": """, agregados_estacion AS (
            SELECT id_estacion,
                   SUM(cantidad) AS total,
                   SUM(pax_pago) AS pax_pago, SUM(pax_pases_pagos) AS pax_pases_pagos,
                   SUM(pax_franq) AS pax_franq,
                   SUM(cantidad) FILTER(WHERE NOT es_fin_semana AND NOT es_feriado) AS total_semana,
                   SUM(cantidad) FILTER(WHERE es_fin_semana OR es_feriado) AS total_descanso,
                   BOOL_OR(NOT es_fin_semana AND NOT es_feriado) AS tiene_semana,
                   BOOL_OR(es_fin_semana OR es_feriado) AS tiene_descanso
            FROM base GROUP BY id_estacion
        ), por_estacion AS (
            SELECT a.*, e.nombre_estacion || ' · ' || replace(e.linea_subte, 'LINEA ', '') AS estacion,
                   e.linea_subte AS linea, e.categoria_estacion AS categoria, e.comuna
            FROM agregados_estacion a JOIN dw.tabla_dim_estacion e ON e.id = a.id_estacion
        ) SELECT
            CASE WHEN GROUPING(linea) = 0 THEN 'linea' WHEN GROUPING(categoria) = 0 THEN 'categoria'
                 WHEN GROUPING(comuna) = 0 THEN 'comuna' ELSE 'estacion' END AS nivel,
            coalesce(linea, categoria, comuna, estacion) AS etiqueta,
            CASE WHEN GROUPING(estacion) = 0 THEN MIN(categoria) END AS categoria_estacion,
            SUM(total) AS total,
            SUM(pax_pago) AS pax_pago, SUM(pax_pases_pagos) AS pax_pases_pagos, SUM(pax_franq) AS pax_franq,
            SUM(total_semana) AS total_semana, SUM(total_descanso) AS total_descanso,
            COUNT(DISTINCT id_estacion) AS estaciones,
            COUNT(DISTINCT id_estacion) FILTER(WHERE tiene_semana) AS estaciones_semana,
            COUNT(DISTINCT id_estacion) FILTER(WHERE tiene_descanso) AS estaciones_descanso
            FROM por_estacion GROUP BY GROUPING SETS ((linea), (categoria), (comuna), (estacion))""",
        "temporal": """, por_fecha AS (
            SELECT fecha, mes_fecha, dia_semana, hora, categoria,
                   SUM(cantidad) AS total, COUNT(cantidad) > 0 AS conocido
            FROM base GROUP BY fecha, mes_fecha, dia_semana, hora, categoria
        ) SELECT
            CASE WHEN GROUPING(mes_fecha) = 0 THEN 'mensual' ELSE 'mapa' END AS nivel,
            coalesce(CAST(mes_fecha AS VARCHAR), CAST(dia_semana AS VARCHAR)) AS eje,
            coalesce(categoria, 'todas') AS categoria, dia_semana, hora,
            SUM(total) AS total,
            COUNT(DISTINCT fecha) FILTER(WHERE conocido) AS dias_conocidos,
            SUM(total)::DOUBLE / nullif(COUNT(DISTINCT fecha) FILTER(WHERE conocido), 0) AS promedio
            FROM por_fecha GROUP BY GROUPING SETS ((mes_fecha), (dia_semana, hora), (categoria, dia_semana, hora))""",
        "composicion": f"""SELECT
            zona AS etiqueta,
            SUM(pax_pago) AS pax_pago, SUM(pax_pases_pagos) AS pax_pases_pagos, SUM(pax_franq) AS pax_franq,
            COUNT(*) FILTER(WHERE NOT ({completos})) AS incompletos
            FROM base GROUP BY zona""",
    }
    nombres = tuple(consultas) if secciones is None else tuple(secciones)
    if any(nombre not in consultas for nombre in nombres):
        raise ValueError("La sección solicitada no es válida.")
    return {nombre: repository.query(base + consultas[nombre], params) for nombre in nombres}
