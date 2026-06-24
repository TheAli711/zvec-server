"""Translate our :class:`QuerySpec` models into native ``zvec.Query`` objects."""

from __future__ import annotations

import zvec

from zvec_server.models.search import QuerySpec

__all__ = ["build_queries"]


def _build_query_param(
    params: dict[str, object] | None,
) -> zvec.HnswQueryParam | None:
    """Best-effort translation of query params into a Zvec query-param object.

    Currently recognises ``{"ef": int}`` for HNSW. Unknown shapes yield ``None``
    so the engine uses its defaults.
    """
    if not params:
        return None
    ef = params.get("ef")
    if isinstance(ef, int) and not isinstance(ef, bool):
        return zvec.HnswQueryParam(ef=ef)
    return None


def _build_query(spec: QuerySpec) -> zvec.Query:
    """Build a single ``zvec.Query`` from a query spec (vector or id)."""
    param = _build_query_param(spec.params)
    if spec.vector is not None:
        return zvec.Query(field_name=spec.field, vector=spec.vector, param=param)
    return zvec.Query(field_name=spec.field, id=spec.id, param=param)


def build_queries(specs: list[QuerySpec]) -> list[zvec.Query]:
    """Convert a list of :class:`QuerySpec` into native ``zvec.Query`` objects."""
    return [_build_query(spec) for spec in specs]
