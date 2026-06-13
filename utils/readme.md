# utils — 数据库初始化与辅助脚本

本目录存放 **Olist 电商原始数据** 的建表、导入、预聚合视图，以及 NLP Agent 衍生表的 DDL 与性能基准脚本。Agentic BI 各 Agent（SQL / Viz / NLP / Decision）均依赖此处准备的数据层。

## 前置条件

1. 已安装项目依赖（`pip install -r requirements.txt`）
2. 已配置数据库环境变量（项目根目录 `.env` 或 shell 导出均可）：

| 变量 | 说明 |
|------|------|
| `AGENTIC_BI_DB_HOST` | MySQL 主机 |
| `AGENTIC_BI_DB_PORT` | 端口（通常 `3306`） |
| `AGENTIC_BI_DB_NAME` | 目标库名 |
| `AGENTIC_BI_DB_USER` | 用户名 |
| `AGENTIC_BI_DB_PASSWORD` | 密码 |

3. 原始 CSV 已放在项目根目录 `data/` 下（Olist 公开数据集，共 9 张表对应 9 个 CSV）

本地 MySQL 也可通过 [`deploy/readme.md`](../deploy/readme.md) 用 Docker 启动。

## 推荐执行顺序

```bash
# 1. 创建目标数据库（若尚不存在）
python utils/init_database.py

# 2. 建原始表 + 批量导入 CSV
python utils/load_data_to_mysql.py

# 3. 创建 / 刷新 6 个预聚合视图
python utils/refresh_views.py
```

**可选（NLP Agent 离线灌库前需先建表）：**

```bash
# 在 MySQL 客户端或任意 SQL 工具中执行
mysql ... < utils/create_review_sentiment_table.sql
mysql ... < utils/create_review_topics_table.sql

# 然后由 NLP Agent 灌库（见 agents/nlp_agent/readme.md）
python -m agents.nlp_agent.tools.sentiment --backfill
python -m agents.nlp_agent.tools.topic_model --backfill
```

**可选（性能对比 / 报告配图）：**

```bash
python utils/benchmark_preagg_vs_raw.py
python utils/benchmark_preagg_vs_raw.py --warmup 1 --runs 5 --out docs/figures/preagg_benchmark.png
```

## 数据层关系概览

```
data/*.csv
    │
    ▼
load_data_to_mysql.py  ──►  create_origin_table.sql  ──►  9 张原始表
    │                              orders, order_items, products,
    │                              customers, sellers, payments,
    │                              order_reviews, geolocation,
    │                              product_category_name_translation
    │
    ▼
refresh_views.py  ──►  create_materialized_views.sql  ──►  6 个预聚合视图 (mv_*)
    │
    ▼
SQL / Viz / Decision Agent 查询

NLP 衍生表（独立 DDL，需离线灌库）：
  create_review_sentiment_table.sql  →  review_sentiment
  create_review_topics_table.sql     →  review_topics, review_topic_meta
```

---

## Python 脚本

### `init_database.py`

连接 MySQL **服务端**（不预先指定 database），创建 `AGENTIC_BI_DB_NAME` 指定的库（`utf8mb4` / `utf8mb4_0900_ai_ci`），并执行 `USE`。仅负责「库是否存在」，不建表、不导数据。

### `load_data_to_mysql.py`

数据导入主脚本，完成两件事：

1. 执行 `create_origin_table.sql`（代码内路径为 `origin_table.sql`，与磁盘文件名 `create_origin_table.sql` 对应同一脚本）
2. 从 `data/` 读取 9 个 CSV，按表配置做类型转换后 **批量 `INSERT IGNORE`** 入库（每批 5000 行，主键重复自动跳过）

| 目标表 | CSV 文件 |
|--------|----------|
| `orders` | `olist_orders_dataset.csv` |
| `order_items` | `olist_order_items_dataset.csv` |
| `products` | `olist_products_dataset.csv` |
| `customers` | `olist_customers_dataset.csv` |
| `sellers` | `olist_sellers_dataset.csv` |
| `payments` | `olist_order_payments_dataset.csv` |
| `order_reviews` | `olist_order_reviews_dataset.csv` |
| `geolocation` | `olist_geolocation_dataset.csv` |
| `product_category_name_translation` | `product_category_name_translation.csv` |

### `refresh_views.py`

读取 `create_materialized_views.sql`，逐条执行 `DROP VIEW` / `CREATE VIEW`，并在完成后：

- 统计各视图行数
- 列出库中全部 VIEW

供 SQL Agent 与协调器在常见分析场景下走预聚合层，避免每次对原始大表做多表 JOIN 聚合。

### `benchmark_preagg_vs_raw.py`

对比 **同一分析语义** 下三种查询方式的耗时：

| 模式 | 说明 |
|------|------|
| `raw_join` | 与视图定义等价的多表 JOIN + GROUP BY |
| `raw_correlated` | 相关子查询写法（更慢，用于放大差异） |
| `view` | `SELECT * FROM mv_*` |

覆盖 6 个视图各一组场景，可导出 PNG 柱状图与可选 JSON 原始计时。运行前须已完成 `refresh_views.py`。

---

## SQL 脚本

### `create_origin_table.sql`

Olist **原始业务表** DDL：先 `DROP` 再 `CREATE` 共 9 张表，含主键、常用查询索引及字段中文注释。被 `load_data_to_mysql.py` 在导入前自动执行。

| 表名 | 说明 |
|------|------|
| `orders` | 订单主表 |
| `order_items` | 订单明细（商品行） |
| `products` | 商品属性 |
| `customers` | 客户与所在州 |
| `sellers` | 卖家与所在州 |
| `payments` | 支付记录 |
| `order_reviews` | 订单评论（NLP 主要输入） |
| `geolocation` | 邮编 → 经纬度 |
| `product_category_name_translation` | 葡语类目 → 英文 |

### `create_materialized_views.sql`

定义 **6 个预聚合视图**（MySQL `CREATE VIEW`，非物化表；数据随基表变化实时反映）：

| 视图 | 粒度 | 典型用途 |
|------|------|----------|
| `mv_monthly_sales` | 年-月 | 月度 GMV、订单量、客单价 |
| `mv_state_sales` | 年-月-州 | 各州销售排名、区域对比 |
| `mv_category_sales` | 年-月-品类 | 品类表现、下滑品类识别 |
| `mv_delivery_perf` | 年-月-州 | 配送天数、准时率 |
| `mv_seller_perf` | 年-月-卖家 | 卖家 GMV 与平均评分 |
| `mv_payment_dist` | 年-月-支付类型 | 支付方式与分期分布 |

视图元数据供 Agent 匹配查询，详见 [`config/view_metadata.json`](../config/view_metadata.json) 与 [`docs/README_VIEWS.md`](../docs/README_VIEWS.md)。

### `create_review_sentiment_table.sql`

NLP Agent **情感分析结果表** DDL（`review_sentiment`）。与 `order_reviews` 通过 `review_id` 1:1 关联；由 `python -m agents.nlp_agent.tools.sentiment --backfill` 离线写入，在线查询毫秒级聚合。不修改任何原始表。

主要字段：`polarity`（POS/NEU/NEG）、`polarity_score`（pos_prob − neg_prob）、三分类概率、`model_name` 等。

### `create_review_topics_table.sql`

NLP Agent **BERTopic 主题建模** 双表 DDL：

| 表 | 说明 |
|----|------|
| `review_topics` | 每条差评 → `topic_id` 及置信度 |
| `review_topic_meta` | 每个主题的 Top 关键词、样本量、人类可读标签 |

由 `python -m agents.nlp_agent.tools.topic_model --backfill` 离线训练并灌库。详细流程见 [`agents/nlp_agent/readme.md`](../agents/nlp_agent/readme.md)。

---

## 相关文档

| 文档 | 内容 |
|------|------|
| [项目 README](../README.md) | 快速开始与 Agent 入口 |
| [docs/README_VIEWS.md](../docs/README_VIEWS.md) | 预聚合视图详细说明与 Agent 用法 |
| [agents/nlp_agent/readme.md](../agents/nlp_agent/readme.md) | 情感 / 主题离线灌库与在线查询 |
| [deploy/readme.md](../deploy/readme.md) | Docker 部署 MySQL |
