#!/usr/bin/env python3
"""SQL Agent Execution Accuracy 评测。

对金标 JSON 逐题：执行 gold_sql → 跑流水线抽出 query_sqls → 再执行预测 SQL →
按 intent 贪心配对，输出题级 PASS/FAIL 与 EX。

用法（仓库根）：
  python agents/sql_agent/test/eval_ex.py --suite smoke
  python agents/sql_agent/test/eval_ex.py --suite capability --validate-gold
  python agents/sql_agent/test/eval_ex.py --gold agents/sql_agent/test/gold/phase1.json
  python agents/sql_agent/test/eval_ex.py --suite assignment --repeat 3
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agents.sql_agent.pipeline import run_sql_pipeline_with_feedback
from agents.sql_agent.test.eval_db import QueryResult, execute_eval_sql
from agents.sql_agent.test.ex_compare import (
    ResultSet,
    match_intents,
    spec_from_intent,
)

KNOWN_VIEWS = {
    "mv_monthly_sales",
    "mv_state_sales",
    "mv_category_sales",
    "mv_delivery_perf",
    "mv_seller_perf",
    "mv_payment_dist",
}
VIEW_RE = re.compile(r"(?:FROM|JOIN)\s+`?(mv_[a-z_]+)`?", re.IGNORECASE)
GOLD_DIR = Path(__file__).resolve().parent / "gold"
DEFAULT_GOLD = GOLD_DIR / "phase1.json"
OUT_DIR = Path(__file__).resolve().parent / "eval_outputs"
SUITES: dict[str, list[str]] = {
    "smoke": ["smoke.json"],
    "general": ["general.json"],
    "complex": ["complex.json"],
    "extreme": ["extreme.json"],
    "capability": ["smoke.json", "general.json", "complex.json", "extreme.json"],
    "phase1": ["phase1.json"],
    "phase2": ["phase2.json"],
    "assignment": ["phase1.json", "phase2.json"],
}


def resolve_gold_paths(
    gold_paths: list[str] | None, suites: list[str] | None
) -> list[Path]:
    """--suite 与 --gold 可并用；都缺省时用 phase1.json。"""
    files: list[Path] = []
    for name in suites or []:
        mapped = SUITES.get(name)
        if not mapped:
            known = ", ".join(sorted(SUITES))
            raise ValueError(f"未知 suite={name}，可选：{known}")
        files.extend(GOLD_DIR / fname for fname in mapped)
    for raw in gold_paths or []:
        files.append(Path(raw))
    if not files:
        files = [DEFAULT_GOLD]
    return files


def load_gold_files(paths: list[Path]) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    seen: set[str] = set()
    for path in paths:
        data = json.loads(path.read_text(encoding="utf-8"))
        chunk = data.get("cases")
        if not isinstance(chunk, list):
            raise ValueError(f"{path} 缺少 cases 数组")
        for case in chunk:
            cid = str(case.get("id") or "")
            if not cid:
                raise ValueError(f"{path} 中存在无 id 的 case")
            if cid in seen:
                raise ValueError(f"重复 case id: {cid}")
            seen.add(cid)
            _validate_case_shape(case, source=str(path))
            cases.append(case)
    return cases


def _validate_case_shape(case: dict[str, Any], *, source: str) -> None:
    bucket = str(case.get("bucket") or "")
    intents = case.get("intents")
    if not isinstance(intents, list):
        raise ValueError(f"{source} {case.get('id')}: intents 必须是数组")
    if bucket != "oos" and not intents:
        raise ValueError(f"{source} {case.get('id')}: 非 OOS 题必须有 intents")
    if bucket == "oos":
        return
    if not str(case.get("question") or "").strip():
        raise ValueError(f"{source} {case.get('id')}: question 为空")
    for intent in intents:
        spec = spec_from_intent(intent)
        if spec.compare == "ordered_topk" and (spec.k is None or spec.k < 1):
            raise ValueError(f"{source} {case.get('id')}/{intent.get('id')}: ordered_topk 需要 k")
        if not str(intent.get("gold_sql") or "").strip():
            raise ValueError(f"{source} {case.get('id')}/{intent.get('id')}: gold_sql 为空")


def parse_query_sqls(generate_sql_json: str) -> list[str]:
    try:
        data = json.loads(generate_sql_json)
    except (json.JSONDecodeError, TypeError):
        return []
    if not isinstance(data, dict):
        return []
    sqls = data.get("query_sqls") or []
    return [str(s) for s in sqls if str(s).strip()]


def views_in_sqls(sqls: list[str]) -> list[str]:
    found: set[str] = set()
    for sql in sqls:
        for m in VIEW_RE.findall(sql):
            name = m.lower()
            if name in KNOWN_VIEWS:
                found.add(name)
    return sorted(found)


def routing_label(expected: list[str], used: list[str]) -> str:
    exp = set(expected)
    got = set(used)
    if exp == got:
        return "exact"
    if not exp and got:
        return "extra"
    if exp and not got:
        return "missing"
    extra = bool(got - exp)
    missing = bool(exp - got)
    if extra and not missing:
        return "extra"
    if missing and not extra:
        return "missing"
    return "none"


def filter_literals_ok(sqls: list[str], literals: list[str]) -> bool:
    if not literals:
        return True
    blob = " ".join(sqls).lower()
    return all(str(lit).lower() in blob for lit in literals)


def execute_sql_ok(execute_sql_json: str) -> tuple[bool, int]:
    try:
        data = json.loads(execute_sql_json)
    except (json.JSONDecodeError, TypeError):
        return False, 0
    if not isinstance(data, dict) or data.get("ok") is not True:
        return False, 0
    n = 0
    for item in data.get("results") or []:
        if not isinstance(item, dict):
            continue
        n += int(item.get("row_count_returned") or 0)
    return True, n


def to_result_set(qr: QueryResult) -> ResultSet:
    return ResultSet(
        columns=tuple(qr.columns),
        rows=tuple(dict(r) for r in qr.rows),
    )


def is_oos(case: dict[str, Any]) -> bool:
    return str(case.get("bucket") or "") == "oos"


def execute_gold_intents(case: dict[str, Any]) -> tuple[str | None, list[QueryResult]]:
    """执行金标 SQL 并检查行数形态。失败返回 infra 原因。"""
    results: list[QueryResult] = []
    for intent in case.get("intents") or []:
        qr = execute_eval_sql(str(intent["gold_sql"]))
        if not qr.ok:
            return f"gold {intent.get('id')}: {qr.error}", []
        spec = spec_from_intent(intent)
        if spec.compare == "scalar" and len(qr.rows) != 1:
            return (
                f"gold {intent.get('id')}: scalar 需要恰好 1 行，实际 {len(qr.rows)}",
                [],
            )
        if spec.compare == "ordered_topk":
            k = spec.k or 0
            if len(qr.rows) < k:
                return (
                    f"gold {intent.get('id')}: ordered_topk 需要 ≥{k} 行，实际 {len(qr.rows)}",
                    [],
                )
        results.append(qr)
    return None, results


def score_prediction(
    case: dict[str, Any],
    pred_sqls: list[str],
    gold_results: list[QueryResult],
) -> dict[str, Any]:
    intents = list(case.get("intents") or [])
    pred_qrs = [execute_eval_sql(sql) for sql in pred_sqls]
    pred_ok = [qr.ok for qr in pred_qrs]
    pred_sets = [to_result_set(qr) for qr in pred_qrs]
    gold_sets = [to_result_set(qr) for qr in gold_results]
    intent_rows = match_intents(
        intents,
        gold_sets,
        pred_ok,
        pred_sets,
        pred_sql_count=len(pred_sqls),
    )
    question_pass = bool(intents) and all(row["pass"] for row in intent_rows)
    used_views = views_in_sqls(pred_sqls)
    expected_views = [str(v) for v in (case.get("expected_views") or [])]
    literals = [str(x) for x in (case.get("required_literals") or [])]
    return {
        "question_pass": question_pass,
        "intents": intent_rows,
        "pred_sqls": pred_sqls,
        "pred_exec_ok": pred_ok,
        "pred_errors": [qr.error for qr in pred_qrs],
        "used_views": used_views,
        "routing": routing_label(expected_views, used_views),
        "filter_ok": filter_literals_ok(pred_sqls, literals),
        "has_required_literals": bool(literals),
    }


def evaluate_case(
    case: dict[str, Any],
    *,
    pipeline_fn: Callable[[str], dict[str, Any]] | None,
    validate_gold_only: bool = False,
) -> dict[str, Any]:
    base = {
        "id": case.get("id"),
        "question": case.get("question"),
        "bucket": case.get("bucket"),
        "split": case.get("split"),
        "oos": is_oos(case),
        "infra_error": None,
        "ex_eligible": (not is_oos(case)),
        "question_pass": False,
        "validity": False,
        "elapsed_s": None,
    }
    gold_err, gold_results = execute_gold_intents(case)
    if gold_err:
        base["infra_error"] = gold_err
        base["ex_eligible"] = False
        return base
    if validate_gold_only:
        base["gold_ok"] = True
        base["gold_row_counts"] = [len(qr.rows) for qr in gold_results]
        base["ex_eligible"] = False
        return base
    if pipeline_fn is None:
        base["infra_error"] = "未提供 pipeline_fn"
        base["ex_eligible"] = False
        return base

    t0 = time.perf_counter()
    pipe = pipeline_fn(str(case["question"]))
    elapsed = round(time.perf_counter() - t0, 2)
    pred_sqls = parse_query_sqls(str(pipe.get("generate_sql_json") or ""))
    validity, row_count_returned = execute_sql_ok(str(pipe.get("execute_sql_json") or ""))
    scored = score_prediction(case, pred_sqls, gold_results)
    out = {
        **base,
        "elapsed_s": elapsed,
        "validity": validity,
        "pipeline_row_count_returned": row_count_returned,
        "rewrite_attempts": pipe.get("rewrite_attempts"),
        "generate_sql_attempts": pipe.get("generate_sql_attempts"),
        **scored,
    }
    if is_oos(case):
        out["question_pass"] = False
        out["ex_eligible"] = False
        out["oos_has_sql"] = bool(pred_sqls)
        out["oos_false_view"] = bool(scored["used_views"])
    return out


def summarize_rows(
    rows: list[dict[str, Any]], *, validate_gold_only: bool = False
) -> dict[str, Any]:
    infra = [r for r in rows if r.get("infra_error")]
    oos = [r for r in rows if r.get("oos") and not r.get("infra_error")]
    if validate_gold_only:
        by_split: dict[str, dict[str, Any]] = {}
        for split in sorted({str(r.get("split") or "") for r in rows if r.get("split")}):
            chunk = [r for r in rows if str(r.get("split") or "") == split]
            by_split[split] = {
                "n": len(chunk),
                "n_infra_error": sum(1 for r in chunk if r.get("infra_error")),
            }
        return {
            "n": len(rows),
            "n_infra_error": len(infra),
            "n_oos": len(oos),
            "gold_ok": len(infra) == 0,
            "by_split": by_split,
            "infra_errors": [
                {"id": r.get("id"), "error": r.get("infra_error")} for r in infra
            ],
        }
    eligible = [r for r in rows if r.get("ex_eligible")]
    q_pass = sum(1 for r in eligible if r.get("question_pass"))
    intent_total = 0
    intent_pass = 0
    for r in eligible:
        for intent in r.get("intents") or []:
            intent_total += 1
            if intent.get("pass"):
                intent_pass += 1
    validity_n = [r for r in rows if not r.get("infra_error") and not r.get("oos")]
    routing_exact = sum(1 for r in eligible if r.get("routing") == "exact")
    filter_cases = [r for r in eligible if r.get("has_required_literals")]
    by_split: dict[str, dict[str, Any]] = {}
    for split in sorted({str(r.get("split") or "") for r in eligible if r.get("split")}):
        chunk = [r for r in eligible if str(r.get("split") or "") == split]
        if not chunk:
            continue
        c_pass = sum(1 for r in chunk if r.get("question_pass"))
        i_total = 0
        i_pass = 0
        for r in chunk:
            for intent in r.get("intents") or []:
                i_total += 1
                if intent.get("pass"):
                    i_pass += 1
        by_split[split] = {
            "n_ex": len(chunk),
            "question_ex": round(c_pass / len(chunk), 4),
            "intent_micro_ex": round(i_pass / i_total, 4) if i_total else None,
        }
    return {
        "n": len(rows),
        "n_infra_error": len(infra),
        "n_oos": len(oos),
        "n_ex": len(eligible),
        "question_ex": round(q_pass / len(eligible), 4) if eligible else None,
        "intent_micro_ex": round(intent_pass / intent_total, 4) if intent_total else None,
        "by_split": by_split,
        "validity": round(
            sum(1 for r in validity_n if r.get("validity")) / len(validity_n), 4
        )
        if validity_n
        else None,
        "routing_exact": round(routing_exact / len(eligible), 4) if eligible else None,
        "filter_ok": round(
            sum(1 for r in filter_cases if r.get("filter_ok")) / len(filter_cases), 4
        )
        if filter_cases
        else None,
        "infra_errors": [
            {"id": r.get("id"), "error": r.get("infra_error")} for r in infra
        ],
    }


def _print_case_line(row: dict[str, Any]) -> None:
    cid = row.get("id")
    if row.get("infra_error"):
        print(f"  {cid} INFRA {row['infra_error']}", flush=True)
        return
    if row.get("gold_ok"):
        print(f"  {cid} GOLD_OK rows={row.get('gold_row_counts')}", flush=True)
        return
    if row.get("oos"):
        print(
            f"  {cid} OOS sql={row.get('oos_has_sql')} views={row.get('used_views')}",
            flush=True,
        )
        return
    mark = "PASS" if row.get("question_pass") else "FAIL"
    reasons = [
        f"{i.get('id')}:{i.get('reason') or 'ok'}" for i in (row.get("intents") or [])
    ]
    print(
        f"  {cid} {mark} routing={row.get('routing')} validity={row.get('validity')} "
        f"{row.get('elapsed_s')}s intents={reasons}",
        flush=True,
    )


def run_once(
    cases: list[dict[str, Any]],
    *,
    pipeline_fn: Callable[[str], dict[str, Any]] | None,
    validate_gold_only: bool,
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for i, case in enumerate(cases, start=1):
        print(f"[{i}/{len(cases)}] {case.get('id')} {case.get('question')}", flush=True)
        row = evaluate_case(
            case, pipeline_fn=pipeline_fn, validate_gold_only=validate_gold_only
        )
        _print_case_line(row)
        rows.append(row)
    summary = summarize_rows(rows, validate_gold_only=validate_gold_only)
    return {"summary": summary, "cases": rows}


def _stability(run_summaries: list[dict[str, Any]], run_rows: list[list[dict[str, Any]]]) -> dict[str, Any]:
    ex_vals = [
        s["question_ex"] for s in run_summaries if s.get("question_ex") is not None
    ]
    ids = [r.get("id") for r in run_rows[0] if r.get("ex_eligible")]
    always = 0
    denom = 0
    for cid in ids:
        flags: list[bool] = []
        skip = False
        for rows in run_rows:
            hit = next((r for r in rows if r.get("id") == cid), None)
            if hit is None or hit.get("infra_error"):
                skip = True
                break
            flags.append(bool(hit.get("question_pass")))
        if skip or not flags:
            continue
        denom += 1
        if all(flags):
            always += 1
    return {
        "question_ex_mean": round(sum(ex_vals) / len(ex_vals), 4) if ex_vals else None,
        "question_ex_min": min(ex_vals) if ex_vals else None,
        "question_ex_max": max(ex_vals) if ex_vals else None,
        "always_pass_rate": round(always / denom, 4) if denom else None,
        "always_pass_n": always,
        "always_pass_denom": denom,
    }


def _default_pipeline(question: str) -> dict[str, Any]:
    os.environ.setdefault("AGENTIC_BI_SQL_CSV_DIR", str(OUT_DIR / "ex_csv"))
    return run_sql_pipeline_with_feedback(question)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="SQL Agent EX 评测")
    parser.add_argument(
        "--gold",
        action="append",
        dest="gold_paths",
        default=None,
        help="金标 JSON，可重复",
    )
    parser.add_argument(
        "--suite",
        action="append",
        dest="suites",
        choices=sorted(SUITES),
        default=None,
        help="预置套件：smoke/general/complex/extreme/capability/phase1/phase2/assignment",
    )
    parser.add_argument("--repeat", type=int, default=1, help="独立复跑次数，默认 1")
    parser.add_argument(
        "--validate-gold",
        action="store_true",
        help="只执行金标 SQL 检查形态，不调流水线",
    )
    parser.add_argument("--output", type=str, default="", help="结果 JSON 路径")
    args = parser.parse_args(argv)

    gold_paths = resolve_gold_paths(args.gold_paths, args.suites)
    cases = load_gold_files(gold_paths)
    repeat = max(1, int(args.repeat))
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    pipeline_fn: Callable[[str], dict[str, Any]] | None
    pipeline_fn = None if args.validate_gold else _default_pipeline

    print(
        f"题目数={len(cases)} gold={[str(p) for p in gold_paths]} "
        f"repeat={repeat} validate_gold={args.validate_gold}",
        flush=True,
    )

    if args.validate_gold or repeat == 1:
        payload = run_once(
            cases, pipeline_fn=pipeline_fn, validate_gold_only=args.validate_gold
        )
        default_name = "gold_validate.json" if args.validate_gold else "ex_eval.json"
        out_path = Path(args.output) if args.output else OUT_DIR / default_name
        out_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        print("\n===== 汇总 =====", flush=True)
        print(json.dumps(payload["summary"], ensure_ascii=False, indent=2), flush=True)
        print(f"明细: {out_path}", flush=True)
        if args.validate_gold:
            return 0 if payload["summary"].get("n_infra_error", 1) == 0 else 1
        return 0

    runs = []
    run_rows: list[list[dict[str, Any]]] = []
    for n in range(1, repeat + 1):
        print(f"\n======== repeat {n}/{repeat} ========", flush=True)
        payload = run_once(
            cases, pipeline_fn=pipeline_fn, validate_gold_only=False
        )
        runs.append(payload["summary"])
        run_rows.append(payload["cases"])

    report = {
        "repeat": repeat,
        "gold": [str(p) for p in gold_paths],
        "runs": runs,
        "stability": _stability(runs, run_rows),
        "cases": [
            {"repeat_index": i + 1, "cases": rows} for i, rows in enumerate(run_rows)
        ],
    }
    out_path = Path(args.output) if args.output else OUT_DIR / "ex_stability.json"
    out_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    print("\n===== 稳定性 =====", flush=True)
    print(json.dumps(report["stability"], ensure_ascii=False, indent=2), flush=True)
    print(f"明细: {out_path}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
