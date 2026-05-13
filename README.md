# Agentic BI-Driven Multi-Table E-Commerce Operations Analysis and Decision Intelligence System

Agentic BI 驱动的多表电商运营分析与决策智能系统

## 快速开始

- 前置条件
  - python >= 3.11
  - conda
- 创建虚拟环境

```bash
conda create -n agentic_bi python=3.11 -y

conda activate agentic_bi
```

- 安装依赖

```bash
git clone https://github.com/ycc250303/Agentic-BI-Driven-Multi-Table-E-Commerce-Operations-Analysis-and-Decision-Intelligence-System.git

cd Agentic-BI-Driven-Multi-Table-E-Commerce-Operations-Analysis-and-Decision-Intelligence-System

pip install -r requirements.txt
```

- 设置环境变量

```bash
export DEEPSEEK_API_KEY='your_api_key'
export AGENTIC_BI_DB_HOST='your_db_host'
export AGENTIC_BI_DB_PORT='3306'
export AGENTIC_BI_DB_NAME='your_database_name'
export AGENTIC_BI_DB_USER='your_database_user_name'
export AGENTIC_BI_DB_PASSWORD='your_database_password'
# 可选：可视化 PNG 输出目录（默认 agents/viz_agent/chart_output）
# export AGENTIC_BI_VIZ_DIR='/path/to/charts'
```

## 可视化 Agent（作业要求）

- **位置**：`agents/viz_agent/`，提示词：`config/visualization_agent/plan_chart.md`。
- **作用**：读取数据分析 Agent 写入的 **CSV**（及 `execute_sql` JSON 中的 **列画像**），调用 **DeepSeek**（与 `agents/sql_agent` 同源 `get_llm()`）输出结构化 **VizPlan**，再生成 **折线 / 柱状 / 热力 / 地理散点 / 散点 / 词云** 等 PNG。
- **详细用法与输入输出字段**：见 [`agents/viz_agent/readme.md`](agents/viz_agent/readme.md)。
- **快速串联（NL → SQL → 图）**：在代码中调用 `run_sql_then_visualize(user_query)`（需数据库与 API Key）；仅画图调试可用  
  `python agents/viz_agent/run.py --csv <结果.csv> --query "<问题>" --no-llm`。

