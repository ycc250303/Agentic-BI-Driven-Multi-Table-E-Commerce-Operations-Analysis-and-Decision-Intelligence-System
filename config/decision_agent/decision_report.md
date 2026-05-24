# 决策报告生成工具 Prompt

调用本工具时，你将得到 JSON 形式的输入：

```json
{
  "question": "...",
  "intent": "...",
  "analysis_summary": "...",
  "sql_results_brief": [
    {"name": "...", "columns": [...], "row_count": 0, "sample_rows": [...], "explanation": "..."}
  ],
  "chart_descriptions": ["..."],
  "forecast_result": {...} | null,
  "review_insights": {...} | null,
  "what_if_result": {...} | null
}
```

### `review_insights` 字段速查与引用优先级

NLP Agent 一次写入四块数据，请按下述优先级在报告中引用，**避免把所有原始字段堆进正文**：

| 优先级 | 字段路径 | 适合写入的章节 |
|---|---|---|
| ⭐⭐⭐ | `complaints_by_category`（关键词法，10 个业务可解释主题）| 二、关键数据发现 / 三、原因诊断 |
| ⭐⭐⭐ | `sentiment.worst_categories` / `sentiment.by_customer_state` / `sentiment.by_seller_state` | 二、关键数据发现 / 三、原因诊断 |
| ⭐⭐ | `topics_bertopic.complaints_by_category[*].top_reasons`（细分主题）| 三、原因诊断（仅在关键词法主导原因为 `other` 占比偏高时补充） |
| ⭐ | `sentiment.by_review_score`（评分 × 极性一致性）| 不进正文，仅作为数据可信度参考 |
| — | `wordcloud.{positive, negative}`（词频字典）| **不在文字正文中列举词频**；若 `chart_descriptions` 含词云图，仅在「七、图表解读」一句话提及 |

引用建议：
- BERTopic 主题标签可能是机器视角（如 `dois / apenas / só`），引用时**必须用人话翻译**（如「数量不符 / 少发货」），并附上原标签便于追溯。
- 若 `topic_distribution` 中 `other` 占比 > 30%，请在三、原因诊断结尾说明「关键词法未覆盖部分已用 BERTopic 补充」。

---

## 输出结构（严格按章节顺序，使用中文标题）

**一、结论摘要**
用 3–5 句话概括最重要的发现，必须包含至少一个具体指标值或同比/环比方向。

**二、关键数据发现**
列出 3–6 条数据发现，每条尽量引用具体指标、地区、品类、卖家或支付方式数值；
若来自图表，请在末尾用方括号标注 `[来自：<图表说明片段>]`。

**三、原因诊断**
对每条主要发现给出可能原因。配送类问题需从客户地区、卖家地区、跨州运输、品类属性、物流时效角度分析；
差评类问题需结合评分分布、评论主题与履约表现分析。

**四、经营风险**
列出若不处理可能造成的影响：GMV 下滑、差评率升高、复购下降、物流成本增加、卖家流失等。

**五、决策建议**
分三档：
- **短期（1 个月内）**：…
- **中期（1–3 个月）**：…
- **长期（3 个月以上）**：…
每条建议须为可执行动作（含目标对象 / 触发条件 / 度量指标）。

**六、优先级排序**
用 P0 / P1 / P2 标记上述建议，并简述理由（影响面、ROI、可实施性）。

**七、图表解读**
对 `chart_descriptions` 中的每张图，单独一行写明它支持了哪条结论；如无图表则写「本次未生成图表」。

**八、下一步可追问问题**
列出 3 个用户可继续追问的问题，问题需可被本系统的 Data Analysis Agent / Decision Agent 回答。

## 内容硬约束

1. 仅使用输入 JSON 中提供的事实；禁止虚构指标、卖家名、品类名等。
2. 若 `forecast_result` / `review_insights` / `what_if_result` 为 `null`，对应章节按需省略，但必须在「一、结论摘要」中说明范围。
3. 涉及 What-if 必须显式说明假设与局限（如「该模拟为静态反事实估计，未考虑用户需求转移与替代购买行为」）。
4. 不要在最终输出中包含本 Prompt 文本或 JSON 字段名。
