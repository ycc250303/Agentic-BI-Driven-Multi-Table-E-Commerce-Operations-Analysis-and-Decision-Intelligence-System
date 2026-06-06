from __future__ import annotations

from agents.viz_agent.insight_charts import insight_chart_has_data, insight_chart_rows


def test_bertopic_complaints_by_category_rows():
    insights = {
        "complaints_by_category": [
            {
                "category": "cama_mesa_banho",
                "total": 100,
                "top_reasons": [
                    {"label": "缺件/数量", "count": 40, "share": 0.4},
                    {"label": "配送慢", "count": 20, "share": 0.2},
                ],
            }
        ]
    }
    rows = insight_chart_rows(insights, "complaints_by_category")
    assert len(rows) == 2
    assert insight_chart_has_data(insights, "complaints_by_category")


def test_bertopic_topic_distribution_from_topics_bertopic():
    insights = {
        "topic_distribution": {},
        "topics_bertopic": {
            "topics": [
                {"topic_id": 1, "label": "配送延迟", "sample_count": 120},
                {"topic_id": 2, "label": "商品质量", "sample_count": 80},
            ]
        },
    }
    rows = insight_chart_rows(insights, "topic_distribution")
    assert len(rows) == 2
    assert insight_chart_has_data(insights, "topic_distribution")


def test_empty_bertopic_complaints_not_renderable():
    insights = {
        "complaints_by_category": [
            {"category": "x", "total": 0, "top_reasons": []},
        ]
    }
    assert not insight_chart_has_data(insights, "complaints_by_category")
