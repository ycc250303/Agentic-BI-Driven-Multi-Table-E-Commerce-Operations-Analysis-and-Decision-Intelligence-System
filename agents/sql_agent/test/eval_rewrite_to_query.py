import argparse
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
import time
from typing import Any

from dotenv import load_dotenv
from langchain_deepseek import ChatDeepSeek

_sql_agent_dir = Path(__file__).resolve().parents[1]
if str(_sql_agent_dir) not in sys.path:
    sys.path.insert(0, str(_sql_agent_dir))

from tools.rewrite_to_query import (
    RewriteToQueryOutput,
    _load_prompt,
    build_rewrite_to_query_tool,
)
from langchain_core.messages import HumanMessage, SystemMessage


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


EVAL_CONFIGS: list[dict[str, Any]] = [
    {
        "config_id": "flash_thinking_off",
        "label": "flash 关闭思考",
        "model": "deepseek-v4-flash",
        "thinking": "disabled",
    },
    {
        "config_id": "pro_thinking_off",
        "label": "pro 关闭思考",
        "model": "deepseek-v4-pro",
        "thinking": "disabled",
    },
    {
        "config_id": "flash_thinking_on",
        "label": "flash 开启思考",
        "model": "deepseek-v4-flash",
        "thinking": "enabled",
    },
    {
        "config_id": "pro_thinking_on",
        "label": "pro 开启思考",
        "model": "deepseek-v4-pro",
        "thinking": "enabled",
    },
]


def make_llm(model: str, thinking: str) -> ChatDeepSeek:
    load_dotenv()
    if not os.getenv("DEEPSEEK_API_KEY"):
        raise RuntimeError(
            "缺少环境变量 DEEPSEEK_API_KEY。请先设置后再运行，例如："
            "export DEEPSEEK_API_KEY='your_api_key'"
        )
    kwargs: dict[str, Any] = {
        "model": model,
        "extra_body": {"thinking": {"type": thinking}},
    }
    if thinking == "enabled":
        kwargs["reasoning_effort"] = "high"
    return ChatDeepSeek(**kwargs)


def _normalize_thinking_json(data: Any) -> Any:
    if not isinstance(data, dict):
        return data
    query_for_sql = str(data.get("query_for_sql") or "").strip()
    for sq in data.get("sub_questions") or []:
        if not isinstance(sq, dict):
            continue
        if not str(sq.get("question_zh") or "").strip():
            sq["question_zh"] = query_for_sql or "子问题"
        scope = sq.get("scope")
        if isinstance(scope, str):
            sq["scope"] = {"kind": scope}
        for field in ("time_range", "aggregation"):
            if sq.get(field) is None:
                sq[field] = ""
    confidence = data.get("confidence")
    if isinstance(confidence, str):
        confidence_map = {"low": 0.3, "medium": 0.5, "high": 0.8, "max": 0.95}
        data["confidence"] = confidence_map.get(confidence.lower(), 0.5)
    elif confidence is None:
        data["confidence"] = 0.5
    return data


def _build_rewrite_messages(query: str) -> list[Any]:
    background_prompt = _load_prompt("system_core.md")
    schema_prompt = _load_prompt("schema_dictionary.md")
    rewrite_prompt = _load_prompt("rewrite_to_query_tool.md")
    system_prompt = "\n\n".join(
        [
            "# Agent 背景规则",
            background_prompt,
            "# 数据库表结构与视图字典",
            schema_prompt,
            "# 转写工具规则",
            rewrite_prompt,
        ]
    )
    return [
        SystemMessage(content=system_prompt),
        HumanMessage(content=query),
    ]


def _extract_json_object(raw: str) -> dict[str, Any]:
    text = (raw or "").strip()
    if not text:
        raise ValueError("模型返回为空")
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass

    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        parsed = json.loads(text[start : end + 1])
        if isinstance(parsed, dict):
            return parsed
    raise ValueError(f"无法从模型输出解析 JSON: {text[:240]}")


class ThinkingRewriteRunner:
    """思考模式不支持 tool_choice，改为原始 JSON 输出并在评测侧做字段归一化。"""

    def __init__(self, model, max_retries: int = 3):
        self.model = model
        self.max_retries = max_retries

    def invoke(self, query: str) -> str:
        messages = _build_rewrite_messages(query)
        messages.append(
            HumanMessage(
                content=(
                    "请仅输出一个 JSON 对象，字段需包含：sub_questions、hit_pre_agg_view、"
                    "candidate_views、confidence。sub_questions 每项需含 question_zh，"
                    "scope 需为对象（如 {\"kind\":\"platform\"}）。不要输出 Markdown 或解释文字。"
                )
            )
        )
        last_error: Exception | None = None
        resp: RewriteToQueryOutput | None = None

        for _ in range(self.max_retries):
            try:
                response = self.model.invoke(messages)
                content = response.content if hasattr(response, "content") else str(response)
                if isinstance(content, list):
                    content = "".join(
                        block.get("text", "") if isinstance(block, dict) else str(block)
                        for block in content
                    )
                parsed = _extract_json_object(str(content))
                resp = RewriteToQueryOutput.model_validate(_normalize_thinking_json(parsed))
                break
            except Exception as e:
                last_error = e

        if resp is None:
            raise RuntimeError(
                f"rewrite_to_query（thinking/json_mode）在 {self.max_retries} 次尝试后仍失败: {last_error}"
            )

        return resp.model_dump_json(
            indent=2,
            ensure_ascii=False,
            exclude_none=True,
            exclude_defaults=True,
        )


def build_eval_tool(model: ChatDeepSeek, thinking: str, max_retries: int = 3):
    if thinking == "enabled":
        runner = ThinkingRewriteRunner(model=model, max_retries=max_retries)
        return type(
            "EvalTool",
            (),
            {"invoke": lambda _self, payload: runner.invoke(str(payload["query"]))},
        )()
    return build_rewrite_to_query_tool(model, max_retries=max_retries)


def run_eval(
    rounds: int = 5,
    verbose: bool = True,
    model: ChatDeepSeek | None = None,
    thinking: str = "disabled",
    config_label: str | None = None,
) -> dict[str, Any]:
    llm = model or make_llm("deepseek-v4-flash", thinking)
    tool = build_eval_tool(llm, thinking)

    per_question_state: list[dict[str, Any]] = []
    total = len(TEST_CASES) * rounds
    correct = 0
    started_at = time.time()

    if verbose:
        print("===== 开始评测 rewrite_to_query 视图命中 =====", flush=True)
        if config_label:
            print(f"配置: {config_label}", flush=True)
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
            invoke_error = ""
            try:
                raw = tool.invoke({"query": question})
            except Exception as e:
                raw = json.dumps({"invoke_error": str(e)}, ensure_ascii=False)
                invoke_error = str(e)
            parsed = parse_tool_json(raw)
            predicted_views = normalize_views(parsed.get("candidate_views", []))
            predicted_hit = bool(parsed.get("hit_pre_agg_view", False))
            if invoke_error:
                error_type = "invoke_error"
                is_correct = False
            else:
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
                    "invoke_error": invoke_error,
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
        "config_label": config_label,
    }


def resolve_configs(config_ids: list[str] | None) -> list[dict[str, Any]]:
    if not config_ids:
        return EVAL_CONFIGS
    known = {cfg["config_id"]: cfg for cfg in EVAL_CONFIGS}
    selected: list[dict[str, Any]] = []
    for config_id in config_ids:
        if config_id not in known:
            valid = ", ".join(known)
            raise ValueError(f"未知 config_id: {config_id}，可选: {valid}")
        selected.append(known[config_id])
    return selected


def config_result_path(output_dir: Path, config_id: str) -> Path:
    return output_dir / f"rewrite_to_query_benchmark_{config_id}.json"


def save_config_result(output_dir: Path, result: dict[str, Any]) -> Path:
    path = config_result_path(output_dir, result["config_id"])
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def load_partial_results(output_dir: Path) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for cfg in EVAL_CONFIGS:
        path = config_result_path(output_dir, cfg["config_id"])
        if not path.exists():
            continue
        loaded = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(loaded, dict):
            results.append(loaded)
    return results


def merge_benchmark_results(results: list[dict[str, Any]]) -> dict[str, Any]:
    order = {cfg["config_id"]: idx for idx, cfg in enumerate(EVAL_CONFIGS)}
    sorted_results = sorted(results, key=lambda item: order.get(item.get("config_id", ""), 999))
    rounds = sorted_results[0]["rounds"] if sorted_results else 5
    summary = [
        {
            "config_id": item["config_id"],
            "label": item.get("config_label") or item["config_id"],
            "model": item["model"],
            "thinking": item["thinking"],
            "overall_accuracy": item["overall_accuracy"],
            "elapsed_seconds": item["elapsed_seconds"],
            "always_wrong_count": item["always_wrong_count"],
            "flaky_count": item["flaky_count"],
        }
        for item in sorted_results
    ]
    total_elapsed = round(sum(item["elapsed_seconds"] for item in sorted_results), 2)
    return {
        "rounds": rounds,
        "benchmark_total_elapsed": total_elapsed,
        "completed_configs": [item["config_id"] for item in sorted_results],
        "pending_configs": [
            cfg["config_id"]
            for cfg in EVAL_CONFIGS
            if cfg["config_id"] not in {item["config_id"] for item in sorted_results}
        ],
        "summary": summary,
        "results": sorted_results,
    }


def write_benchmark_reports(output_dir: Path, benchmark: dict[str, Any]) -> tuple[Path, Path]:
    json_path = output_dir / "rewrite_to_query_benchmark.json"
    md_path = output_dir / "rewrite_to_query_benchmark.md"
    json_path.write_text(json.dumps(benchmark, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(build_benchmark_text(benchmark), encoding="utf-8")
    return json_path, md_path


def run_benchmark(
    rounds: int = 5,
    verbose: bool = True,
    configs: list[dict[str, Any]] | None = None,
    output_dir: Path | None = None,
    save_partial: bool = False,
) -> dict[str, Any]:
    selected = configs or EVAL_CONFIGS
    benchmark_started = time.time()
    results: list[dict[str, Any]] = []

    if verbose:
        print("===== DeepSeek 四模式对比评测 =====", flush=True)
        print(f"模式数={len(selected)} | 每题轮次={rounds}", flush=True)

    for cfg in selected:
        if verbose:
            print(f"\n{'=' * 60}", flush=True)
            print(f"开始: {cfg['label']} ({cfg['model']} | thinking={cfg['thinking']})", flush=True)
        llm = make_llm(cfg["model"], cfg["thinking"])
        result = run_eval(
            rounds=rounds,
            verbose=verbose,
            model=llm,
            thinking=cfg["thinking"],
            config_label=cfg["label"],
        )
        result["config_id"] = cfg["config_id"]
        result["model"] = cfg["model"]
        result["thinking"] = cfg["thinking"]
        results.append(result)
        if save_partial and output_dir is not None:
            partial_path = save_config_result(output_dir, result)
            if verbose:
                print(f"已保存分批结果: {partial_path}", flush=True)
        if verbose:
            print(
                f"完成: {cfg['label']} | acc={result['overall_accuracy']:.2%} | "
                f"elapsed={result['elapsed_seconds']}s",
                flush=True,
            )

    total_elapsed = round(time.time() - benchmark_started, 2)
    summary = [
        {
            "config_id": item["config_id"],
            "label": item.get("config_label") or item["config_id"],
            "model": item["model"],
            "thinking": item["thinking"],
            "overall_accuracy": item["overall_accuracy"],
            "elapsed_seconds": item["elapsed_seconds"],
            "always_wrong_count": item["always_wrong_count"],
            "flaky_count": item["flaky_count"],
        }
        for item in results
    ]

    if verbose:
        print(f"\n{'=' * 60}", flush=True)
        print("===== 四模式对比汇总 =====", flush=True)
        for row in summary:
            print(
                f"{row['label']:14s} | acc={row['overall_accuracy']:.2%} | "
                f"elapsed={row['elapsed_seconds']}s | "
                f"always_wrong={row['always_wrong_count']} | flaky={row['flaky_count']}",
                flush=True,
            )
        print(f"benchmark_total_elapsed={total_elapsed}s", flush=True)

    return {
        "rounds": rounds,
        "benchmark_total_elapsed": total_elapsed,
        "summary": summary,
        "results": results,
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


def build_benchmark_text(benchmark: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# rewrite_to_query DeepSeek 四模式对比评测")
    lines.append("")
    lines.append(f"- 每题轮次: {benchmark['rounds']}")
    lines.append(f"- 总耗时: {benchmark['benchmark_total_elapsed']}s")
    lines.append("")
    lines.append("## 汇总")
    lines.append("")
    lines.append("| 模式 | 模型 | 思考 | 准确率 | 耗时(s) | 总是错 | 不稳定 |")
    lines.append("| --- | --- | --- | ---: | ---: | ---: | ---: |")
    for row in benchmark["summary"]:
        thinking = "开启" if row["thinking"] == "enabled" else "关闭"
        lines.append(
            f"| {row['label']} | {row['model']} | {thinking} | "
            f"{row['overall_accuracy']:.2%} | {row['elapsed_seconds']} | "
            f"{row['always_wrong_count']} | {row['flaky_count']} |"
        )
    lines.append("")
    for item in benchmark["results"]:
        lines.append(f"## {item.get('config_label') or item['config_id']}")
        lines.append("")
        lines.append(build_analysis_text(item))
        lines.append("")
    return "\n".join(lines)


if __name__ == "__main__":
    config_help = ", ".join(cfg["config_id"] for cfg in EVAL_CONFIGS)
    parser = argparse.ArgumentParser(description="rewrite_to_query 视图命中评测")
    parser.add_argument("--rounds", type=int, default=5, help="每题重复轮次")
    parser.add_argument(
        "--benchmark",
        action="store_true",
        help="运行 DeepSeek flash/pro × 思考开/关 四模式对比评测",
    )
    parser.add_argument(
        "--config",
        action="append",
        dest="configs",
        metavar="CONFIG_ID",
        help=f"分批运行指定配置，可重复传入。可选: {config_help}",
    )
    parser.add_argument(
        "--merge-only",
        action="store_true",
        help="仅合并 eval_outputs 中已有的分批结果，不发起 API 调用",
    )
    parser.add_argument("--quiet", action="store_true", help="仅输出汇总，不打印逐题日志")
    args = parser.parse_args()

    # 与本脚本同目录下的 eval_outputs，避免用 parents[n] 误判仓库根路径
    output_dir = Path(__file__).resolve().parent / "eval_outputs"
    output_dir.mkdir(parents=True, exist_ok=True)
    verbose = not args.quiet

    if args.merge_only:
        partial = load_partial_results(output_dir)
        if not partial:
            raise SystemExit(f"未找到分批结果，请先运行 --benchmark --config <id>。目录: {output_dir}")
        benchmark = merge_benchmark_results(partial)
        json_path, md_path = write_benchmark_reports(output_dir, benchmark)
        print(f"已合并 {len(partial)}/{len(EVAL_CONFIGS)} 个配置")
        print(f"对比评测: {json_path}")
        print(f"对比报告: {md_path}")
        if benchmark["pending_configs"]:
            print(f"待完成: {', '.join(benchmark['pending_configs'])}")
        for row in benchmark["summary"]:
            print(
                f"{row['label']}: acc={row['overall_accuracy']:.2%}, "
                f"elapsed={row['elapsed_seconds']}s"
            )
    elif args.benchmark:
        selected_configs = resolve_configs(args.configs)
        batch_mode = bool(args.configs)
        benchmark = run_benchmark(
            rounds=args.rounds,
            verbose=verbose,
            configs=selected_configs,
            output_dir=output_dir,
            save_partial=batch_mode,
        )
        if batch_mode:
            partial = load_partial_results(output_dir)
            benchmark = merge_benchmark_results(partial)
        json_path, md_path = write_benchmark_reports(output_dir, benchmark)
        print(f"对比评测完成: {json_path}")
        print(f"对比报告: {md_path}")
        if batch_mode and benchmark.get("pending_configs"):
            print(f"待完成配置: {', '.join(benchmark['pending_configs'])}")
        for row in benchmark["summary"]:
            print(
                f"{row['label']}: acc={row['overall_accuracy']:.2%}, "
                f"elapsed={row['elapsed_seconds']}s"
            )
    else:
        result = run_eval(rounds=args.rounds, verbose=verbose)
        json_path = output_dir / "rewrite_to_query_eval.json"
        md_path = output_dir / "rewrite_to_query_eval.md"
        json_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        md_path.write_text(build_analysis_text(result), encoding="utf-8")
        print(f"评测完成: {json_path}")
        print(f"分析报告: {md_path}")
        print(f"总体准确率: {result['overall_accuracy']:.2%}")
