"""从 SQL 月度品类差评结果构造 forecast_result，供预测类决策使用。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

_TIME_COLS = ("year_month", "month", "year", "period")
_CATEGORY_COLS = ("product_category_english", "category", "product_category")
_RATE_COLS = ("bad_review_rate", "negative_rate", "rate")
_COUNT_COLS = ("bad_review_count", "bad_reviews", "negative_count")
_RECENT_MONTHS = 3
_PRIOR_MONTHS = 3
_RATE_DELTA_THRESHOLD = 0.02


def _pick_column(cols: list[str], candidates: tuple[str, ...]) -> str | None:
    lower_map = {c.lower(): c for c in cols}
    for name in candidates:
        if name in lower_map:
            return lower_map[name]
    for col in cols:
        cl = col.lower()
        for name in candidates:
            if name in cl:
                return col
    return None


def _load_trend_frames(sql_runs: list[dict[str, Any]]) -> list[pd.DataFrame]:
    frames: list[pd.DataFrame] = []
    for run in sql_runs:
        raw = str(run.get("execute_sql_json") or "").strip()
        if not raw:
            continue
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if not payload.get("ok"):
            continue
        rows = payload.get("results") or []
        if not rows and payload.get("result_csv_path"):
            rows = [payload]
        for row in rows:
            if not row.get("ok"):
                continue
            csv_path = row.get("result_csv_path")
            if not csv_path:
                continue
            path = Path(str(csv_path))
            if not path.is_file():
                continue
            try:
                df = pd.read_csv(path)
            except Exception:
                continue
            if df.empty:
                continue
            time_col = _pick_column(list(df.columns), _TIME_COLS)
            cat_col = _pick_column(list(df.columns), _CATEGORY_COLS)
            rate_col = _pick_column(list(df.columns), _RATE_COLS)
            count_col = _pick_column(list(df.columns), _COUNT_COLS)
            if not time_col or not cat_col or (not rate_col and not count_col):
                continue
            use = df[[time_col, cat_col]].copy()
            use = use.rename(columns={time_col: "year_month", cat_col: "category"})
            if rate_col:
                use["bad_review_rate"] = pd.to_numeric(df[rate_col], errors="coerce")
            else:
                use["bad_review_count"] = pd.to_numeric(df[count_col], errors="coerce")
            frames.append(use.dropna(subset=["year_month", "category"]))
    return frames


def _month_sort_key(value: str) -> tuple[int, int]:
    text = str(value).strip()
    if len(text) >= 7 and text[4] == "-":
        try:
            return int(text[:4]), int(text[5:7])
        except ValueError:
            pass
    return 0, 0


def _compute_rate_deltas(df: pd.DataFrame) -> pd.DataFrame:
    work = df.copy()
    if "bad_review_rate" not in work.columns:
        work["bad_review_rate"] = pd.NA
    work["year_month"] = work["year_month"].astype(str)
    work = work.sort_values(["category", "year_month"], key=lambda s: s.map(_month_sort_key))
    months = sorted(work["year_month"].unique(), key=_month_sort_key)
    if len(months) < _RECENT_MONTHS + _PRIOR_MONTHS:
        return pd.DataFrame()

    recent = set(months[-_RECENT_MONTHS:])
    prior = set(months[-(_RECENT_MONTHS + _PRIOR_MONTHS) : -_RECENT_MONTHS])
    rows: list[dict[str, Any]] = []
    for category, grp in work.groupby("category", observed=True):
        recent_grp = grp[grp["year_month"].isin(recent)]
        prior_grp = grp[grp["year_month"].isin(prior)]
        if recent_grp.empty or prior_grp.empty:
            continue
        recent_rate = float(recent_grp["bad_review_rate"].mean())
        prior_rate = float(prior_grp["bad_review_rate"].mean())
        if pd.isna(recent_rate) or pd.isna(prior_rate):
            recent_count = float(recent_grp.get("bad_review_count", pd.Series(dtype=float)).mean() or 0)
            prior_count = float(prior_grp.get("bad_review_count", pd.Series(dtype=float)).mean() or 0)
            delta = recent_count - prior_count
            metric = "count"
        else:
            delta = recent_rate - prior_rate
            metric = "rate"
        rows.append(
            {
                "category": category,
                "recent_value": recent_rate if metric == "rate" else recent_count,
                "prior_value": prior_rate if metric == "rate" else prior_count,
                "delta": delta,
                "metric": metric,
            }
        )
    if not rows:
        return pd.DataFrame()
    out = pd.DataFrame(rows)
    if out.iloc[0]["metric"] == "rate":
        risky = out[out["delta"] > _RATE_DELTA_THRESHOLD].sort_values("delta", ascending=False)
    else:
        risky = out[out["delta"] > 0].sort_values("delta", ascending=False)
    return risky


def _query_is_bad_review_predictive(user_query: str, intent: str) -> bool:
    q = str(user_query or "").lower()
    if intent != "predictive":
        return False
    return any(h in q for h in ("差评", "负面", "bad review", "差评率", "差评订单", "评论"))


def build_bad_review_forecast_result(
    *,
    user_query: str,
    intent: str,
    sql_runs: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    """基于按月×品类差评率/差评数，生成预测性风险 forecast_result。"""
    if not _query_is_bad_review_predictive(user_query, intent):
        return {}
    frames = _load_trend_frames(sql_runs or [])
    if not frames:
        return {}

    combined = pd.concat(frames, ignore_index=True)
    agg_spec: dict[str, tuple[str, str]] = {}
    if "bad_review_rate" in combined.columns:
        agg_spec["bad_review_rate"] = ("bad_review_rate", "mean")
    if "bad_review_count" in combined.columns:
        agg_spec["bad_review_count"] = ("bad_review_count", "sum")
    if agg_spec:
        combined = combined.groupby(
            ["year_month", "category"], as_index=False, observed=True
        ).agg(**agg_spec)
    risky = _compute_rate_deltas(combined)
    if risky.empty:
        return {
            "ok": True,
            "method": "category_bad_review_3m_compare",
            "horizon": "statistical_trend",
            "trend_direction": "flat",
            "risk_flags": [],
            "summary_text": (
                "基于各品类近3个月与此前3个月的差评率对比，"
                "未识别出超过2个百分点阈值的系统性恶化品类。"
            ),
        }

    top = risky.head(8)
    flags = [
        f"{row['category']}: 近3月差评率较此前3月上升 {row['delta'] * 100:.1f} 个百分点"
        if row["metric"] == "rate"
        else f"{row['category']}: 近3月月均差评订单较此前3月增加 {row['delta']:.0f} 单"
        for _, row in top.iterrows()
    ]
    worsening = int((risky["delta"] > _RATE_DELTA_THRESHOLD).sum()) if top.iloc[0]["metric"] == "rate" else len(top)
    return {
        "ok": True,
        "method": "category_bad_review_3m_compare",
        "horizon": "1-2 months inertia",
        "trend_direction": "up" if worsening > 0 else "flat",
        "risk_flags": flags,
        "summary_text": (
            f"基于 2016-09~2018-10 各品类按月差评数据，近3个月 vs 前3个月对比识别出 "
            f"{worsening} 个恶化风险品类；升幅前列："
            + "；".join(flags[:3])
            + "。若无干预，差评订单数惯性上行风险较高。"
        ),
    }


def try_build_gmv_forecast_result() -> dict[str, Any]:
    """基于周度 GMV 线性外推，构造标准 forecast_result。"""
    from agents.viz_agent.forecast import forecast_weekly_gmv, gmv_forecast_result_payload

    fc = forecast_weekly_gmv(horizon_weeks=6)
    return gmv_forecast_result_payload(fc)


def enrich_forecast_from_state(state: dict[str, Any]) -> dict[str, Any]:
    """若 state 尚无 forecast_result，按问题类型尝试构建。"""
    if state.get("forecast_result"):
        return {}
    built = build_bad_review_forecast_result(
        user_query=str(state.get("user_query") or ""),
        intent=str(state.get("intent") or ""),
        sql_runs=state.get("sql_runs") or [],
    )
    if built:
        return {"forecast_result": built}
    if str(state.get("intent") or "") == "predictive":
        gmv_fc = try_build_gmv_forecast_result()
        if gmv_fc:
            return {"forecast_result": gmv_fc}
    return {}
