from __future__ import annotations

from typing import Any, Dict, List, Optional, Union
from qdrant_client.http import models

from .logger import get_colorlogger
logger = get_colorlogger(__name__)


Spec = Dict[str, Any]


def _as_list(x: Any) -> List[Any]:
    if x is None:
        return []
    if isinstance(x, list):
        return x
    return [x]


def _parse_range_value(value: Any) -> Dict[str, Any]:
    """
    Accepts:
      - {"gte": ..., "lte": ...}
      - ["start", "end"] / ("start", "end")
      - "start, end"  (string)
    Returns dict with keys: gte, gt, lte, lt (subset)
    """
    if isinstance(value, dict):
        return value

    if isinstance(value, (list, tuple)) and len(value) == 2:
        return {"gte": value[0], "lte": value[1]}

    if isinstance(value, str) and "," in value:
        a, b = [p.strip() for p in value.split(",", 1)]
        return {"gte": a, "lte": b}

    logger.error(f"Unsupported range value format: {value!r}")
    raise ValueError(f"Unsupported range value format: {value!r}")


def _field_condition_from_atomic(spec: Spec) -> Union[models.FieldCondition, models.HasIdCondition]:
    """
    Build a single Qdrant condition from one atomic spec.
    """
    key = spec.get("key")
    dtype = (spec.get("dtype") or "string").lower()
    op = (spec.get("op") or "equals").lower()
    value = spec.get("value", None)

    if not key and op != "has_id":
        logger.error(f"Missing 'key' in spec: {spec}")
        raise ValueError(f"Missing 'key' in spec: {spec}")

    # Special: filter by point ids (Qdrant IDs), not payload field
    if op == "has_id":
        ids = _as_list(value)
        return models.HasIdCondition(has_id=ids)

    # Common string exact match ops (keyword-like fields)
    if op in {"equals", "eq"}:
        return models.FieldCondition(key=key, match=models.MatchValue(value=value))

    if op in {"in"}:
        # value: list
        return models.FieldCondition(key=key, match=models.MatchAny(any=_as_list(value)))

    if op in {"not_in"}:
        return models.FieldCondition(key=key, match=models.MatchExcept(except_=_as_list(value)))

    # Text search (requires text index for best performance; still works otherwise)
    if op in {"contains", "text"}:
        # token-based match; for substring-ish search use text index
        return models.FieldCondition(key=key, match=models.MatchText(text=str(value)))

    if op in {"phrase"}:
        return models.FieldCondition(key=key, match=models.MatchPhrase(phrase=str(value)))

    if op in {"prefix"}:
        # Qdrant supports MatchText; prefix semantics depend on tokenizer/index config.
        # Many log use-cases are better handled by storing normalized keyword field(s).
        return models.FieldCondition(key=key, match=models.MatchText(text=str(value)))

    # Existence / null / empty checks
    if op in {"exists", "has_field"}:
        # "is_null=False" matches when field is present & not null
        return models.FieldCondition(key=key, is_null=False)

    if op in {"is_null"}:
        return models.FieldCondition(key=key, is_null=True)

    if op in {"is_empty"}:
        return models.FieldCondition(key=key, is_empty=True)

    # Numeric / datetime ranges
    if op in {"gt", "gte", "lt", "lte", "between", "range"}:
        r = _parse_range_value(value) if op in {"between", "range"} else {op: value}

        if dtype in {"datetime", "date", "timestamp"}:
            # DatetimeRange expects RFC3339 strings, e.g. "2025-12-08T19:07:34Z"
            return models.FieldCondition(
                key=key,
                range=models.DatetimeRange(
                    gt=r.get("gt"),
                    gte=r.get("gte"),
                    lt=r.get("lt"),
                    lte=r.get("lte"),
                ),
            )
        else:
            # int/float
            return models.FieldCondition(
                key=key,
                range=models.Range(
                    gt=r.get("gt"),
                    gte=r.get("gte"),
                    lt=r.get("lt"),
                    lte=r.get("lte"),
                ),
            )

    logger.error(f"Unsupported op={op!r} for spec: {spec}")
    raise ValueError(f"Unsupported op={op!r} for spec: {spec}")


def _build_filter_from_expr(expr: Spec) -> models.Filter:
    """
    expr can be:
      - atomic: {key,dtype,op,value}
      - logical: {"logic":"and|or|not", "clauses":[expr, expr, ...]}
    """
    logic = expr.get("logic")
    if not logic:
        # atomic -> filter with a single must condition
        cond = _field_condition_from_atomic(expr)
        return models.Filter(must=[cond])

    logic = logic.lower()
    clauses = expr.get("clauses", [])
    if not isinstance(clauses, list) or not clauses:
        logger.error(f"Logical expr must have non-empty list 'clauses': {expr}")
        raise ValueError(f"Logical expr must have non-empty list 'clauses': {expr}")

    if logic == "and":
        # Merge as must
        must_conds = []
        for c in clauses:
            if c.get("logic"):
                # nested: embed as Filter in must via FilterCondition
                must_conds.append(models.FilterCondition(filter=_build_filter_from_expr(c)))
            else:
                must_conds.append(_field_condition_from_atomic(c))
        return models.Filter(must=must_conds)

    if logic == "or":
        should_conds = []
        for c in clauses:
            if c.get("logic"):
                should_conds.append(models.FilterCondition(filter=_build_filter_from_expr(c)))
            else:
                should_conds.append(_field_condition_from_atomic(c))
        return models.Filter(should=should_conds, min_should=models.MinShould(min_count=1))

    if logic == "not":
        # NOT of a single clause or many clauses
        must_not_conds = []
        for c in clauses:
            if c.get("logic"):
                must_not_conds.append(models.FilterCondition(filter=_build_filter_from_expr(c)))
            else:
                must_not_conds.append(_field_condition_from_atomic(c))
        return models.Filter(must_not=must_not_conds)

    logger.error(f"Unsupported logic={logic!r} in expr: {expr}")
    raise ValueError(f"Unsupported logic={logic!r} in expr: {expr}")


def adapter_specs_to_filters(
    specs: List[Spec],
    *,
    mode: str = "and",
) -> List[models.Filter]:
    """
    Take a list of atomic specs OR logical exprs and return a list of Qdrant Filters.

    Common usage:
      - mode="and": single Filter with must=[...]
      - mode="or":  single Filter with should=[...]
      - or pass a list of logical exprs and get one Filter per expr

    Returns: models.Filter
    """
    mode = mode.lower()

    # If user already provided logical expressions, compile each into a Filter
    if any("logic" in s for s in specs):
        filters = [_build_filter_from_expr(s) for s in specs]
        logger.info(f"Successfully built {len(filters)} filters from logical expressions.")
        return filters

    # Otherwise treat as atomic list and wrap according to mode
    conds = [_field_condition_from_atomic(s) for s in specs]
    if mode == "and":
        filter_ = models.Filter(must=conds)
        logger.info("Successfully built AND filter from atomic specs.")
        return filter_
    if mode == "or":
        logger.error("Mode 'or' is not implemented.")
        raise NotImplementedError
    logger.error(f"Unsupported mode={mode!r}. Use 'and' or 'or'.")
    raise ValueError(f"Unsupported mode={mode!r}. Use 'and' or 'or'.")
