from pathlib import Path

from agentic_bi.core.prompts import render_prompt
from agentic_bi.data.metrics import MetricCatalog

CONFIG_PATH = Path("config")


def test_interpret_prompt_uses_catalog_defaults_before_requesting_clarification() -> None:
    catalog = MetricCatalog.load(CONFIG_PATH / "metrics.yaml")

    rendered = render_prompt(
        "analysis/interpret",
        {
            "locale": "zh-CN",
            "metric_context": catalog.render_metric_context(),
            "question": "2017 年哪个客户州的销售额最高？",
        },
        config_dir=CONFIG_PATH,
    )

    assert "目录已给出默认口径时，直接使用该口径" in rendered.content
    assert "execute 分支表示信息完整" in rendered.content
    assert "clarify 分支表示缺少会改变答案的信息" in rendered.content
    assert "code=missing_metric" in rendered.content
    assert "可以直接展示的完整问题" in rendered.content
    assert "只统计非已取消、非不可用的订单" in rendered.content
    assert "只统计已送达且客户签收时间不为空的订单" in rendered.content
    assert "用户只说销售额、成交额或 GMV 时使用本指标" in rendered.content
