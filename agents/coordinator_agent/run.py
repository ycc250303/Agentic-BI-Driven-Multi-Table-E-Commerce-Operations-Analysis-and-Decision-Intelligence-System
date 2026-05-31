"""
协调器 Agent CLI：问题分解 → 迭代调度子 Agent → LLM 汇总 final_answer。

用法（项目根目录）：
    python -m agents.coordinator_agent.run --query "2017年哪个州的销售额最高？"
    python -m agents.coordinator_agent.run --decompose-only --no-llm-plan --query "..."
"""

from __future__ import annotations

import argparse
import json
import sys

from agents.coordinator_agent.decomposer import decompose_query, dump_decompose_json
from agents.coordinator_agent.graph import run_coordinator


def _write(text: str) -> None:
    try:
        print(text)
    except UnicodeEncodeError:
        sys.stdout.buffer.write(text.encode("utf-8"))
        sys.stdout.buffer.write(b"\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="协调器 Agent：迭代式多 Agent 编排")
    parser.add_argument("--query", required=True, help="用户自然语言问题")
    parser.add_argument(
        "--no-llm-plan",
        action="store_true",
        help="问题分解与路由仅用规则引擎",
    )
    parser.add_argument(
        "--no-llm-viz",
        action="store_true",
        help="可视化 Agent 仅用启发式",
    )
    parser.add_argument(
        "--no-llm-synthesize",
        action="store_true",
        help="最终回答仅用规则模板，不调用 LLM",
    )
    parser.add_argument(
        "--decompose-only",
        action="store_true",
        help="仅输出问题分解 JSON",
    )
    parser.add_argument(
        "--full-state",
        action="store_true",
        help="打印完整 AgentState JSON",
    )
    args = parser.parse_args()

    if args.decompose_only:
        result = decompose_query(args.query, use_llm=not args.no_llm_plan)
        _write(dump_decompose_json(result))
        return

    def _emit(tool: str, payload: str) -> None:
        _write(f"\n===== {tool} =====\n{payload[:2000]}")

    state = run_coordinator(
        args.query,
        use_llm_plan=not args.no_llm_plan,
        use_llm_viz=not args.no_llm_viz,
        use_llm_synthesize=not args.no_llm_synthesize,
        on_tool_end=_emit,
    )

    if args.full_state:
        _write(json.dumps(state, ensure_ascii=False, indent=2, default=str))
        return

    _write("\n===== 子问题 =====")
    _write(json.dumps(state.get("sub_questions") or [], ensure_ascii=False, indent=2))
    _write("\n===== 调度记录 =====")
    _write(json.dumps(state.get("execution_log") or [], ensure_ascii=False, indent=2))

    _write("\n===== 最终回答 =====\n")
    _write(str(state.get("final_answer") or "（无 final_answer）"))


if __name__ == "__main__":
    main()
