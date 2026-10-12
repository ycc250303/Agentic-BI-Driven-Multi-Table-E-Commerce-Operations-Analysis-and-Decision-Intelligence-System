#!/usr/bin/env python3
"""反引号 A/B：capability 套件各独立复跑 3 次，结束后还原 generate Prompt。"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PROMPT = ROOT / "config" / "sql_agent" / "generate_sql_tool.md"
OUT_DIR = Path(__file__).resolve().parent / "eval_outputs"
BACKUP = OUT_DIR / "generate_sql_tool.always_backtick.md"
MINIMAL = OUT_DIR / "generate_sql_tool.minimal_backtick.md"
ALWAYS_JSON = OUT_DIR / "ex_backtick_always.json"
MINIMAL_JSON = OUT_DIR / "ex_backtick_minimal.json"
COMPARE_JSON = OUT_DIR / "ex_backtick_ab_compare.json"
EVAL = ROOT / "agents" / "sql_agent" / "test" / "eval_ex.py"


def _run_eval(output: Path) -> None:
    cmd = [
        sys.executable,
        str(EVAL),
        "--suite",
        "capability",
        "--repeat",
        "3",
        "--output",
        str(output),
    ]
    print(f"$ {' '.join(cmd)}", flush=True)
    subprocess.run(cmd, cwd=str(ROOT), check=True)


def _mean(xs: list[float]) -> float | None:
    return round(sum(xs) / len(xs), 4) if xs else None


def _variant_stats(report: dict) -> dict:
    all_rows: list[dict] = []
    for block in report.get("cases") or []:
        all_rows.extend(block.get("cases") or [])
    attempts: list[float] = []
    retry_n = 0
    sql_n = 0
    sql_with_tick = 0
    sql_tick_count = 0
    pred_err_n = 0
    year_month_err_n = 0
    for row in all_rows:
        if not row.get("ex_eligible"):
            continue
        att = row.get("generate_sql_attempts")
        if isinstance(att, (int, float)):
            attempts.append(float(att))
            if att > 1:
                retry_n += 1
        for sql in row.get("pred_sqls") or []:
            sql_n += 1
            n_tick = str(sql).count("`")
            sql_tick_count += n_tick
            if n_tick:
                sql_with_tick += 1
        for err in row.get("pred_errors") or []:
            if not err:
                continue
            pred_err_n += 1
            if "year_month" in str(err).lower():
                year_month_err_n += 1
    split_means: dict[str, list[float]] = {}
    for run in report.get("runs") or []:
        for split, payload in (run.get("by_split") or {}).items():
            split_means.setdefault(split, []).append(float(payload["question_ex"]))
    return {
        "stability": report.get("stability"),
        "runs": report.get("runs"),
        "n_case_rows": len(all_rows),
        "generate_sql_attempts_mean": _mean(attempts),
        "retry_rate": round(retry_n / len(attempts), 4) if attempts else None,
        "sql_with_backtick_rate": round(sql_with_tick / sql_n, 4) if sql_n else None,
        "backticks_per_sql_mean": round(sql_tick_count / sql_n, 4) if sql_n else None,
        "pred_error_n": pred_err_n,
        "year_month_error_n": year_month_err_n,
        "by_split_question_ex_mean": {
            k: _mean(v) for k, v in sorted(split_means.items())
        },
    }


def _pass_counts(report: dict) -> dict[str, int]:
    counts: dict[str, int] = {}
    for block in report.get("cases") or []:
        for row in block.get("cases") or []:
            if not row.get("ex_eligible"):
                continue
            cid = str(row.get("id"))
            counts[cid] = counts.get(cid, 0) + int(bool(row.get("question_pass")))
    return counts


def compare(always: dict, minimal: dict) -> dict:
    a_pass = _pass_counts(always)
    b_pass = _pass_counts(minimal)
    ids = sorted(set(a_pass) | set(b_pass))
    a_better = []
    b_better = []
    tied = []
    for cid in ids:
        av = a_pass.get(cid, 0)
        bv = b_pass.get(cid, 0)
        rec = {"id": cid, "always_pass_n": av, "minimal_pass_n": bv}
        if av > bv:
            a_better.append(rec)
        elif bv > av:
            b_better.append(rec)
        else:
            tied.append(rec)
    return {
        "always": _variant_stats(always),
        "minimal": _variant_stats(minimal),
        "n_questions": len(ids),
        "always_better_n": len(a_better),
        "minimal_better_n": len(b_better),
        "tied_n": len(tied),
        "always_better": a_better,
        "minimal_better": b_better,
    }


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    if not MINIMAL.is_file():
        raise SystemExit(f"缺少 {MINIMAL}")
    original = PROMPT.read_text(encoding="utf-8")
    BACKUP.write_text(original, encoding="utf-8")
    try:
        print("===== VARIANT A START (always backtick) =====", flush=True)
        PROMPT.write_text(BACKUP.read_text(encoding="utf-8"), encoding="utf-8")
        _run_eval(ALWAYS_JSON)
        print("===== VARIANT A DONE =====", flush=True)

        print("===== VARIANT B START (minimal backtick) =====", flush=True)
        PROMPT.write_text(MINIMAL.read_text(encoding="utf-8"), encoding="utf-8")
        _run_eval(MINIMAL_JSON)
        print("===== VARIANT B DONE =====", flush=True)
    finally:
        PROMPT.write_text(BACKUP.read_text(encoding="utf-8"), encoding="utf-8")
        print("===== RESTORED PROMPT =====", flush=True)

    always = json.loads(ALWAYS_JSON.read_text(encoding="utf-8"))
    minimal = json.loads(MINIMAL_JSON.read_text(encoding="utf-8"))
    report = compare(always, minimal)
    COMPARE_JSON.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print("\n===== BACKTICK A/B COMPARE =====", flush=True)
    print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)
    print(f"明细: {COMPARE_JSON}", flush=True)
    print("===== BACKTICK_AB_DONE =====", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
