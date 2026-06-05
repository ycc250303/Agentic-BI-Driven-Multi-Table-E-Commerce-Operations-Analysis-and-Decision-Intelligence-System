"""NLP 洞察 → 可视化行数据（兼容关键词分类与 BERTopic 两种结构）。"""

from __future__ import annotations

from typing import Any

def _topic_zh(key: str) -> str:
    from agents.viz_agent.viz_planner import _TOPIC_ZH

    return _TOPIC_ZH.get(key, key)


def insight_chart_rows(insights: dict[str, Any] | None, kind: str) -> list[dict[str, Any]]:
    data = insights or {}
    if kind == "topic_distribution":
        td = data.get("topic_distribution") or {}
        if td:
            return [
                {
                    "topic": _topic_zh(str(k)),
                    "count": int(v),
                }
                for k, v in td.items()
                if int(v or 0) > 0
            ]
        bt = data.get("topics_bertopic") or {}
        return [
            {
                "topic": str(t.get("label") or f"主题{t.get('topic_id')}"),
                "count": int(t.get("sample_count") or 0),
            }
            for t in (bt.get("topics") or [])
            if int(t.get("sample_count") or 0) > 0
        ]

    if kind == "complaints_by_category":
        rows: list[dict[str, Any]] = []
        for item in data.get("complaints_by_category") or []:
            cat = str(item.get("category") or "未知")
            nested = item.get("topic_distribution") or {}
            if nested:
                for topic, cnt in nested.items():
                    if int(cnt or 0) <= 0:
                        continue
                    rows.append(
                        {
                            "category": cat,
                            "topic": _topic_zh(str(topic)),
                            "count": int(cnt),
                        }
                    )
                continue
            for reason in item.get("top_reasons") or []:
                cnt = int(reason.get("count") or 0)
                if cnt <= 0:
                    continue
                rows.append(
                    {
                        "category": cat,
                        "topic": str(reason.get("label") or reason.get("topic_id")),
                        "count": cnt,
                    }
                )
        return rows

    return []


def insight_chart_has_data(insights: dict[str, Any] | None, kind: str) -> bool:
    return bool(insight_chart_rows(insights, kind))
