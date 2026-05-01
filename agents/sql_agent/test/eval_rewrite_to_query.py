import json
from dataclasses import dataclass
from pathlib import Path
import time
from typing import Any

from llm import get_llm
from tools.rewrite_to_query import build_rewrite_to_query_tool


KNOWN_VIEWS = {
    "mv_monthly_sales",
    "mv_state_sales",
    "mv_category_sales",
    "mv_delivery_perf",
    "mv_seller_perf",
    "mv_payment_dist",
}


@dataclass(frozen=True)
class TestCase:
    question: str
    expected_views: tuple[str, ...]


TEST_CASES: list[TestCase] = [
    TestCase("最近12个月的月度GMV趋势如何？", ("mv_monthly_sales",)),
    TestCase("2018年各州销售额排名TOP10。", ("mv_state_sales",)),
    TestCase("按月看各品类GMV变化，找出下滑最明显的3个品类。", ("mv_category_sales",)),
    TestCase("平台整体准时交付率及各州延迟订单数。", ("mv_delivery_perf",)),
    TestCase("分期支付平均期数和各支付方式交易分布。", ("mv_payment_dist",)),
    TestCase("评分最低的卖家是谁？按州看卖家GMV和平均评分。", ("mv_seller_perf",)),
    TestCase("最近12个月各州每月GMV趋势。", ("mv_state_sales",)),
    TestCase("按月比较GMV、订单量、客单价、运费。", ("mv_monthly_sales",)),
    TestCase("不同品类的平均客单价和订单量对比。", ("mv_category_sales",)),
    TestCase("哪些州的平均配送时长最长，准时率最低？", ("mv_delivery_perf",)),
    TestCase("信用卡和Boleto支付方式的交易额与笔数趋势。", ("mv_payment_dist",)),
    TestCase("卖家维度看月度订单量、GMV和平均评分。", ("mv_seller_perf",)),
    TestCase("按州和月份联合分析销售额与准时率。", ("mv_state_sales", "mv_delivery_perf")),
    TestCase("按月对比品类GMV与支付方式分布变化。", ("mv_category_sales", "mv_payment_dist")),
    TestCase("卖家绩效与州级销售走势联合观察。", ("mv_seller_perf", "mv_state_sales")),
    TestCase("商品重量、体积与运费关系（做散点相关分析）。", ()),
    TestCase("评论文本里差评高频词有哪些？并看对应品类。", ()),
    TestCase("给出未来6周销售额预测。", ()),
    TestCase("客户LTV分层分析与复购周期。", ()),
    TestCase("州内城市级别配送热力图（经纬度）。", ()),
]


def normalize_views(raw_views: Any) -> tuple[str, ...]:
    if not isinstance(raw_views, list):
        return tuple()
    cleaned = sorted({v for v in raw_views if isinstance(v, str) and v in KNOWN_VIEWS})
    return tuple(cleaned)


def parse_tool_json(raw: str) -> dict[str, Any]:
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            return parsed
    except Exception:
        pass
    return {}


def classify_error(expected: tuple[str, ...], predicted: tuple[str, ...], predicted_hit: bool) -> str:
    expect_hit = len(expected) > 0
    if expect_hit and not predicted_hit:
        return "false_negative"
    if (not expect_hit) and predicted_hit:
        return "false_positive"
    if predicted != tuple(sorted(expected)):
        return "wrong_view_set"
    return "correct"


def _fmt_views(views: tuple[str, ...]) -> str:
    return ",".join(views) if views else "无命中"


def run_eval(rounds: int = 5, verbose: bool = True) -> dict[str, Any]:
    model = get_llm()
    tool = build_rewrite_to_query_tool(model)

    per_question_state: list[dict[str, Any]] = []
    total = len(TEST_CASES) * rounds
    correct = 0
    started_at = time.time()

    if verbose:
        print("===== 开始评测 rewrite_to_query 视图命中 =====", flush=True)
        print(f"题目数={len(TEST_CASES)} | 每题轮次={rounds} | 总调用次数={total}", flush=True)

    for case_idx, case in enumerate(TEST_CASES, start=1):
        expected_sorted = tuple(sorted(case.expected_views))
        per_question_state.append(
            {
                "case_id": case_idx,
                "question": case.question,
                "expected_views": list(expected_sorted),
                "expected_hit": len(expected_sorted) > 0,
                "correct_count": 0,
                "prediction_patterns_set": set(),
                "error_types": {},
                "runs": [],
            }
        )

    for r in range(1, rounds + 1):
        if verbose:
            print(f"\n===== Round {r}/{rounds} =====", flush=True)
        for state in per_question_state:
            expected_sorted = tuple(state["expected_views"])
            case_idx = int(state["case_id"])
            question = str(state["question"])
            raw = tool.invoke({"query": question})
            parsed = parse_tool_json(raw)
            predicted_views = normalize_views(parsed.get("candidate_views", []))
            predicted_hit = bool(parsed.get("hit_pre_agg_view", False))
            error_type = classify_error(expected_sorted, predicted_views, predicted_hit)
            is_correct = error_type == "correct"

            if is_correct:
                correct += 1
                state["correct_count"] += 1
            else:
                state["error_types"][error_type] = state["error_types"].get(error_type, 0) + 1

            state["prediction_patterns_set"].add((predicted_hit, predicted_views))
            state["runs"].append(
                {
                    "round": r,
                    "raw": raw,
                    "predicted_hit": predicted_hit,
                    "predicted_views": list(predicted_views),
                    "is_correct": is_correct,
                    "error_type": error_type,
                }
            )

            if verbose:
                done = (r - 1) * len(TEST_CASES) + case_idx
                running_acc = correct / done if done else 0
                print(
                    f"[Case {case_idx:02d}/{len(TEST_CASES)}] round {r}/{rounds} | "
                    f"预期={_fmt_views(expected_sorted)} | "
                    f"hit={predicted_hit} | "
                    f"views={_fmt_views(predicted_views)} | "
                    f"result={error_type} | "
                    f"running_acc={running_acc:.2%}",
                    flush=True,
                )

    per_question: list[dict[str, Any]] = []
    for state in per_question_state:
        question_correct = int(state["correct_count"])
        patterns = sorted(state["prediction_patterns_set"])
        per_question.append(
            {
                "case_id": state["case_id"],
                "question": state["question"],
                "expected_views": state["expected_views"],
                "expected_hit": state["expected_hit"],
                "correct_count": question_correct,
                "accuracy": round(question_correct / rounds, 4),
                "is_always_wrong": question_correct == 0,
                "is_flaky": 0 < question_correct < rounds,
                "prediction_patterns": [
                    {"predicted_hit": p[0], "predicted_views": list(p[1])} for p in patterns
                ],
                "error_types": state["error_types"],
                "runs": state["runs"],
            }
        )

    always_wrong = [q for q in per_question if q["is_always_wrong"]]
    flaky = [q for q in per_question if q["is_flaky"]]
    elapsed = round(time.time() - started_at, 2)

    if verbose:
        print("\n===== 评测结束 =====", flush=True)
        print(
            f"overall_acc={correct / total:.2%} | "
            f"always_wrong={len(always_wrong)} | "
            f"flaky={len(flaky)} | "
            f"elapsed={elapsed}s",
            flush=True,
        )

    return {
        "rounds": rounds,
        "total_questions": len(TEST_CASES),
        "total_predictions": total,
        "correct_predictions": correct,
        "overall_accuracy": round(correct / total, 4),
        "always_wrong_count": len(always_wrong),
        "flaky_count": len(flaky),
        "always_wrong_cases": always_wrong,
        "flaky_cases": flaky,
        "per_question": per_question,
        "elapsed_seconds": elapsed,
    }


def build_analysis_text(result: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# rewrite_to_query 视图命中评测报告")
    lines.append("")
    lines.append(f"- 题目数: {result['total_questions']}")
    lines.append(f"- 每题轮次: {result['rounds']}")
    lines.append(f"- 总判断次数: {result['total_predictions']}")
    lines.append(f"- 正确次数: {result['correct_predictions']}")
    lines.append(f"- 总体准确率: {result['overall_accuracy']:.2%}")
    lines.append(f"- 总是判断错误题目数: {result['always_wrong_count']}")
    lines.append(f"- 有时对有时错题目数: {result['flaky_count']}")
    lines.append("")

    lines.append("## 总是判断错误题目")
    if not result["always_wrong_cases"]:
        lines.append("- 无")
    else:
        for item in result["always_wrong_cases"]:
            lines.append(f"- Case {item['case_id']}: {item['question']}")
            lines.append(f"  - 预期视图: {item['expected_views'] or '无命中'}")
            lines.append(f"  - 常见错误类型: {item['error_types']}")
            lines.append(f"  - 预测模式: {item['prediction_patterns']}")
    lines.append("")

    lines.append("## 有时正确有时错误题目")
    if not result["flaky_cases"]:
        lines.append("- 无")
    else:
        for item in result["flaky_cases"]:
            lines.append(f"- Case {item['case_id']}: {item['question']}")
            lines.append(f"  - 准确率: {item['accuracy']:.2%}")
            lines.append(f"  - 预期视图: {item['expected_views'] or '无命中'}")
            lines.append(f"  - 错误类型: {item['error_types']}")
            lines.append(f"  - 预测模式: {item['prediction_patterns']}")
    lines.append("")

    lines.append("## 每题准确率")
    for item in result["per_question"]:
        lines.append(
            f"- Case {item['case_id']:02d} | acc={item['accuracy']:.2%} | expected={item['expected_views'] or '无命中'} | {item['question']}"
        )
    lines.append("")
    return "\n".join(lines)


if __name__ == "__main__":
    project_root = Path(__file__).resolve().parents[2]
    output_dir = project_root / "agents" / "sql_agent" / "test" / "eval_outputs"
    output_dir.mkdir(parents=True, exist_ok=True)

    result = run_eval(rounds=5, verbose=True)
    json_path = output_dir / "rewrite_to_query_eval.json"
    md_path = output_dir / "rewrite_to_query_eval.md"
    json_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(build_analysis_text(result), encoding="utf-8")

    print(f"评测完成: {json_path}")
    print(f"分析报告: {md_path}")
    print(f"总体准确率: {result['overall_accuracy']:.2%}")
