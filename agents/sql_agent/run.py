"""SQL Agent CLI：`python -m agents.sql_agent.run`。

编排逻辑在 `pipeline`；本模块仅 re-export 对外入口，保持
`from agents.sql_agent.run import run_sql_pipeline_with_feedback` 不变。
"""

from __future__ import annotations

from agents.sql_agent.pipeline import run_sql_pipeline_with_feedback

__all__ = ["run_sql_pipeline_with_feedback"]


if __name__ == "__main__":
    import sys

    TEST_QUESTIONS = [
        "2017 年 GMV 是多少？按月和各州排名的趋势怎样？",
        "平台整体准时交付率是多少？哪些州延迟最严重？",
        "哪种支付方式最受欢迎？平均分期数是多少？",
        "产品的重量、尺寸与运费之间有什么关系？",
        "Top 10 差评品类是什么？",
        "2017年哪个州的销售额最高？交付准时率是多少？哪种支付方式最受欢迎？",
        "哪些卖家的差评率最高？",
    ]

    questions = [sys.argv[1]] if len(sys.argv) > 1 else TEST_QUESTIONS

    def _emit(tool: str, payload: str) -> None:
        print(f"\n===== {tool} 完成 =====\n{payload}")

    for i, question in enumerate(questions, start=1):
        print(f"\n{'=' * 60}\n测试问题 {i}/{len(questions)}\n{question}\n{'=' * 60}")
        out = run_sql_pipeline_with_feedback(question, on_tool_end=_emit)
        print(f"\n===== rewrite_to_query 调用次数 =====\n{out.get('rewrite_attempts')}")
        print(f"\n===== generate_sql 调用次数 =====\n{out.get('generate_sql_attempts')}")
