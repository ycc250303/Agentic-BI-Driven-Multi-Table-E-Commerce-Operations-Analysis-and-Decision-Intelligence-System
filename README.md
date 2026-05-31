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

- 设置环境变量（项目根目录的 `.env` 若包含 `DEEPSEEK_API_KEY` 及 `AGENTIC_BI_DB_*`，从项目根执行下方 Python 命令时，`get_llm()` 会先加载该文件写入进程环境，`execute_sql` 即可读到数据库配置；也可仅用 PowerShell 的 `$env:...=` 逐项设置）

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

或者使用 `.env`

- 导入数据

```bash
python utils/init_database.py
python utils/load_data_to_mysql.py
python utils/refresh_views.py
```

## 协调器 Agent（多 Agent 编排）

- **位置**：`agents/coordinator_agent/`
- **作用**：拆分复合问题 → **迭代式**调度 sql / viz / nlp / decision → **LLM 撰写**最终回答
- **详细用法**：见 [`agents/coordinator_agent/readme.md`](agents/coordinator_agent/readme.md)

```bash
python -m agents.coordinator_agent.run --query "2017年哪个州的销售额最高？"
python -m agents.coordinator_agent.run --decompose-only --no-llm-plan --query "A？B？"
```

## 可视化 Agent（作业要求）

- **位置**：`agents/viz_agent/`，提示词：`config/visualization_agent/plan_chart.md`。
- **作用**：读取数据分析 Agent 写入的 **CSV**（及 `execute_sql` JSON 中的 **列画像**），调用 **DeepSeek**（与 `agents/sql_agent` 同源 `get_llm()`）输出结构化 **VizPlan**，再生成 **折线 / 柱状 / 热力 / 地理散点 / 散点 / 词云** 等 PNG。
- **详细用法与输入输出字段**：见 [`agents/viz_agent/readme.md`](agents/viz_agent/readme.md)。
- **快速串联（NL → SQL → 图）**：项目根目录执行  
  `python agents/viz_agent/run.py --sql-then-viz --query "<你的问题>"`（需 MySQL、`AGENTIC_BI_DB_*`、`DEEPSEEK_API_KEY`）；或在代码里调用 `run_sql_then_visualize(user_query)`。仅画图调试可用  
  `python agents/viz_agent/run.py --csv <结果.csv> --query "<问题>" --no-llm`。
