# src/etl/transform.py

from collections.abc import Callable, Sequence

import polars as pl


Operation = Callable[[pl.Expr], pl.Expr]
Frame = pl.DataFrame | pl.LazyFrame


class Transformer:
    @staticmethod
    def strip(expr: pl.Expr) -> pl.Expr:
        return expr.cast(pl.String).str.strip_chars()

    @staticmethod
    def normalize_spaces(expr: pl.Expr) -> pl.Expr:
        return expr.cast(pl.String).str.replace_all(r"\s+", " ")

    @staticmethod
    def uppercase(expr: pl.Expr) -> pl.Expr:
        return expr.cast(pl.String).str.to_uppercase()

    @staticmethod
    def remove_accents(expr: pl.Expr) -> pl.Expr:
        """Quita tildes y diéresis, y convierte ñ/Ñ en n/N."""
        return (
            expr.cast(pl.String)
            .str.normalize("NFD")
            .str.replace_all(r"\p{M}", "")
        )

    @staticmethod
    def remove_symbols(expr: pl.Expr) -> pl.Expr:
        """Elimina símbolos conservando letras Unicode, números y espacios."""
        return expr.cast(pl.String).str.replace_all(
            r"[^\p{L}\p{N}\s]", ""
        )

    @staticmethod
    def empty_to_null(expr: pl.Expr) -> pl.Expr:
        return (
            pl.when(expr == "")
            .then(pl.lit(None))
            .otherwise(expr)
        )

    def unique(self, data: Frame, column: str) -> Frame:
        """Devuelve solo la columna indicada con sus valores únicos."""
        if column not in data.collect_schema().names():
            raise ValueError(f"Columna inexistente: {column}")

        return data.select(column).unique(maintain_order=True)

    def transform(
        self,
        data: Frame,
        rules: dict[str, Sequence[Operation]],
    ) -> Frame:
        missing = set(rules) - set(data.collect_schema().names())

        if missing:
            raise ValueError(f"Columnas inexistentes: {sorted(missing)}")

        expressions = []

        for column, operations in rules.items():
            expr = pl.col(column)

            for operation in operations:
                expr = operation(expr)

            expressions.append(expr.alias(column))

        return data.with_columns(expressions)
