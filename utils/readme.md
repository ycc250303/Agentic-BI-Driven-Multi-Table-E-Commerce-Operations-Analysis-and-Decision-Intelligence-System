# utils — 数据库初始化与辅助脚本

本目录存放 Olist 原始表 / NLP 衍生表 / 预聚合视图的 **DDL + 灌库入口**，以及预聚合性能基准。Agentic BI 各 Agent 均依赖此处准备的数据层。

## 前置条件

1. 已安装项目依赖（`pip install -r requirements.txt`；离线 NLP 灌库另装 `requirements-nlp.txt`）
2. 已配置 `AGENTIC_BI_DB_HOST` / `PORT` / `NAME` / `USER` / `PASSWORD`（根目录 `.env` 或 shell 导出）
3. 原始 CSV 在 `data/`（9 个文件对应 9 张原始表）

本地 MySQL 也可通过 [`deploy/readme.md`](../deploy/readme.md) 用 Docker 启动。

## 推荐执行顺序

```bash
# 建库 + 原始表 CSV 导入 + 刷新 6 个预聚合视图
python utils/setup.py

# 等价于分步：
python utils/setup.py init
python utils/setup.py load
python utils/setup.py views
```

**可选（NLP Agent 离线灌库前需先建表）：**

```bash
python utils/setup.py nlp-tables
python -m agents.nlp_agent.tools.sentiment --backfill
python -m agents.nlp_agent.tools.topic_model --backfill
```

`nlp-tables` 会 `DROP` 情感/主题表，已灌数据需重新 backfill。

**只重修翻译表**（71 行，不动其余表）：

```bash
python utils/setup.py translation
```

CSV 带 UTF-8 BOM，加载一律 `utf-8-sig`。全量 `load` 后会断言翻译表为 71 行。

**可选（性能对比）：**

```bash
python utils/benchmark_preagg_vs_raw.py
python utils/benchmark_preagg_vs_raw.py --warmup 1 --runs 5 --out docs/figures/preagg_benchmark.png
```

## 数据层关系

```
data/*.csv
    │
    ▼
utils/setup.py load  ──►  schema.sql @section origin  ──►  9 张原始表
    │
    ▼
utils/setup.py views ──►  schema.sql @section views   ──►  6 个预聚合视图 (mv_*)
    │
    ▼
SQL / Viz / Decision Agent 查询

utils/setup.py nlp-tables ──► schema.sql @section nlp
    → review_sentiment, review_topics, review_topic_meta
```

当前目录文件：

| 文件 | 作用 |
|------|------|
| `setup.py` | 唯一入口：`init` / `load` / `views` / `nlp-tables` / `translation` |
| `schema.sql` | 全部 DDL，按 `-- @section origin \| nlp \| views` 分段 |
| `benchmark_preagg_vs_raw.py` | 预聚合 vs 原始 JOIN 耗时对比 |
| `readme.md` | 本说明 |

---

## `setup.py`

| 子命令 | 做什么 | 会否丢数据 |
|--------|--------|------------|
| （默认）`all` | `init` + `load` + `views` | `load` 会 DROP 9 张原始表 |
| `init` | `CREATE DATABASE IF NOT EXISTS` | 否 |
| `load` | 执行 origin DDL，从 `data/` 批量 `INSERT IGNORE` | DROP 原始表；**不碰** NLP 表 |
| `views` | DROP/CREATE 6 个 `mv_*` | 否（视图） |
| `nlp-tables` | DROP/CREATE 情感与主题表 | 清空 NLP 灌库结果 |
| `translation` | `DELETE` + 插入 71 行翻译 | 只动翻译表 |

`load` 对评论/地理的主键重复会静默跳过（评论约 −814 行，地理去重到约 72 万唯一坐标），这是源数据口径，不是少导。

CSV → 表映射：

| 目标表 | CSV |
|--------|-----|
| `orders` | `olist_orders_dataset.csv` |
| `order_items` | `olist_order_items_dataset.csv` |
| `products` | `olist_products_dataset.csv` |
| `customers` | `olist_customers_dataset.csv` |
| `sellers` | `olist_sellers_dataset.csv` |
| `payments` | `olist_order_payments_dataset.csv` |
| `order_reviews` | `olist_order_reviews_dataset.csv` |
| `geolocation` | `olist_geolocation_dataset.csv` |
| `product_category_name_translation` | `product_category_name_translation.csv` |

## `schema.sql`

- **origin**：9 张业务表，主键与常用索引；二级索引不重复主键左前缀。
- **nlp**：`review_sentiment`（与评论 1:1）；`review_topics` + `review_topic_meta`（BERTopic）。
- **views**：6 个 `CREATE VIEW`（非物化表，随基表变化）。

| 视图 | 粒度 | 典型用途 |
|------|------|----------|
| `mv_monthly_sales` | 年-月 | 月度 GMV、订单量、客单价 |
| `mv_state_sales` | 年-月-州 | 各州销售排名 |
| `mv_category_sales` | 年-月-品类 | 品类表现 |
| `mv_delivery_perf` | 年-月-州 | 配送天数、准时率 |
| `mv_seller_perf` | 年-月-卖家 | 卖家 GMV 与平均评分 |
| `mv_payment_dist` | 年-月-支付类型 | 支付方式与分期 |

视图元数据见 [`config/view_metadata.json`](../config/view_metadata.json) 与 [`docs/README_VIEWS.md`](../docs/README_VIEWS.md)。变更 DDL 后须同步该文档与 SQL Agent Prompt。

## `benchmark_preagg_vs_raw.py`

同一分析语义下对比 `raw_join` / `raw_correlated` / `view`。运行前须已 `python utils/setup.py views`。

## 相关文档

| 文档 | 内容 |
|------|------|
| [项目 README](../README.md) | 快速开始 |
| [docs/README_VIEWS.md](../docs/README_VIEWS.md) | 预聚合视图 |
| [agents/nlp_agent/readme.md](../agents/nlp_agent/readme.md) | 情感 / 主题离线灌库 |
| [deploy/readme.md](../deploy/readme.md) | Docker 部署 MySQL |
