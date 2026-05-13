# 可视化 Agent（Visualize）

面向 **Agentic BI**：在数据分析 Agent 产出 **CSV + 列画像** 后，由 **大模型** 根据业务问题与数据结构选择图表类型（折线 / 柱状 / 热力 / 地理散点 / 散点 / 词云），并用 matplotlib / seaborn / wordcloud **渲染 PNG**。

---

## 1. 依赖与环境

- 与数据分析链路一致，需配置 **`DEEPSEEK_API_KEY`**（使用默认 LLM 规划图表时）。
- 可选：`AGENTIC_BI_VIZ_DIR` — 指定 PNG 输出目录；默认 `agents/viz_agent/chart_output/`。

---

## 2. 对外入口

| 函数 | 说明 |
|------|------|
| `run_visualization_agent(...)` | 主入口：输入业务问题 + `execute_sql_json` 或 `csv_path`，返回结构化 dict。 |
| `plan_with_llm(...)` | 仅调用 LLM 得到 `VizPlan`（便于单独测试）。 |
| `heuristic_plan(df, user_query)` | 不调用 LLM 的兜底选型（字段规则 + 关键词）。 |
| `run_sql_then_visualize(user_query, ...)` | 串联 `sql_agent` 全链路后再可视化（需数据库）。 |

Python 导入示例（需在路径中包含包或通过 `sys.path` 加载 `agents/viz_agent`，与运行 `sql_agent` 方式一致）：

```python
from pathlib import Path
import sys
sys.path.insert(0, str(Path("agents/viz_agent").resolve()))
from run import run_visualization_agent, run_sql_then_visualize
```

---

## 3. `run_visualization_agent` 参数

| 参数 | 类型 | 说明 |
|------|------|------|
| `user_query` | `str` | 用户业务问题，用于指导图表类型与语义标题。 |
| `execute_sql_json` | `str \| None` | **`execute_sql_tool` 返回的完整 JSON 字符串**。要求 `ok=true`，内含 `result_csv_path`、`column_profiles`、`data_summary_zh`。 |
| `csv_path` | `str \| Path \| None` | 直接指定查询结果 CSV；无列画像时 LLM 仍可根据表头与样本推断。 |
| `model` | 可选 | 传入自定义 LangChain Chat 模型；默认 `sql_agent.llm.get_llm()`（DeepSeek）。 |
| `use_llm` | `bool`，默认 `True` | `False` 时仅用 `heuristic_plan`，无需 API Key（适合离线联调）。 |
| `output_dir` | `Path \| None` | 覆盖 PNG 输出目录。 |

**注意**：`execute_sql_json` 与 `csv_path` 至少提供一个。

---

## 4. 返回 dict 字段（`VisualizationAgentOutput`）

| 字段 | 说明 |
|------|------|
| `ok` | 是否成功生成图片。 |
| `error_message` | 失败时的中文原因。 |
| `user_query` | 传入的业务问题。 |
| `csv_path` | 使用的 CSV 绝对路径。 |
| `plan` | `VizPlan`：`chart_type`、`title`、各列映射、`reasoning`。 |
| `plan_raw_json` | LLM 原始 JSON 或序列化后的规划（便于调试）。 |
| `image_path` | 生成的 **PNG 绝对路径**。 |
| `chart_type_resolved` | 最终图表类型枚举字符串。 |

支持的 `chart_type`：`line`、`bar`、`heatmap`、`scatter`、`geo_scatter`、`wordcloud`。约束说明见 `config/visualization_agent/plan_chart.md`。

---

## 5. 命令行

在项目根目录：

```bash
# 仅可视化已有 CSV（无 LLM）
python agents/viz_agent/run.py --csv path/to/result.csv --query "各州销售额对比" --no-llm

# 使用 execute_sql 的 JSON 文件（通常内含列画像，利于 LLM）
python agents/viz_agent/run.py --execute-json path/to/exec.json --query "支付方式分布"
```

---

## 6. 与数据分析 Agent 串联

```python
from run import run_sql_then_visualize

out = run_sql_then_visualize("2017 年各月 GMV 趋势如何？", use_llm=True)
# out["sql_pipeline"] — 与 sql_agent 流水线输出一致
# out["visualization"] — 本节所述可视化输出 dict
```

---

## 7. 改进方向（可选）

- 与 LangGraph 协调器对接：在 SQL 节点后自动挂载可视化节点。
- 地理「州级」底图需 shapefile 或 GeoPandas 时再扩展；当前 `geo_scatter` 为经纬度散点。
