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

- **位置**：`agents/viz_agent/`
- **智能流程**：SQL 分析完成后 → `viz_planner` 根据**用户问题 + 已有查数结果**规划需要几张图、从哪取数 → `intelligent_viz` 按需复用 SQL / 追加查数 / 词云并渲染
- **不会**固定生成 8 张图；纯数值问题可跳过可视化
- **详细用法**：见 [`agents/viz_agent/readme.md`](agents/viz_agent/readme.md)
- **调试全套模板图**（非协调器默认）：`python agents/viz_agent/run.py --dashboard`
- **NL → SQL → 智能出图**：`python -m agents.coordinator_agent.run --query "<问题>"`
