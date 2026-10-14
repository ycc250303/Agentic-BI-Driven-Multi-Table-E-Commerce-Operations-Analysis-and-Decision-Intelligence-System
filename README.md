# Agentic BI 驱动的多表电商运营分析与决策智能系统

面向电商运营分析与决策支持：用自然语言完成跨表指标统计、原因下钻与趋势观察，并按需输出图表与可落地的运营建议。

![Python](https://img.shields.io/badge/Python-3.11+-3776AB)
![LangChain](https://img.shields.io/badge/LangChain-1.4-1C3C3C)
![LangGraph](https://img.shields.io/badge/LangGraph-1.2-1C3C3C)
![MySQL](https://img.shields.io/badge/MySQL-8-4479A1)
![License](https://img.shields.io/badge/License-MIT-yellow)

---

## 项目介绍

本系统基于巴西 [Olist](https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce) 电商公开数据（约 11 万订单、9 张业务表，2016–2018），支持描述、诊断、预测与决策类分析。

它针对三类常见痛点：

- 非技术人员难以直接查询多表关联数据
- 传统看板只能被动看数，无法按问题动态分析
- 诊断结论与运营建议缺乏可核对的上游证据

业务人员可以这样提问：「2017 年哪个州的销售额最高？」「人们对某品类的评价如何，入行是否有前景？」「那 SP 州呢？」

此前实现的说明与运行方式见 [`README_legacy.md`](README_legacy.md)，代码在 `legacy/`。

---

## 技术栈

| 技术 | 版本 | 说明 |
| --- | --- | --- |
| Python | ≥ 3.11 | 运行时 |
| LangChain | 1.4 | LLM 调用与结构化输出 |
| LangGraph | 1.2 | 状态图 |
| DeepSeek / 通义千问 | deepseek-v4-flash / qwen3.8-max | 默认与可选模型 |
| MySQL | 8.0 | 业务库 |
| PyMySQL | 1.2 | 数据库访问 |
| Pydantic | 2.13 | 结构化契约 |

---

## 使用场景

| 角色 | 可以做什么 |
| --- | --- |
| 运营 / 分析 | 用自然语言查 GMV、州排名、品类趋势、配送准时率、支付结构 |
| 品类 / 商家运营 | 结合差评主题与评分，看问题集中在物流、品质还是履约 |
| 决策支持 | 在查数与评论证据齐备后，要改进建议或有限的 What-if 推演 |

示例问题：

- 2017 年哪个州的销售额最高？交付准时率是多少？
- 哪些品类近期在下滑？差评主要集中在什么主题？
- 如果缩短配送时长，准时率大概会怎么变？

---

## 快速开始

除进入 MySQL 的命令在数据库服务器上执行外，其余命令在仓库根目录执行。`.env`、密码和 API Key 不要提交。

### 1. 安装依赖

需要 Python 3.11 及以上、3.14 以下。

```bash
conda create -n agentic_bi python=3.11 -y
conda activate agentic_bi
pip install -e '.[dev]'
```

离线评论灌库再执行 `pip install -e '.[nlp]'`。

把 Olist 的 9 个 CSV 放到 `data/`。表与文件的对应关系见 [`utils/readme.md`](utils/readme.md)。

安装后可先确认代码检查通过：

```bash
ruff check src tests
ruff format --check src tests
mypy src
pytest tests/unit -q
```

### 2. 配置环境变量

```bash
cp .env.example .env
```

按实际环境填写 `.env`。连接池、超时和模型名可以保持示例文件中的默认值。

| 变量 | 用途 |
| --- | --- |
| `AGENTIC_BI_LLM_PROVIDER` | 模型提供商，`deepseek` 或 `qwen` |
| `AGENTIC_BI_DEEPSEEK_MODEL` / `AGENTIC_BI_QWEN_MODEL` | 当前提供商的模型名。语义解析、SQL 生成和摘要共用 |
| `DEEPSEEK_API_KEY` | DeepSeek Key。默认提供商为 deepseek 时，调用模型前填写 |
| `DASHSCOPE_API_KEY` | 通义千问 Key。`AGENTIC_BI_LLM_PROVIDER=qwen` 时填写 |
| `AGENTIC_BI_DB_HOST` | MySQL 服务器地址 |
| `AGENTIC_BI_DB_PORT` | MySQL 端口，示例为 `3306` |
| `AGENTIC_BI_DB_NAME` | 库名，`agentic_bi` |
| `AGENTIC_BI_DB_USER` / `AGENTIC_BI_DB_PASSWORD` | 维护账号。`utils/setup.py` 用它建表和灌库 |
| `AGENTIC_BI_DB_READONLY_USER` / `AGENTIC_BI_DB_READONLY_PASSWORD` | 只读账号。创建账号前先写入，在线查数只使用这一对 |
| `AGENTIC_BI_DB_ADMIN_USER` / `AGENTIC_BI_DB_ADMIN_PASSWORD` | 可选。创建只读账号时优先使用；不填则使用维护账号 |
| `LANGSMITH_TRACING` / `LANGSMITH_API_KEY` | 可选。追踪默认关闭；设为 `true` 时必须填写 Key |

### 3. 在服务器创建数据库和用户

在数据库服务器上进入 MySQL。管理员账号不是 `root` 时，换成实际账号：

```bash
mysql -h 127.0.0.1 -P 3306 -u root -p
```

先建库并创建维护账号，再授予建表、灌库和创建其他账号所需的权限。账号名、库名和密码换成 `.env` 中的值：

```sql
CREATE DATABASE IF NOT EXISTS `agentic_bi`
  DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;

CREATE USER IF NOT EXISTS 'agentic_bi'@'%' IDENTIFIED BY '维护账号密码';
GRANT CREATE USER ON *.* TO 'agentic_bi'@'%';
GRANT ALL PRIVILEGES ON `agentic_bi`.* TO 'agentic_bi'@'%' WITH GRANT OPTION;
FLUSH PRIVILEGES;
```

`CREATE USER` 允许这个账号继续创建只读账号。`ALL PRIVILEGES ... WITH GRANT OPTION` 允许它在目标库建表、写入、创建视图，并把 `SELECT`、`SHOW VIEW` 授给只读账号。

### 4. 建表并导入数据

回到仓库根目录，用维护账号建表：

```bash
python utils/setup.py
```

这一步导入 9 张原始表，并刷新 6 个预聚合视图。NLP 表另建：

```bash
python utils/setup.py nlp-tables
```

该命令会删除并重建 `review_sentiment`、`review_topics`、`review_topic_meta`。已有的情感和主题数据会被清空，评论分析结果需要另外灌入。

### 5. 创建只读账号

在线查数使用只读账号。创建脚本优先用 `AGENTIC_BI_DB_ADMIN_USER` 登录；未设置时使用刚创建的维护账号。

`--host-pattern` 填写允许连入的客户端地址，例如运行 Agent 的那台机器的公网地址。填写数据库服务器地址时，只读账号只能在服务器本机登录。省略时默认为 `localhost`。`%` 只用于临时验证。

```bash
python utils/create_readonly_user.py --host-pattern '<客户端来源地址>'
```

脚本会创建 `.env` 中的 `AGENTIC_BI_DB_READONLY_USER`，并授予目标库的 `SELECT` 和 `SHOW VIEW`。维护账号仍缺少建用户权限时，脚本会打印可由管理员在上面的 MySQL 会话中执行的 SQL。

## 注意事项

`deepseek-v4-flash` 默认开启思考。数据分析的语义解析、SQL 生成和摘要都使用 `function_calling`，请求里带 `tool_choice`。思考模式不支持 `tool_choice`，接口返回 HTTP 400：`Thinking mode does not support this tool_choice`。

`AGENTIC_BI_LLM_THINKING_ENABLED=false` 只表示不要主动打开思考。关闭思考必须在请求体里显式传入 `{"thinking": {"type": "disabled"}}`。省略 `extra_body` 时，模型仍按默认开启思考。结构化调用固定传 `disabled`；自由文本只在该开关为真时传 `enabled`。

这次失败出现在 `interpret_request`。图节点把 400 收成 `model_unavailable`，文案是「语义解析模型暂时不可用」，`context` 为空。排查时要看模型接口的原始错误。

## 许可证

[MIT License](LICENSE)
