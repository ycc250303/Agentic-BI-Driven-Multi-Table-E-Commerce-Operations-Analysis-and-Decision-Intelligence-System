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

    assert "目录已给出默认口径时直接采用" in rendered.content
    assert "不得仅因存在其他口径的指标就写入 clarification_questions" in rendered.content
    assert "可直接展示给调用方的完整问题" in rendered.content
    assert "用户只说销售额、成交额或 GMV 时使用本指标" in rendered.content
