"""EX 结果集比较：scalar / bag / ordered_topk，以及预测 SQL 与 intent 的贪心配对。"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any

DEFAULT_NUMERIC_TOL = 1e-4

REASON_PASS = ""
REASON_ROW_COUNT = "row_count"
REASON_SCHEMA_MISMATCH = "schema_mismatch"
REASON_TOO_FEW_ROWS = "too_few_rows"
REASON_UNMATCHED = "unmatched"
REASON_NO_PRED_SQL = "no_pred_sql"
REASON_UNSUPPORTED = "unsupported_compare"

# 金标列名 → 预测常见别名。用于忽略多余度量列时仍能对齐身份列。
_KEY_ALIASES: dict[str, tuple[str, ...]] = {
    "top_state_2017": ("customer_state", "top_state", "state"),
    "gmv_2017": ("total_gmv", "gmv"),
    "gmv_2017_sp": ("total_gmv", "gmv"),
    "gmv_2018": ("total_gmv", "gmv"),
    "total_gmv": ("gmv_total", "gmv"),
    "total_transactions": ("payment_transactions", "tx_count", "tx_2017"),
    "overall_on_time_rate": ("on_time_rate",),
    "on_time_rate_2017": ("on_time_rate",),
    "overall_weighted_avg_installments": (
        "avg_installments",
        "weighted_avg_installments",
    ),
    "most_popular_payment_type": ("payment_type",),
    "product_category": (
        "product_category_english",
        "product_category_name",
        "category",
    ),
    "product_category_english": ("product_category", "product_category_name"),
    "total_orders": ("order_count",),
    "tx_2017": ("total_transactions",),
    "top_category": ("product_category_english", "product_category"),
    "delivered_orders": ("order_count", "total_orders", "n_orders"),
    "avg_review_score": ("avg_score", "mean_review_score"),
    "n_states": ("state_count", "num_states"),
    "score_1_count": ("review_count", "n_reviews"),
    "avg_delivery_days": ("mean_delivery_days",),
    "avg_installments": ("weighted_avg_installments", "avg_payment_installments"),
    "avg_price": ("avg_unit_price", "mean_price"),
    "one_time_customer_share": ("one_time_share", "single_order_share"),
    "repeat_gmv_share": ("repeat_share", "repurchase_gmv_share"),
    "delivery_status": ("status", "delay_status"),
    "avg_freight_value": ("avg_freight", "mean_freight"),
    "corr_weight_freight": ("correlation", "corr"),
}


def _alias_candidates(key: str) -> tuple[str, ...]:
    k = key.lower()
    names = {k, *_KEY_ALIASES.get(k, ())}
    for canon, alts in _KEY_ALIASES.items():
        if k == canon or k in alts:
            names.add(canon)
            names.update(alts)
    return tuple(names)


def _canonical_name(name: str) -> str:
    """词序无关列名：``gmv_total`` 与 ``total_gmv`` 相同。"""
    tokens = [t for t in re.split(r"[^a-z0-9]+", str(name).lower()) if t]
    return "_".join(sorted(tokens))


def _resolve_column(key: str, name_set: set[str]) -> str | None:
    """精确名 → 词典别名 → 词序规范化。"""
    k = key.lower()
    if k in name_set:
        return k
    for alias in _alias_candidates(k):
        if alias in name_set:
            return alias
    want = _canonical_name(k)
    if not want:
        return None
    for col in name_set:
        if _canonical_name(col) == want:
            return col
    return None


@dataclass(frozen=True)
class CompareSpec:
    compare: str
    key_columns: tuple[str, ...]
    numeric_tol: float = DEFAULT_NUMERIC_TOL
    k: int | None = None


@dataclass(frozen=True)
class ResultSet:
    columns: tuple[str, ...]
    rows: tuple[dict[str, Any], ...]


def spec_from_intent(intent: dict[str, Any]) -> CompareSpec:
    compare = str(intent["compare"])
    keys = tuple(str(c) for c in intent["key_columns"])
    tol = intent.get("numeric_tol")
    numeric_tol = DEFAULT_NUMERIC_TOL if tol is None else float(tol)
    k_raw = intent.get("k")
    k = None if k_raw is None else int(k_raw)
    return CompareSpec(compare=compare, key_columns=keys, numeric_tol=numeric_tol, k=k)


def normalize_cell(value: Any) -> Any:
    """把驱动类型收成可比较的标量；NULL 保持 None。"""
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, datetime):
        return value.isoformat(sep=" ", timespec="seconds")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, (bytes, bytearray)):
        return bytes(value).decode("utf-8", errors="replace")
    if isinstance(value, float):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        return value
    return value


def values_equal(left: Any, right: Any, numeric_tol: float) -> bool:
    a = normalize_cell(left)
    b = normalize_cell(right)
    if a is None and b is None:
        return True
    if a is None or b is None:
        return False
    if isinstance(a, bool) or isinstance(b, bool):
        return a is b if (isinstance(a, bool) and isinstance(b, bool)) else False
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        fa = float(a)
        fb = float(b)
        return abs(fa - fb) <= max(numeric_tol, numeric_tol * abs(fb))
    return a == b


def tuples_equal(
    left: tuple[Any, ...], right: tuple[Any, ...], numeric_tol: float
) -> bool:
    if len(left) != len(right):
        return False
    return all(values_equal(a, b, numeric_tol) for a, b in zip(left, right))


def _lowercase_row(row: dict[str, Any]) -> dict[str, Any]:
    return {str(k).lower(): v for k, v in row.items()}


def extract_key_tuples(
    result: ResultSet, key_columns: tuple[str, ...]
) -> tuple[str, list[tuple[Any, ...]] | None]:
    """按列名、同义列名或按列顺序抽出 key 元组。失败返回 schema_mismatch。"""
    keys = tuple(k.lower() for k in key_columns)
    if not keys:
        return REASON_SCHEMA_MISMATCH, None

    col_order = tuple(str(c).lower() for c in result.columns)
    lower_rows = [_lowercase_row(r) for r in result.rows]
    name_set = set(col_order)
    for row in lower_rows:
        name_set.update(row.keys())

    resolved: list[str] = []
    for k in keys:
        hit = _resolve_column(k, name_set)
        if hit is None:
            resolved = []
            break
        resolved.append(hit)
    if len(resolved) == len(keys):
        tuples = [tuple(row.get(c) for c in resolved) for row in lower_rows]
        return REASON_PASS, tuples

    if len(col_order) == len(keys):
        tuples = [tuple(row.get(c) for c in col_order) for row in lower_rows]
        return REASON_PASS, tuples

    return REASON_SCHEMA_MISMATCH, None


def compare_result_sets(
    gold: ResultSet, pred: ResultSet, spec: CompareSpec
) -> tuple[bool, str]:
    """比较两个结果集。返回 (是否相等, 失败原因码)。"""
    if spec.compare == "scalar":
        if len(gold.rows) != 1 or len(pred.rows) != 1:
            return False, REASON_ROW_COUNT
        g_reason, g_tuples = extract_key_tuples(gold, spec.key_columns)
        if g_reason:
            return False, g_reason
        p_reason, p_tuples = extract_key_tuples(pred, spec.key_columns)
        if p_reason:
            return False, p_reason
        assert g_tuples is not None and p_tuples is not None
        if tuples_equal(g_tuples[0], p_tuples[0], spec.numeric_tol):
            return True, REASON_PASS
        return False, REASON_UNMATCHED

    if spec.compare == "bag":
        g_reason, g_tuples = extract_key_tuples(gold, spec.key_columns)
        if g_reason:
            return False, g_reason
        p_reason, p_tuples = extract_key_tuples(pred, spec.key_columns)
        if p_reason:
            return False, p_reason
        assert g_tuples is not None and p_tuples is not None
        if len(g_tuples) != len(p_tuples):
            return False, REASON_UNMATCHED
        used = [False] * len(p_tuples)
        for gt in g_tuples:
            found = False
            for i, pt in enumerate(p_tuples):
                if used[i]:
                    continue
                if tuples_equal(gt, pt, spec.numeric_tol):
                    used[i] = True
                    found = True
                    break
            if not found:
                return False, REASON_UNMATCHED
        return True, REASON_PASS

    if spec.compare == "ordered_topk":
        if spec.k is None or spec.k < 1:
            return False, REASON_UNSUPPORTED
        if len(pred.rows) < spec.k:
            return False, REASON_TOO_FEW_ROWS
        if len(gold.rows) < spec.k:
            return False, REASON_TOO_FEW_ROWS
        gold_cut = ResultSet(columns=gold.columns, rows=gold.rows[: spec.k])
        pred_cut = ResultSet(columns=pred.columns, rows=pred.rows[: spec.k])
        g_reason, g_tuples = extract_key_tuples(gold_cut, spec.key_columns)
        if g_reason:
            return False, g_reason
        p_reason, p_tuples = extract_key_tuples(pred_cut, spec.key_columns)
        if p_reason:
            return False, p_reason
        assert g_tuples is not None and p_tuples is not None
        for gt, pt in zip(g_tuples, p_tuples):
            if not tuples_equal(gt, pt, spec.numeric_tol):
                return False, REASON_UNMATCHED
        return True, REASON_PASS

    return False, REASON_UNSUPPORTED


def match_intents(
    intents: list[dict[str, Any]],
    gold_results: list[ResultSet],
    pred_ok: list[bool],
    pred_results: list[ResultSet],
    *,
    pred_sql_count: int,
) -> list[dict[str, Any]]:
    """按金标 intent 顺序贪心配对预测结果。每个预测最多占用一次。"""
    if len(intents) != len(gold_results):
        raise ValueError("intents 与 gold_results 数量不一致")
    if len(pred_ok) != len(pred_results):
        raise ValueError("pred_ok 与 pred_results 数量不一致")

    used = [False] * len(pred_results)
    out: list[dict[str, Any]] = []

    if pred_sql_count <= 0:
        for intent in intents:
            out.append(
                {
                    "id": intent.get("id"),
                    "pass": False,
                    "reason": REASON_NO_PRED_SQL,
                    "pred_index": None,
                }
            )
        return out

    for intent, gold in zip(intents, gold_results):
        spec = spec_from_intent(intent)
        matched_index: int | None = None
        fail_reasons: list[str] = []
        for i, (ok, pred) in enumerate(zip(pred_ok, pred_results)):
            if used[i] or not ok:
                continue
            equal, reason = compare_result_sets(gold, pred, spec)
            if equal:
                matched_index = i
                used[i] = True
                fail_reasons = []
                break
            fail_reasons.append(reason)
        if matched_index is None and spec.compare == "bag":
            merged_idx, merge_reason = _try_merge_bag(
                gold, spec, pred_ok, pred_results, used
            )
            if merged_idx is not None:
                matched_index = merged_idx
                fail_reasons = []
            elif merge_reason:
                fail_reasons.append(merge_reason)
        if matched_index is not None:
            last_reason = REASON_PASS
        elif not fail_reasons:
            last_reason = REASON_UNMATCHED
        elif all(r == REASON_SCHEMA_MISMATCH for r in fail_reasons):
            last_reason = REASON_SCHEMA_MISMATCH
        elif all(r == REASON_TOO_FEW_ROWS for r in fail_reasons):
            last_reason = REASON_TOO_FEW_ROWS
        elif all(r == REASON_ROW_COUNT for r in fail_reasons):
            last_reason = REASON_ROW_COUNT
        else:
            last_reason = REASON_UNMATCHED
        out.append(
            {
                "id": intent.get("id"),
                "pass": matched_index is not None,
                "reason": last_reason,
                "pred_index": matched_index,
            }
        )
    return out


def _try_merge_bag(
    gold: ResultSet,
    spec: CompareSpec,
    pred_ok: list[bool],
    pred_results: list[ResultSet],
    used: list[bool],
) -> tuple[int | None, str]:
    """同一 bag intent 允许把多条预测 SQL 的行并起来再比。"""
    mergeable = [
        i
        for i, (ok, _pred) in enumerate(zip(pred_ok, pred_results))
        if ok and not used[i]
    ]
    if len(mergeable) < 2:
        return None, ""
    tuples: list[tuple[Any, ...]] = []
    for i in mergeable:
        reason, extracted = extract_key_tuples(pred_results[i], spec.key_columns)
        if reason or extracted is None:
            return None, reason or REASON_SCHEMA_MISMATCH
        tuples.extend(extracted)
    merged = ResultSet(
        columns=spec.key_columns,
        rows=tuple(
            {spec.key_columns[j]: cell for j, cell in enumerate(t)} for t in tuples
        ),
    )
    equal, reason = compare_result_sets(gold, merged, spec)
    if not equal:
        return None, reason
    for i in mergeable:
        used[i] = True
    return mergeable[0], REASON_PASS
