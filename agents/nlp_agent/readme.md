# NLP / 评论洞察 Agent

面向 **Agentic BI** 5-Agent 方案中的 NLP 节点：将 `order_reviews` 评论文本（葡萄牙语）
转化为**结构化指标**，供下游决策智能 Agent 直接消费。

> **职责定位**：只做"非结构化文本 → 结构化指标"的转换，**不**做 SQL 业务查询、**不**画图、**不**写决策建议。

---

## 1. 目录结构

```
agents/nlp_agent/
├── __init__.py
├── db.py                       # 复用 sql_agent 环境变量的 PyMySQL 查询封装（独立，不依赖 decision_agent）
├── state.py                    # ReviewInsightState / ReviewInsightsPayload TypedDict
├── run.py                      # ReviewInsightAgent + nlp_node(state) + CLI
├── tools/
│   ├── __init__.py
│   ├── topic_keyword.py        # 葡语关键词主题分类（含主题 × 品类交叉表）
│   ├── sentiment.py            # 葡语情感分析：离线灌库 review_sentiment + 在线聚合
│   ├── topic_model.py          # BERTopic 无监督主题：离线灌库 review_topics(_meta) + 在线聚合
│   └── wordcloud_data.py       # 好评 / 差评对比词云数据生成
└── readme.md                   # 本文件
```

配套提示词与配置：

```
config/nlp_agent/
├── system_core.md              # NLP Agent 角色边界与方法分层
├── topic_keywords.yaml         # 葡语主题关键词词典（关键词法用，可热更新）
└── stopwords_pt.txt            # 葡语停用词词典（词云生成时过滤）
```

---

## 2. 输入 / 输出 State 字段

NLP Agent 通过 LangGraph `state` 与其他 Agent 通信。

**主要读取**

| 字段 | 来源 | 说明 |
|------|------|------|
| `question` | Orchestrator | 用户原始问题 |
| `intent` | Orchestrator | `descriptive` / `diagnostic` / `predictive` / `what_if` / `prescriptive` |

**主要写入**

`state["review_insights"]`（dict 形式，schema 见 `state.py` 的 `ReviewInsightsPayload`）：

```jsonc
{
  // ── 关键词主题分类（topic_keyword.py）──────────────────────────
  "sample_size": 1000,
  "negative_review_count": 985,
  "topic_distribution":   {"delivery_delay": 152, "product_quality": 80, ...},
  "top_categories":       [{"key": "cama_mesa_banho", "count": 108}, ...],   // Top 5
  "top_seller_states":    [{"key": "SP", "count": 410}, ...],
  "top_customer_states":  [{"key": "RJ", "count": 220}, ...],
  "complaints_by_category": [
    {
      "category": "cama_mesa_banho",
      "total": 108,
      "dominant_topic": "not_received",
      "dominant_share": 0.31,
      "topic_distribution": {"not_received": 34, "other": 28, ...}
    },
    ... // Top 10 差评品类，每个含主导原因 + 完整分布
  ],
  "method": "keyword_pt_baseline",
  "summary": "采样 1000 条差评……主导主题为「other」，占比 36.9%。",

  // ── 情感分析聚合（sentiment.py，读 review_sentiment 表）────────
  "sentiment": {
    "total": 40641,
    "polarity_distribution": {"POS": 19238, "NEU": 13609, "NEG": 7794},
    "avg_polarity_score": 0.2709,
    "by_review_score": [{"review_score": 1, "polarity": "NEG", "count": 4772}, ...],
    "worst_categories":  [{"category": "moveis_escritorio", "avg_score": -0.061, ...}, ...],
    "by_customer_state": [{"state": "AL", "avg_score": 0.116, "neg_rate": 0.285, ...}, ...],
    "by_seller_state":   [{"state": "PR", "avg_score": 0.205, ...}, ...],
    "method": "pysentimiento/bertweet-pt-sentiment (offline backfill)",
    "summary": "已落库 40641 条评论的情感分数：POS=47.3%，NEU=33.5%，NEG=19.2%……"
  },

  // ── 好评 / 差评对比词云（wordcloud_data.py）──────────────────
  "wordcloud": {
    "positive": {"prazo": 1101, "antes": 810, "entrega": 741, ...},   // Top N (默认 80)
    "negative": {"não": 2813, "recebi": 1223, "comprei": 701, ...},
    "method":   "1-gram + pt_stopwords",
    "sample":   {"positive": 4000, "negative": 4000},
    "stopwords_count": 155,
    "summary":  "好评 Top 词：prazo, antes, entrega, …；差评 Top 词：não, recebi, …"
  },

  // ── BERTopic 无监督主题（topic_model.py，读 review_topics(_meta) 表）──
  "topics_bertopic": {
    "method":  "bertopic + paraphrase-multilingual-MiniLM-L12-v2",
    "summary": "BERTopic 在差评全量上发现了 12 个有效主题；Top 3 主题为「dois/apenas/só」(920)、…",
    "topics": [
      {
        "topic_id": 0,
        "label": "dois / apenas / só",
        "sample_count": 920,
        "top_words": ["dois", "apenas", "só", "comprei", "unidades", ...]
      },
      ...
    ],
    "complaints_by_category": [
      {
        "category": "cama_mesa_banho",
        "total": 782,
        "top_reasons": [
          {"topic_id": 0, "label": "dois / apenas / só", "count": 284, "share": 0.363},
          {"topic_id": 2, "label": "muito / recebi / entrega", "count": 103, "share": 0.132},
          ...
        ]
      },
      ...
    ]
  }
}
```

---

## 3. 内部执行链路

```mermaid
flowchart TD
    A[state in: question + intent] --> B{should_run_nlp?}
    B -->|否| Z[return state]
    B -->|是| C{state has review_insights?}
    C -->|是| D[幂等：跳过] --> Z
    C -->|否| E[topic_keyword.run_review_insight\n实时抽样 + 关键词分类 + 主题×品类]
    E --> F[sentiment.aggregate_sentiment\n读 review_sentiment 表，毫秒级]
    F --> G[topic_model.aggregate_bertopic\n读 review_topics(_meta) 表，毫秒级]
    G --> H[wordcloud_data.run_wordcloud_data\n好评/差评抽样 + 词频统计]
    H --> I[合并 review_insights] --> Z
```

任意子工具失败都不会阻塞主流程：失败的字段会写入 `{"method": "n/a", "summary": "<原因>"}` 占位。

`should_run_nlp(question, intent)` 触发条件（任一）：
- `intent ∈ {"diagnostic", "prescriptive"}`
- 问题命中：`评论 / 差评 / 评分 / 抱怨 / 满意度 / 投诉 / review / sentiment / complaint / feedback ...`

---

## 4. 在 LangGraph 中的接入方式

```python
from langgraph.graph import StateGraph, END
from agents.nlp_agent.run import nlp_node, should_run_nlp

workflow = StateGraph(AgentState)
workflow.add_node("orchestrator", orchestrator_node)
workflow.add_node("data_analysis", data_analysis_node)
workflow.add_node("visualization", visualization_node)
workflow.add_node("nlp", nlp_node)            # ← 新增独立节点
workflow.add_node("decision", decision_intelligence_node)

workflow.set_entry_point("orchestrator")
workflow.add_edge("orchestrator", "data_analysis")
workflow.add_edge("data_analysis", "visualization")
# 条件分支：仅在需要时触发 NLP
workflow.add_conditional_edges(
    "visualization",
    lambda s: "nlp" if should_run_nlp(s.get("question", ""), s.get("intent", "")) else "decision",
    {"nlp": "nlp", "decision": "decision"},
)
workflow.add_edge("nlp", "decision")
workflow.add_edge("decision", END)
```

也可独立使用：

```python
from agents.nlp_agent.run import ReviewInsightAgent

agent = ReviewInsightAgent(sample_size=2000)
state = {"question": "Top 10 差评品类的主要原因是什么？", "intent": "diagnostic"}
state = agent.run(state, on_tool_end=lambda t, p: print(t))
print(state["review_insights"])
```

---

## 5. CLI 用法

```bash
# 模式 A：直接跑工具，打印关键词洞察 JSON
python -m agents.nlp_agent.run --sample 200 --no-state

# 模式 B：模拟 LangGraph 流转（含路由判定）
python -m agents.nlp_agent.run \
    --question "Top 10 差评品类的主要原因是什么？" \
    --intent diagnostic \
    --sample 500
```

---

## 6. 词典维护

葡语关键词词典外置在 `config/nlp_agent/topic_keywords.yaml`：

- 修改文件后**无需改代码**，下次进程启动自动生效（运行中如需热更新可清除 `_load_topic_keywords` 的 `lru_cache`）
- 加载顺序：PyYAML（若装了）→ 内置极简 YAML 解析 → 兜底默认词典
- 维护建议：
  1. 新主题追加到列表末尾，避免改动既有顺序
  2. 关键词全部小写、避免与其它主题重叠
  3. 标签使用英文 snake_case，与下游决策报告对齐

---

## 7. 环境变量

复用 SQL Agent 的环境变量；本 Agent 不引入新变量：

| 变量 | 用途 |
|------|------|
| `AGENTIC_BI_DB_HOST/PORT/USER/PASSWORD/NAME` | NLP Agent 内部所有 SQL 工具的 MySQL 连接 |

### 数据库依赖

| 表 / 视图 | 来源 | NLP Agent 用途 |
|------|------|------|
| `order_reviews`（原始） | `utils/create_origin_table.sql` | 关键词主题、情感、词云、BERTopic 的输入源 |
| `order_items / products / sellers / customers / product_category_name_translation`（原始） | 同上 | 各工具按品类 / 卖家州 / 客户州下钻 |
| **`review_sentiment`**（NLP 自有） | **[`utils/create_review_sentiment_table.sql`](../../utils/create_review_sentiment_table.sql)** | 存放离线灌库的情感预测结果；`sentiment.py --backfill` 写入，`aggregate_sentiment()` 在线读 |
| **`review_topics` + `review_topic_meta`**（NLP 自有） | **[`utils/create_review_topics_table.sql`](../../utils/create_review_topics_table.sql)** | 存放 BERTopic 无监督主题模型结果；`topic_model.py --backfill` 写入，`aggregate_bertopic()` 在线读 |

> 灌库一次后，所有在线查询均为毫秒级。详细灌库命令见 §9。

---

## 8. 演进路线

| 阶段 | 文件 | 内容 |
|------|------|------|
| **P0**（已完成） | `tools/topic_keyword.py` | 葡语关键词主题分类（含主题 × 品类交叉表 `complaints_by_category`） |
| **P1**（已完成） | `tools/sentiment.py` + `review_sentiment` 表 | 葡语情感模型 `pysentimiento/bertweet-pt-sentiment` 离线灌库；在线聚合按品类 / 客户州 / 卖家州下钻 |
| **P2**（已完成） | `tools/wordcloud_data.py` + `config/nlp_agent/stopwords_pt.txt` | 好评 / 差评对比词云数据，对接 `viz_agent` |
| **P4**（已完成） | `tools/topic_model.py` + `review_topics` / `review_topic_meta` 表 | BERTopic 无监督主题（多语种 sentence-transformers + UMAP + HDBSCAN），跳出预设词典自动发现真实主题 |

---

## 9. 测试

### 9.1 完整能力可视化演示（推荐第一步）

```bash
.venv/bin/python tasks/nlp_demo.py
```

会顺序展示：
1. 抽 6 条评论看模型对单条文本的预测（评分 vs 模型预测对照）
2. 整体极性分布（POS/NEU/NEG 占比 + 加权平均）
3. `review_score × polarity` 交叉表（人工评分 × 模型预测一致性）
4. 最负面品类排行
5. 最负面客户州 / 卖家州排行
6. 主题 × 品类交叉表（差评原因下钻）
7. 好评 / 差评高频词对比（词云原始数据）
8. NLP Agent 完整 `run(state)` 一次跑通

### 9.2 单工具级 CLI

```bash
# 关键词主题分类（实时抽样）
python -m agents.nlp_agent.tools.topic_keyword

# 情感聚合（读 review_sentiment 表，毫秒级）
python -m agents.nlp_agent.tools.sentiment --aggregate

# 情感离线灌库（首次 ~7 分钟，下载 ~500MB 模型；MPS GPU 加速）
python -m agents.nlp_agent.tools.sentiment --backfill
python -m agents.nlp_agent.tools.sentiment --backfill --limit 200   # 试水

# BERTopic 主题建模聚合（读 review_topics 表，毫秒级）
python -m agents.nlp_agent.tools.topic_model --aggregate

# BERTopic 离线训练 + 灌库（首次 ~1 分钟，下载 ~120MB embedding 模型）
python -m agents.nlp_agent.tools.topic_model --backfill --min-topic-size 30

# 好评 / 差评对比词云数据
python -m agents.nlp_agent.tools.wordcloud_data --top 80 --pos-sample 4000 --neg-sample 4000

# Agent 入口
python -m agents.nlp_agent.run --sample 500 --no-state
python -m agents.nlp_agent.run --question "Top 10 差评品类的主要原因？" --intent diagnostic
```

### 9.3 路由判定（无需 MySQL）

```python
from agents.nlp_agent.run import should_run_nlp

assert should_run_nlp("Top 10 差评品类的原因？", "diagnostic") is True
assert should_run_nlp("2017 年 GMV 是多少？", "descriptive") is False
```

### 9.4 关键词分类准确率人工抽检

```python
from agents.nlp_agent import db
from agents.nlp_agent.tools.topic_keyword import _NEG_REVIEW_SQL, _classify_topic

for r in db.query(_NEG_REVIEW_SQL, (30,)):
    msg = (r.get("review_comment_message") or "").strip()
    if msg:
        print(f"[{_classify_topic(msg)}]\t{msg[:80]}")
```

人眼抽检 30 条葡语评论，主题命中率 ≥ 70% 视为基线达标。
