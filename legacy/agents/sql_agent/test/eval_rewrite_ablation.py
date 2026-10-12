#!/usr/bin/env python3
"""对照：有 rewrite 的完整流水线 vs 跳过 rewrite。主指标为 EX，不是视图点名。

用法（仓库根）：
  python agents/sql_agent/test/eval_rewrite_ablation.py
  python agents/sql_agent/test/eval_rewrite_ablation.py --suite smoke
  python agents/sql_agent/test/eval_rewrite_ablation.py --gold agents/sql_agent/test/gold/phase1.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from langchain_core.messages import HumanMessage, SystemMessage

from agents.common.llm import get_structured_llm, invoke_structured
from agents.common.paths import load_config_text
from agents.common.prompts import compose_system_prompt_parts
from agents.sql_agent.pipeline import (
    _parse_check_syntax_ok,
    _run_retry_loop,
    run_sql_pipeline_with_feedback,
)
from agents.sql_agent.tools.check_sql import build_check_sql_tool
from agents.sql_agent.tools.execute_sql import build_execute_sql_tool
from agents.sql_agent.tools.generate_sql import GenerateSqlOutput
from agents.sql_agent.test.eval_ex import (
    execute_gold_intents,
    execute_sql_ok,
    is_oos,
    load_gold_files,
    parse_query_sqls,
    resolve_gold_paths,
    score_prediction,
    SUITES,
)

OUT_DIR = Path(__file__).resolve().parent / "eval_outputs"


class DirectGenerateTool:
    """无 rewrite：模型直接看用户原问，仍可自行选视图。"""

    def __init__(self, model: Any) -> None:
        self.model = model

    def invoke(self, payload: dict[str, Any]) -> str:
        query = str(payload.get("rewrite_json") or payload.get("query") or "")
        correction_context = str(payload.get("correction_context") or "").strip()
        system_prompt = compose_system_prompt_parts(
            "# Agent 背景规则\n\n" + load_config_text("sql_agent", "system_core.md"),
            "# 数据库表结构与视图字典\n\n"
            + load_config_text("sql_agent", "schema_dictionary.md"),
            "# SQL 生成规则\n\n" + load_config_text("sql_agent", "generate_sql_tool.md"),
        )
        human = (
            "没有上游 rewrite JSON。下面是用户原问，请自行拆分子问题、"
            "判断是否命中预聚合视图（命中则优先用视图，否则原始表），并生成 query_sqls。\n\n"
            f"{query}"
        )
        if correction_context:
            human += (
                "\n\n## 上一次校验或执行的纠错上下文：\n\n" + correction_context
            )
        messages = [SystemMessage(content=system_prompt), HumanMessage(content=human)]
        resp = invoke_structured(GenerateSqlOutput, messages, model=self.model)
        if not isinstance(resp, GenerateSqlOutput):
            resp = GenerateSqlOutput.model_validate(resp)
        return resp.model_dump_json(
            indent=2, ensure_ascii=False, exclude_none=True, exclude_defaults=True
        )


def run_with_rewrite(query: str, model: Any) -> dict[str, Any]:
    t0 = time.perf_counter()
    out = run_sql_pipeline_with_feedback(query, model=model)
    return {
        "arm": "with_rewrite",
        "rewrite_json": out.get("rewrite_json") or "",
        "generate_sql_json": out.get("generate_sql_json") or "",
        "check_sql_json": out.get("check_sql_json") or "",
        "execute_sql_json": out.get("execute_sql_json") or "",
        "generate_attempts": out.get("generate_sql_attempts") or 0,
        "elapsed_s": round(time.perf_counter() - t0, 2),
    }


def run_without_rewrite(query: str, model: Any) -> dict[str, Any]:
    generate_tool = DirectGenerateTool(model)
    check_tool = build_check_sql_tool()
    execute_tool = build_execute_sql_tool()
    t0 = time.perf_counter()
    sql_json, check_json, exec_json, attempts = _run_retry_loop(
        query,
        generate_tool=generate_tool,
        check_tool=check_tool,
        execute_tool=execute_tool,
        emit=None,
    )
    return {
        "arm": "without_rewrite",
        "rewrite_json": "",
        "generate_sql_json": sql_json,
        "check_sql_json": check_json,
        "execute_sql_json": exec_json,
        "generate_attempts": attempts,
        "elapsed_s": round(time.perf_counter() - t0, 2),
    }


def _score_arm(
    case: dict[str, Any],
    raw: dict[str, Any],
    gold_results: list[Any],
) -> dict[str, Any]:
    sqls = parse_query_sqls(str(raw.get("generate_sql_json") or ""))
    scored = score_prediction(case, sqls, gold_results)
    validity, row_count_returned = execute_sql_ok(str(raw.get("execute_sql_json") or ""))
    check_ok, brief = _parse_check_syntax_ok(str(raw.get("check_sql_json") or ""))
    intent_pass = sum(1 for i in scored["intents"] if i.get("pass"))
    intent_n = len(scored["intents"])
    return {
        "arm": raw["arm"],
        "question_pass": scored["question_pass"],
        "intent_pass": intent_pass,
        "intent_n": intent_n,
        "intents": scored["intents"],
        "validity": validity,
        "nonempty": validity and row_count_returned > 0,
        "row_count_returned": row_count_returned,
        "check_ok": check_ok,
        "check_brief": brief,
        "generate_attempts": raw["generate_attempts"],
        "elapsed_s": raw["elapsed_s"],
        "used_views": scored["used_views"],
        "routing": scored["routing"],
        "filter_ok": scored["filter_ok"],
        "pred_sqls": sqls,
    }


def _arm_metrics(rows: list[dict[str, Any]], arm: str) -> dict[str, Any]:
    eligible = [
        r
        for r in rows
        if not r.get("infra_error") and r.get(arm) and not r.get("oos")
    ]
    if not eligible:
        return {
            "question_ex": None,
            "intent_micro_ex": None,
            "validity": None,
            "routing_exact": None,
            "mean_generate_attempts": None,
            "mean_elapsed_s": None,
        }
    q_pass = sum(1 for r in eligible if r[arm]["question_pass"])
    intent_pass = sum(r[arm]["intent_pass"] for r in eligible)
    intent_n = sum(r[arm]["intent_n"] for r in eligible)
    return {
        "question_ex": round(q_pass / len(eligible), 4),
        "intent_micro_ex": round(intent_pass / intent_n, 4) if intent_n else None,
        "validity": round(sum(1 for r in eligible if r[arm]["validity"]) / len(eligible), 4),
        "routing_exact": round(
            sum(1 for r in eligible if r[arm]["routing"] == "exact") / len(eligible), 4
        ),
        "mean_generate_attempts": round(
            sum(r[arm]["generate_attempts"] for r in eligible) / len(eligible), 2
        ),
        "mean_elapsed_s": round(
            sum(r[arm]["elapsed_s"] for r in eligible) / len(eligible), 2
        ),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="rewrite 消融（EX）")
    parser.add_argument("--gold", action="append", dest="gold_paths", default=None)
    parser.add_argument(
        "--suite",
        action="append",
        dest="suites",
        choices=sorted(SUITES),
        default=None,
        help="预置套件；缺省为 assignment（phase1+phase2）",
    )
    args = parser.parse_args(argv)

    if args.gold_paths or args.suites:
        gold_paths = resolve_gold_paths(args.gold_paths, args.suites)
    else:
        gold_paths = resolve_gold_paths(None, ["assignment"])
    cases = [c for c in load_gold_files(gold_paths) if not is_oos(c)]

    os.environ.setdefault("AGENTIC_BI_SQL_CSV_DIR", str(OUT_DIR / "ablation_csv"))
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    model = get_structured_llm()
    rows: list[dict[str, Any]] = []
    print(
        f"题目数={len(cases)}（已排除 OOS）| 两臂：with_rewrite / without_rewrite",
        flush=True,
    )

    for i, case in enumerate(cases, start=1):
        print(f"\n--- [{i}/{len(cases)}] {case.get('id')} {case.get('question')}", flush=True)
        gold_err, gold_results = execute_gold_intents(case)
        if gold_err:
            print(f"    INFRA {gold_err}", flush=True)
            rows.append(
                {
                    "id": case.get("id"),
                    "question": case.get("question"),
                    "infra_error": gold_err,
                    "oos": False,
                }
            )
            continue

        try:
            with_raw = run_with_rewrite(str(case["question"]), model)
            with_sum = _score_arm(case, with_raw, gold_results)
        except Exception as e:
            print(f"    WITH    INFRA {e}", flush=True)
            rows.append(
                {
                    "id": case.get("id"),
                    "question": case.get("question"),
                    "infra_error": f"with_rewrite: {e}",
                    "oos": False,
                }
            )
            continue
        print(
            f"    WITH    EX={'PASS' if with_sum['question_pass'] else 'FAIL'} "
            f"validity={with_sum['validity']} routing={with_sum['routing']} "
            f"attempts={with_sum['generate_attempts']} {with_sum['elapsed_s']}s",
            flush=True,
        )
        try:
            without_raw = run_without_rewrite(str(case["question"]), model)
            without_sum = _score_arm(case, without_raw, gold_results)
        except Exception as e:
            print(f"    WITHOUT INFRA {e}", flush=True)
            rows.append(
                {
                    "id": case.get("id"),
                    "question": case.get("question"),
                    "infra_error": f"without_rewrite: {e}",
                    "oos": False,
                    "with_rewrite": with_sum,
                }
            )
            continue
        print(
            f"    WITHOUT EX={'PASS' if without_sum['question_pass'] else 'FAIL'} "
            f"validity={without_sum['validity']} routing={without_sum['routing']} "
            f"attempts={without_sum['generate_attempts']} {without_sum['elapsed_s']}s",
            flush=True,
        )
        rows.append(
            {
                "id": case.get("id"),
                "question": case.get("question"),
                "expected_views": list(case.get("expected_views") or []),
                "infra_error": None,
                "oos": False,
                "with_rewrite": with_sum,
                "without_rewrite": without_sum,
            }
        )

    summary = {
        "n": len(rows),
        "n_infra_error": sum(1 for r in rows if r.get("infra_error")),
        "with_rewrite": _arm_metrics(rows, "with_rewrite"),
        "without_rewrite": _arm_metrics(rows, "without_rewrite"),
        "cases": rows,
    }
    path = OUT_DIR / "rewrite_ablation.json"
    path.write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print("\n===== 汇总（主指标 EX） =====", flush=True)
    print(
        json.dumps(
            {
                "n": summary["n"],
                "n_infra_error": summary["n_infra_error"],
                "with_rewrite": summary["with_rewrite"],
                "without_rewrite": summary["without_rewrite"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    print(f"明细: {path}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
