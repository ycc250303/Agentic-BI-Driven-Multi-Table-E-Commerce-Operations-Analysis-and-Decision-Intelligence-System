# Agentic BI 驱动的多表电商运营分析与决策智能系统

## 项目背景

随着大语言模型与多智能体技术的成熟，商业智能（BI）正从“被动看板”进化为“主动分析与决策引擎”——即 Agentic BI。

本项目基于巴西 Olist 电商公开数据集（约 11.2 万订单、9 张业务表、2016–2018 年），设计并实现一个多智能体协作的 BI 分析系统，使非技术业务人员能用自然语言提问，即时获得统计结论、可视化图表与可执行的商业建议。系统涵盖原始数据导入、预聚合视图加速、NL2SQL 数据分析、多 Agent 协调调度与 Web 页面交互等完整链路。

---

## 数据库设计

### 数据来源

数据集为 Kaggle 公开的 [Brazilian E-Commerce Public Dataset by Olist](https://www.kaggle.com/datasets/enzoschitini/brazilian-e-commerce-public-dataset-by-olist)，包含 9 张 CSV 业务表，对应订单、明细、商品、客户、卖家、支付、评论、地理坐标及品类翻译等主题域。

数据规模约 11.5 万行，时间跨度 2016 年 9 月至 2018 年 10 月，字段含葡萄牙语品类名与评论文本，需在分析层做翻译或编码处理。

| 业务主题 | 说明 |
| --- | --- |
| 订单主表 | 订单生命周期、下单与签收时间戳 |
| 订单明细 | 商品、卖家、成交价与运费 |
| 商品属性 | 品类、重量、尺寸等物理属性 |
| 客户 / 卖家 | 地域分布（城市、州） |
| 支付明细 | 支付方式、分期数、支付金额 |
| 评论评分 | 评分与文本评论 |
| 地理坐标 | 邮编前缀对应的经纬度 |
| 品类翻译 | 葡语品类名与英文对照 |

### ER 图

9 张原始表以订单 ID 为核心关联键，形成星型与雪花型混合结构：客户经订单关联明细，明细再关联商品与卖家；同一订单可关联支付记录与评论；地理信息通过邮编前缀与客户、卖家地域字段间接关联；品类翻译表与商品品类字段对应。

预聚合视图（月度销售、各州销售、品类销售、配送绩效、卖家绩效、支付分布等）建立在原始表之上，供数据分析 Agent 在匹配业务维度时优先使用。

### 物理表结构设计与字段说明

物理表采用 MySQL InnoDB 存储引擎，utf8mb4 字符集以支持葡语评论。各表按业务语义设置主键（含复合主键），在订单 ID、客户 ID、商品 ID、卖家 ID 等高频关联字段建立索引。金额字段采用定点小数，时间字段采用日期时间类型，标识字段采用变长字符串。

```sql
SET FOREIGN_KEY_CHECKS = 0;

DROP TABLE IF EXISTS geolocation;
DROP TABLE IF EXISTS payments;
DROP TABLE IF EXISTS order_reviews;
DROP TABLE IF EXISTS order_items;
DROP TABLE IF EXISTS orders;
DROP TABLE IF EXISTS products;
DROP TABLE IF EXISTS sellers;
DROP TABLE IF EXISTS customers;
DROP TABLE IF EXISTS product_category_name_translation;

SET FOREIGN_KEY_CHECKS = 1;

-- 1. 订单表
CREATE TABLE orders (
    order_id VARCHAR(32) NOT NULL COMMENT '订单ID',
    customer_id VARCHAR(32) NOT NULL COMMENT '客户ID',
    order_status VARCHAR(32) NOT NULL COMMENT '订单状态',
    order_purchase_timestamp DATETIME NULL COMMENT '下单时间戳',
    order_approved_at DATETIME NULL COMMENT '支付审批通过时间',
    order_delivered_carrier_date DATETIME NULL COMMENT '交付给承运商时间',
    order_delivered_customer_date DATETIME NULL COMMENT '客户签收时间',
    order_estimated_delivery_date DATETIME NULL COMMENT '预计送达时间',
    PRIMARY KEY (order_id)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_0900_ai_ci COMMENT = '订单主表';

CREATE INDEX idx_orders_order_id ON orders (order_id);
CREATE INDEX idx_orders_customer_id ON orders (customer_id);

-- 2. 订单项目表
CREATE TABLE order_items (
    order_id VARCHAR(32) NOT NULL COMMENT '订单ID',
    order_item_id INT NOT NULL COMMENT '订单内明细序号',
    product_id VARCHAR(32) NOT NULL COMMENT '产品ID',
    seller_id VARCHAR(32) NOT NULL COMMENT '商家ID',
    shipping_limit_date DATETIME NULL COMMENT '最晚发货时限',
    price DECIMAL(10, 2) NULL COMMENT '商品成交价格',
    freight_value DECIMAL(10, 2) NULL COMMENT '运费金额',
    PRIMARY KEY (order_id, order_item_id)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_0900_ai_ci COMMENT = '订单项目表';

CREATE INDEX idx_order_items_order_id ON order_items (order_id);
CREATE INDEX idx_order_items_product_id ON order_items (product_id);
CREATE INDEX idx_order_items_seller_id ON order_items (seller_id);
CREATE INDEX idx_order_items_shipping_limit_date ON order_items (shipping_limit_date);

-- 3. 产品表
CREATE TABLE products (
    product_id VARCHAR(32) NOT NULL COMMENT '产品ID',
    product_category_name VARCHAR(255) NOT NULL COMMENT '产品分类名称',
    product_name_lenght INT NOT NULL COMMENT '产品名称长度',
    product_description_lenght INT NOT NULL COMMENT '产品描述长度',
    product_photos_qty INT NOT NULL COMMENT '产品照片数量',
    product_weight_g INT NOT NULL COMMENT '产品重量(g)',
    product_length_cm INT NOT NULL COMMENT '产品长度(cm)',
    product_height_cm INT NOT NULL COMMENT '产品高度(cm)',
    product_width_cm INT NOT NULL COMMENT '产品宽度(cm)',
    PRIMARY KEY (product_id)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_0900_ai_ci COMMENT = '产品表';

CREATE INDEX idx_products_product_id ON products (product_id);
CREATE INDEX idx_products_product_category_name ON products (product_category_name);

-- 4. 客户表
CREATE TABLE customers (
    customer_id VARCHAR(32) NOT NULL COMMENT '客户ID',
    customer_unique_id VARCHAR(32) NOT NULL COMMENT '客户唯一ID',
    customer_zip_code_prefix INT NOT NULL COMMENT '客户邮编前缀',
    customer_city VARCHAR(255) NOT NULL COMMENT '客户城市',
    customer_state VARCHAR(2) NOT NULL COMMENT '客户州',
    PRIMARY KEY (customer_id)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_0900_ai_ci COMMENT = '客户表';

CREATE INDEX idx_customers_customer_id ON customers (customer_id);
CREATE INDEX idx_customers_customer_unique_id ON customers (customer_unique_id);
CREATE INDEX idx_customers_customer_city ON customers (customer_city);
CREATE INDEX idx_customers_customer_state ON customers (customer_state);
CREATE INDEX idx_customers_customer_city_state ON customers (customer_city, customer_state);

-- 5. 商家表
CREATE TABLE sellers (
    seller_id VARCHAR(32) NOT NULL COMMENT '商家ID',
    seller_zip_code_prefix INT NOT NULL COMMENT '商家邮编前缀',
    seller_city VARCHAR(255) NOT NULL COMMENT '商家城市',
    seller_state VARCHAR(2) NOT NULL COMMENT '商家州',
    PRIMARY KEY (seller_id)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_0900_ai_ci COMMENT = '商家表';

CREATE INDEX idx_sellers_seller_id ON sellers (seller_id);
CREATE INDEX idx_sellers_seller_city ON sellers (seller_city);
CREATE INDEX idx_sellers_seller_state ON sellers (seller_state);
CREATE INDEX idx_sellers_seller_city_state ON sellers (seller_city, seller_state);

-- 6. 支付表
CREATE TABLE payments (
    order_id VARCHAR(32) NOT NULL COMMENT '订单ID',
    payment_sequential INT NOT NULL COMMENT '支付序号',
    payment_type VARCHAR(255) NOT NULL COMMENT '支付方式',
    payment_installments INT NOT NULL COMMENT '支付分期数',
    payment_value DECIMAL(10, 2) NOT NULL COMMENT '支付金额',
    PRIMARY KEY (order_id, payment_sequential)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_0900_ai_ci COMMENT = '支付表';

CREATE INDEX idx_payments_order_id_payment_sequential ON payments (order_id, payment_sequential);

-- 7. 评论表
CREATE TABLE order_reviews (
    review_id VARCHAR(32) NOT NULL COMMENT '评论ID',
    order_id VARCHAR(32) NOT NULL COMMENT '订单ID',
    review_score INT NOT NULL COMMENT '评论评分',
    review_comment_title VARCHAR(255) NOT NULL COMMENT '评论标题',
    review_comment_message TEXT NOT NULL COMMENT '评论内容',
    review_creation_date DATETIME NOT NULL COMMENT '评论时间',
    review_answer_timestamp DATETIME NOT NULL COMMENT '评论回答时间',
    PRIMARY KEY (review_id)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_0900_ai_ci COMMENT = '评论表';

CREATE INDEX idx_order_reviews_review_id ON order_reviews (review_id);
CREATE INDEX idx_order_reviews_order_id ON order_reviews (order_id);

-- 8. 地理位置表
CREATE TABLE geolocation (
    geolocation_zip_code_prefix INT NOT NULL COMMENT '地理位置邮编前缀',
    geolocation_lat DECIMAL(10, 6) NOT NULL COMMENT '地理位置纬度',
    geolocation_lng DECIMAL(10, 6) NOT NULL COMMENT '地理位置经度',
    geolocation_city VARCHAR(255) NOT NULL COMMENT '地理位置城市',
    geolocation_state VARCHAR(2) NOT NULL COMMENT '地理位置州',
    PRIMARY KEY (
        geolocation_zip_code_prefix,
        geolocation_lat,
        geolocation_lng
    )
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_0900_ai_ci COMMENT = '地理位置表';

CREATE INDEX idx_geolocation_city_state ON geolocation (
    geolocation_city,
    geolocation_state
);

-- 9. 产品类目翻译表
CREATE TABLE product_category_name_translation (
    product_category_name VARCHAR(255) NOT NULL COMMENT '产品类目名称',
    product_category_name_english VARCHAR(255) NOT NULL COMMENT '产品类目名称英文',
    PRIMARY KEY (product_category_name)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_0900_ai_ci COMMENT = '产品类目翻译表';

CREATE INDEX idx_pcnt_product_category_name ON product_category_name_translation (product_category_name);
CREATE INDEX idx_pcnt_product_category_name_english ON product_category_name_translation (product_category_name_english);
```

数据导入流程为：先执行建表脚本创建 9 张业务表，再按表结构逐文件读取 CSV，做类型转换与空值处理后分批写入，合计约 11.5 万行入库。部署上提供 Docker 化 MySQL 8.0 方案，支持数据持久化、健康检查与一键启停。

---

## 预聚合视图设计

### 具体 SQL 实现

系统共设计 6 张预聚合视图，全部定义在 `utils/create_materialized_views.sql`。所有视图使用 MySQL `CREATE VIEW` 创建为虚拟视图（非物化视图），查询时实时从基础表计算，因此天然反映最新数据。

#### `mv_monthly_sales` — 月度销售趋势

- **粒度：** 年-月
- **来源表：** `orders` INNER JOIN `order_items`
- **订单状态过滤：** `delivered`, `shipped`, `created`, `approved`, `processing`, `invoiced`

```sql
CREATE VIEW mv_monthly_sales AS
SELECT
    DATE_FORMAT(o.order_purchase_timestamp, '%Y-%m') AS `year_month`,
    SUM(oi.price + oi.freight_value) AS total_gmv,
    COUNT(DISTINCT o.order_id) AS total_orders,
    SUM(oi.price + oi.freight_value) / COUNT(DISTINCT o.order_id) AS avg_basket,
    SUM(oi.freight_value) AS total_freight
FROM orders o
INNER JOIN order_items oi ON o.order_id = oi.order_id
WHERE o.order_status IN ('delivered', 'shipped', 'created', 'approved', 'processing', 'invoiced')
GROUP BY DATE_FORMAT(o.order_purchase_timestamp, '%Y-%m');
```

**设计要点：**

- `total_gmv` 采用 `price + freight_value` 口径
- `avg_basket` 使用 `SUM / COUNT(DISTINCT order_id)` 确保跨商品行计算客单价正确
- 订单状态过滤涵盖所有非取消状态，匹配业务分析场景

#### `mv_state_sales` — 各州销售情况

- **粒度：** 年-月-客户州
- **来源表：** `orders` + `order_items` + `customers`

```sql
CREATE VIEW mv_state_sales AS
SELECT
    DATE_FORMAT(o.order_purchase_timestamp, '%Y-%m') AS `year_month`,
    c.customer_state,
    SUM(oi.price + oi.freight_value) AS total_gmv,
    COUNT(DISTINCT o.order_id) AS total_orders,
    COUNT(DISTINCT c.customer_unique_id) AS unique_customers
FROM orders o
INNER JOIN order_items oi ON o.order_id = oi.order_id
INNER JOIN customers c ON o.customer_id = c.customer_id
WHERE o.order_status IN ('delivered', 'shipped', 'created', 'approved', 'processing', 'invoiced')
GROUP BY DATE_FORMAT(o.order_purchase_timestamp, '%Y-%m'), c.customer_state;
```

**设计要点：**

- `unique_customers` 采用 `COUNT(DISTINCT customer_unique_id)` 而非 `customer_id`，去重同一客户的多笔订单
- 三表 JOIN 提前完成州维度的数据关联，避免 Agent 每次查询重复编写 JOIN

#### `mv_category_sales` — 品类销售情况

- **粒度：** 年-月-品类（英文名）
- **来源表：** `orders` + `order_items` + `products` + `product_category_name_translation`（LEFT JOIN）

```sql
CREATE VIEW mv_category_sales AS
SELECT
    DATE_FORMAT(o.order_purchase_timestamp, '%Y-%m') AS `year_month`,
    COALESCE(pct.product_category_name_english, p.product_category_name) AS product_category_english,
    SUM(oi.price) AS total_gmv,
    COUNT(DISTINCT oi.order_id) AS total_orders,
    AVG(oi.price) AS avg_price
FROM orders o
INNER JOIN order_items oi ON o.order_id = oi.order_id
INNER JOIN products p ON oi.product_id = p.product_id
LEFT JOIN product_category_name_translation pct ON p.product_category_name = pct.product_category_name
WHERE o.order_status IN ('delivered', 'shipped', 'created', 'approved', 'processing', 'invoiced')
GROUP BY DATE_FORMAT(o.order_purchase_timestamp, '%Y-%m'),
         COALESCE(pct.product_category_name_english, p.product_category_name);
```

**设计要点：**

- `product_category_name_translation` 使用 LEFT JOIN，`COALESCE` 优先取英文翻译，翻译缺失时回退原始葡萄牙语名
- 品类视图的 GMV 仅取 `oi.price`（不含运费），与月度销售视图的 GMV 口径不同

#### `mv_delivery_perf` — 配送绩效

- **粒度：** 年-月-客户州
- **来源表：** `orders` + `customers`
- **状态过滤：** 仅 `delivered` 状态（必须实际签收才能计算配送天数）

```sql
CREATE VIEW mv_delivery_perf AS
SELECT
    DATE_FORMAT(o.order_purchase_timestamp, '%Y-%m') AS `year_month`,
    c.customer_state,
    AVG(DATEDIFF(o.order_delivered_customer_date, o.order_purchase_timestamp)) AS avg_delivery_days,
    SUM(CASE WHEN o.order_delivered_customer_date <= o.order_estimated_delivery_date
             THEN 1 ELSE 0 END) * 1.0 / COUNT(*) AS on_time_rate,
    SUM(CASE WHEN o.order_delivered_customer_date > o.order_estimated_delivery_date
             THEN 1 ELSE 0 END) AS delayed_orders
FROM orders o
INNER JOIN customers c ON o.customer_id = c.customer_id
WHERE o.order_status = 'delivered'
  AND o.order_delivered_customer_date IS NOT NULL
GROUP BY DATE_FORMAT(o.order_purchase_timestamp, '%Y-%m'), c.customer_state;
```

**设计要点：**

- `on_time_rate` 是“月 × 州”单元内的比率，不是全平台订单级比率
- `delayed_orders` 是绝对延迟单数，按州简单 `SUM` 会被大州（如 SP）主导
- `order_delivered_customer_date IS NOT NULL` 过滤确保 `DATEDIFF` 不产生 NULL

#### `mv_seller_perf` — 卖家绩效

- **粒度：** 年-月-卖家-卖家所在州
- **来源表：** `orders` + `order_items` + `sellers`，`order_reviews`（LEFT JOIN）

```sql
CREATE VIEW mv_seller_perf AS
SELECT
    DATE_FORMAT(o.order_purchase_timestamp, '%Y-%m') AS `year_month`,
    s.seller_id,
    s.seller_state,
    SUM(oi.price + oi.freight_value) AS total_gmv,
    COUNT(DISTINCT oi.order_id) AS total_orders,
    AVG(r.review_score) AS avg_review_score
FROM orders o
INNER JOIN order_items oi ON o.order_id = oi.order_id
INNER JOIN sellers s ON oi.seller_id = s.seller_id
LEFT JOIN order_reviews r ON o.order_id = r.order_id
WHERE o.order_status IN ('delivered', 'shipped', 'created', 'approved', 'processing', 'invoiced')
GROUP BY DATE_FORMAT(o.order_purchase_timestamp, '%Y-%m'), s.seller_id, s.seller_state;
```

**设计要点：**

- `order_reviews` 使用 LEFT JOIN，确保无评论的订单也能纳入卖家 GMV / 订单量统计
- `avg_review_score` 对单月内卖家所有已关联评论取 `AVG()`，为粗粒度绩效快照

#### `mv_payment_dist` — 支付分布

- **粒度：** 年-月-支付类型
- **来源表：** `orders` + `payments`

```sql
CREATE VIEW mv_payment_dist AS
SELECT
    DATE_FORMAT(o.order_purchase_timestamp, '%Y-%m') AS `year_month`,
    p.payment_type,
    COUNT(DISTINCT p.order_id) AS total_transactions,
    AVG(p.payment_installments) AS avg_installments,
    SUM(p.payment_value) AS total_value
FROM orders o
INNER JOIN payments p ON o.order_id = p.order_id
WHERE o.order_status IN ('delivered', 'shipped', 'created', 'approved', 'processing', 'invoiced')
GROUP BY DATE_FORMAT(o.order_purchase_timestamp, '%Y-%m'), p.payment_type;
```

**设计要点：**

- `avg_installments` 是“月 × 支付类型”单元内均值。跨月汇总到支付方式时，必须使用交易笔数加权平均 `SUM(avg_installments * total_transactions) / SUM(total_transactions)`，不能直接 `AVG(avg_installments)`。

### 视图更新策略

#### 刷新机制：虚拟视图自动反映最新数据

所有 6 张视图使用 MySQL `CREATE VIEW`（虚拟视图）而非物化视图，不需要定期刷新数据。每次查询视图时，MySQL 实时从基础表（`orders`、`order_items`、`customers` 等）计算最新结果，天然保证数据一致性。

这意味着：

- 基础表数据更新后，视图查询立即反映最新数据
- 无需维护物化视图的刷新调度、增量更新或全量重建逻辑
- 代价是每次查询视图都执行一次完整的 JOIN + 聚合，但相比 Agent 每次都手写复杂的多表 JOIN SQL，视图将执行计划固化，避免 LLM 生成低效查询

#### 视图定义刷新脚本

当视图的 SQL 定义需要修改（如新增字段、调整口径）时，通过 `utils/refresh_views.py` 一键重建所有视图。

脚本流程：

1. **读取 SQL 文件：** 定位 `utils/create_materialized_views.sql`
2. **解析 SQL 语句：** 去除 `--` 注释行，按 `;` 分割为独立语句
3. **执行 DROP + CREATE：** 逐条执行，每条语句自动 commit，通过正则从 `CREATE VIEW` / `DROP VIEW` 文本中提取视图名并打印执行状态
4. **验证：** 对全部 6 个视图执行 `SELECT COUNT(*)` 确认存在并输出记录数
5. **清单输出：** 执行 `SHOW FULL TABLES WHERE TABLE_TYPE LIKE 'VIEW'` 列出数据库中所有现有视图

数据库连接：通过 `db_env.mysql_connector_config()` 读取 `.env` 中的 `AGENTIC_BI_DB_*` 环境变量建立连接。

### 性能对比

为验证预聚合视图相对原始多表 JOIN 的实际收益，项目在 MySQL 库上对 6 张视图逐一做了同口径耗时对比：一类 SQL 实时查询原始表；另一类直接从预聚合视图 `SELECT`。

我们对六个查询预聚合视图的场景分别去查询了一遍原始表，在数据量较大的情况下，得到最终结果如下所示：

| 视图 | 原始表 | 预聚合视图 | 加速比 |
| --- | ---: | ---: | ---: |
| `mv_monthly_sales`（月度销售） | 1336 ms | 26 ms | 51× |
| `mv_state_sales`（各州销售） | 4985 ms | 36 ms | 137× |
| `mv_category_sales`（品类销售） | 2777 ms | 69 ms | 40× |
| `mv_delivery_perf`（配送绩效） | 849 ms | 39 ms | 22× |
| `mv_seller_perf`（卖家绩效） | 8968 ms | 2911 ms | 3× |
| `mv_payment_dist`（支付分布） | 2117 ms | 37 ms | 58× |

从结果可见，除 `mv_seller_perf` 外，其余 5 个场景加速比在 22×～137× 之间。卖家绩效视图粒度为“年-月-卖家-州”，优化为预聚合视图后结果集行数仍较大，因此加速相对有限；而月度、州、品类、支付等聚合后行数少的场景，收益最为显著。

### Agent 如何利用预聚合视图

核心策略是**“视图优先，基础表兜底”**：SQL Agent 在生成 SQL 之前，先用 LLM 判断用户问题是否落在某张预聚合视图的维度内——命中就用视图名直接查，未命中才 JOIN 原始表。

这一判断在 `rewrite_to_query` 工具（`agents/sql_agent/tools/rewrite_to_query.py`）中完成。该工具将三份 Prompt 合并后发给 LLM：

- `system_core.md`：规定“先判断是否命中视图，命中则优先使用”
- `schema_dictionary.md`：列出全部 6 个视图的粒度、字段、用途及易错口径，LLM 据此判断问题属于哪个维度
- `rewrite_to_query_tool.md`：要求 LLM 输出结构化 JSON，含 `hit_pre_agg_view`（bool）和 `candidate_views`（候选视图列表，白名单严格限定为 6 个视图名）

LLM 返回后，`generate_sql` 工具（`agents/sql_agent/tools/generate_sql.py`）根据结果生成 SQL：`hit_pre_agg_view=true` 则 `FROM mv_xxx`，否则 JOIN 基础表。生成的 SQL 经语法校验后由 pymysql 执行。

以用户问“2017 年哪个州的销售额最高？”为例，LLM 识别到问题维度 = 州 + 销售额，命中 `mv_state_sales`，最终生成的 SQL 是：

```sql
SELECT customer_state, SUM(total_gmv)
FROM mv_state_sales
WHERE year_month BETWEEN '2017-01' AND '2017-12'
GROUP BY customer_state
```

而非 JOIN `orders` + `order_items` + `customers` 三张原始表。

**何时强制回退：** 部分场景使用视图会得出错误结论，因为视图粒度与问题粒度不匹配。这些规则直接写在 `schema_dictionary.md` 和 `generate_sql_tool.md` 中，LLM 生成 SQL 时会遵守——例如：

- “最延迟州排名”必须回退 `orders` + `customers` 按订单级 `delay_rate` 排序（因为 `mv_delivery_perf.delayed_orders` 是绝对数，按州 `SUM` 会使大州天然排第一）
- “全平台整体准时率”不能在 `mv_delivery_perf.on_time_rate`（月 × 州单元比率）上直接取平均
- “跨月分期数”汇总必须用交易笔数加权平均而非简单 `AVG(avg_installments)`

当问题维度完全不在任何视图中（如“产品重量与运费关系”），LLM 直接返回 `hit_pre_agg_view=false`，回退基础表。

Coordinator 侧也有两处配合：分解器检测到 GMV 预测类问题时，会直接将子问题文本改写为“查询 `mv_monthly_sales` 历史月度 GMV”；`adapters.py` 在汇总结果时从 pipeline 输出中提取命中了哪些视图，写入业务摘要供最终答案引用。

---

## 系统架构设计

### 关键技术选型

| 模块 | 选型 | 说明 |
| --- | --- | --- |
| 大语言模型 | DeepSeek v4 | 驱动意图理解、SQL 生成与最终回答撰写 |
| Agent 框架 | LangChain + LangGraph | 单 Agent 工具链编排；协调器采用有状态图调度 |
| 数据库 | MySQL 8.0 | 原始表与预聚合视图同库，只读查询 |
| Web 前端 | Streamlit | 双栏布局：对话区 + 可视化区 |
| 会话持久化 | JSON 文件 | Web 与命令行共用同一会话存储 |
| 数据访问 | PyMySQL | 批量导入与 SQL 执行 |

### 协作模式

系统采用“协调器中枢 + 共享状态”的协作模式。各子 Agent 不直接通信，而是通过共享状态 `AgentState` 交换信息，由协调器 Agent 统一调度执行顺序。

| 阶段 | 说明 |
| --- | --- |
| 问题分解 | 协调器分析用户需求并确定所需 Agent |
| 任务调度 | 协调器选择一个 Agent 执行当前任务 |
| 状态更新 | Agent 将分析结果写入 `AgentState` |
| 迭代协作 | 协调器读取最新状态并决定下一步 |
| 结果汇总 | 汇总所有 Agent 输出生成最终回答 |

`AgentState` 作为共享状态容器，负责存储和传递各 Agent 的中间结果，后续 Agent 可以直接读取前序 Agent 的结果；协调器根据 `AgentState` 中已有结果决定下一步执行流程，从而实现多 Agent 的协同工作。

| 步骤 | AgentState 的作用 |
| --- | --- |
| 问题分解 | 存储 `intent`、`sub_questions`、`suggested_agents` |
| 数据分析 | 写入 SQL 结果、CSV 路径和分析摘要 |
| NLP 洞察 | 写入情感分析、主题分布等文本洞察 |
| 可视化生成 | 写入图表结果和可视化规划 |
| 决策分析 | 写入业务建议与推理结果 |
| 最终汇总 | 汇总所有 Agent 输出生成最终回答 |

---

## 单 Agent 设计

### 数据分析 Agent

数据分析 Agent 是整条 Agentic BI 链路的查询中枢：负责把协调器下发的单条自然语言子问题转为可执行的 MySQL 只读查询，并将统计结果整理为下游可视化、决策 Agent 可直接消费的结构化证据。其核心设计原则是**视图优先、基础表兜底、一子问题一条 SQL、查询结果单独写入 CSV 文件，不作为 LLM 上下文**。

#### 输入与输出

数据分析 Agent 的输入为用户原始提问，输出内容为 LLM 执行结果（JSON）和 CSV 文件（执行 SQL 查询的数据）。其中 LLM 执行结果主要内容包括：转写计划（含视图命中信息）、生成的 SQL 列表及口径说明、执行结果（是否成功、CSV 路径、返回行数与耗时）。

#### 执行流程

数据分析 Agent 将 NL2SQL 拆成五步：查询转写 → 规则校验 → SQL 生成 → 语法校验 → SQL 执行。任一环节失败会将错误反馈写入上下文并自动重试（最多 3 次）。

| 步骤 | 是否调用 LLM | 职责 |
| --- | --- | --- |
| 查询转写 | 是 | 抽取指标、维度、时间范围，拆分子问题，标注是否命中预聚合视图及候选视图 |
| 语义规则校验 | 否 | 按配置规则做一致性校验（子问题继承关系、差评阈值、子问题数量等） |
| SQL 生成 | 是 | 依据转写计划生成一条或多条只读 SELECT，一子问题对应一条 SQL |
| 语法与安全校验 | 否 | 只读约束、格式规范等本地规则校验 |
| SQL 执行 | 否 | 顺序执行 SQL，每条写入一个 CSV，返回行数、耗时与列摘要 |

LLM 的 system prompt 由三部分组成：核心决策规则（视图优先顺序与安全边界）、数据库表与视图字典（字段、粒度、易错口径）、以及各阶段专用任务说明。

#### 视图优先与强制回退

结构化转写阶段的输出为 JSON，关键信息包括：面向 SQL 生成器的规范化问题文本、可独立执行的子问题列表、是否命中预聚合视图、以及白名单内的候选视图名。

当判定命中预聚合视图时，SQL 生成优先对视图查询；但若某子问题需要视图不具备的维度，该子问题仍须回退原始表，不得偷换为全平台口径。以下场景在数据字典中标记为强制回退：

- 「全平台整体准时率」不能对视图中的准时率字段直接取平均（该字段是月 × 州单元内比率）
- 跨月汇总平均分期数须用交易笔数加权平均，不能简单对均值再取平均
- 商品物理属性、单笔订单明细、评论原文等视图未覆盖维度，一律 JOIN 基础表

以作业附录问题「2017 年哪个州的销售额最高？」为例：LLM 识别维度为州、销售额与 2017 年，命中各州销售视图，最终 SQL 对各州 GMV 按 2017 年月度汇总后排序取 Top 1，而非实时 JOIN 订单、明细、客户三表。

### 可视化 Agent

可视化 Agent 的主要作用，是把数据分析 Agent 查出来的 CSV 结果进一步变成业务人员能直接看懂的图表。我们没有把它设计成“每次固定生成一整套图”的形式，而是让它先判断用户的问题到底需不需要可视化。如果用户只是问“2017 年 GMV 是多少”这类单一指标问题，系统可以只返回文字和数值；如果用户问的是趋势、排名、分布、原因诊断或预测问题，可视化 Agent 才会开始规划图表。这样做的好处是结果不会显得堆砌，也更接近真实 BI 系统中“图表服务于问题”的逻辑。

在实现上，可视化 Agent 的输入主要有三类：

1. 用户原始问题和协调器识别出的意图，例如 descriptive、diagnostic、predictive 等
2. 数据分析 Agent 的查询结果，包括 CSV 路径、字段名、数据摘要和已命中的预聚合视图
3. NLP 评论洞察 Agent 产出的差评主题、情感分布和词云数据

可视化 Agent 会先调用规划模块，根据这些信息生成一个图表计划，计划中会说明是否需要画图、画几张图、每张图从哪里取数，以及建议使用什么图表类型。

本项目中支持的图表类型覆盖了作业要求中的主要场景：

| 图表类型 | 主要使用场景 | 数据来源示例 |
| --- | --- | --- |
| 折线图 | 月度 GMV、订单量变化、预测趋势 | `mv_monthly_sales` |
| 柱状图 / 条形图 | 各州销售排名、Top 品类、支付方式对比 | `mv_state_sales`、`mv_category_sales`、`mv_payment_dist` |
| 热力图 | 支付方式与分期数、品类与评分的交叉关系 | 支付表、评论表或聚合结果 |
| 散点图 / 气泡图 | 商品重量、体积与运费之间的关系 | `products` + `order_items` |
| 地理气泡图 | 巴西各州销售额、订单量空间分布 | `mv_state_sales` + 地理坐标 |
| 词云图 | 好评与差评评论高频词对比 | NLP Agent 的 wordcloud 结果 |

可视化 Agent 的执行过程大致可以分成三步：

1. **规划：** 根据问题和字段结构判断图表类型。例如看到 `year_month` 和 `total_gmv` 时更倾向于折线图，看到 `customer_state` 和 `total_orders` 时更倾向于柱状图或地理图。
2. **取数：** 如果数据分析 Agent 已经查到了合适的 CSV，就优先复用已有结果；如果图表需要额外维度（例如用户问整体运营状况但当前缺少支付结构数据），可视化 Agent 会生成补充问题，再交给数据分析 Agent 追加查询。
3. **渲染：** 系统使用 matplotlib、seaborn 和 wordcloud 将结果保存为 PNG 图片，并返回图片路径、图表标题、选型原因等结构化信息，供 Web 页面展示。

对于预测类问题，可视化 Agent 还会承担一部分预测展示工作。系统会优先基于 `mv_monthly_sales` 中的历史 GMV 序列生成趋势图，并在折线图上叠加未来 6 周预测值和置信区间。这样用户不但能看到一个预测数字，也能看到这个预测是接在怎样的历史趋势后面得出的。对于评论诊断类问题，可视化 Agent 会优先使用 NLP Agent 提供的 `topic_distribution`、`complaints_by_category` 和好评 / 差评词云，让“差评原因”不只是停留在文字描述中，而是可以通过图表看出主要问题集中在哪些主题和品类。

从用户体验上看，可视化 Agent 最终输出的不是一段技术日志，而是一组可以直接放到仪表板右侧的图表。Streamlit 页面会把每轮提问对应的图表按轮次展示，用户可以一边看左侧的分析结论，一边在右侧查看趋势、排名、词云等辅助材料。这样整个系统比传统静态 BI 看板更灵活，因为图表不是提前写死的，而是跟随用户问题动态生成。

### NLP 评论洞察 Agent

#### 架构概览

NLP Agent 负责从 `order_reviews` 表（约 11.2 万条评论）中提取情感倾向、主题分布和高频词，为 diagnostic / prescriptive 类问题提供“用户评价”证据。

架构：**离线训练 + 在线读表**。

情感分析单条需 50~150 ms，全量约 10 万条需数小时；BERTopic 训练约 1.4 万条差评需 5~10 分钟——模型推理太慢，无法放在用户请求路径上。因此离线阶段用 backfill 命令一次性跑完推理，结果写入三张 MySQL 表；在线阶段只执行聚合 SQL，毫秒级响应。

**为什么不用纯在线查询：** NLP 模型推理太慢，无法放在用户请求路径上。情感分析单条评论需 50~150 ms，全量约 10 万条需数小时；BERTopic 训练约 1.4 万条差评需 5~10 分钟。即使用了 `_FastWrapper` 绕过 HuggingFace datasets pipeline 实现 15–30 倍提速，全量推理仍需数十分钟。因此采用 **离线灌库 + 在线读库**：离线阶段用 backfill 命令对全量评论跑模型推理并写入 `review_sentiment`、`review_topics`、`review_topic_meta` 三张表；在线阶段只执行聚合 SQL，毫秒级响应。新数据通过 `--only-missing` 增量更新，`INSERT ... ON DUPLICATE KEY UPDATE` 保证幂等。

离线层使用两个 HuggingFace 开源小模型，均为 BERT 家族 encoder-only 架构（约 1.2 亿参数，本地运行，不调 LLM API）：

| | 情感分析 | 文本嵌入 |
| --- | --- | --- |
| **模型** | `pysentimiento/robertuito-sentiment-analysis` | `paraphrase-multilingual-MiniLM-L12-v2` |
| **用途** | 三分类（POS / NEU / NEG） | 文本 → 384 维语义向量 |
| **大小** | ~500 MB | ~120 MB |

robertuito 加载失败时自动降级到 `cardiffnlp/twitter-xlm-roberta-base-sentiment`。`ReviewInsightAgent` 类支持依赖注入四个子工具，关键参数：`sample_size=1000`、`wordcloud_top_n=80`、`wordcloud_sample=4000`。

#### 触发机制

Coordinator 如何决定调用 NLP Agent，具体是 `should_run_nlp(question, intent)` 决定触发：

- `intent` 为 diagnostic / prescriptive 时一律触发
- predictive 时仅当命中评论关键词才触发
- 问题直接含关键词（“评论”“差评”“满意度”“review”“sentiment”等）也触发

Coordinator 三层保证不遗漏：

1. 分解阶段插入 `suggested_agents`
2. 编排路由每轮检查并强制 NLP 先于 visualization（执行顺序 `nlp → visualization → decision`）
3. 决策前若缺失则补运行

幂等保证：`state["review_insights"]` 已存在时跳过。

#### 子工具详解

##### 1. BERTopic 无监督主题建模（最高优先级）

BERTopic 是无监督聚类，无关键词分类的 “other” 盲区（约 30–40% 差评不命中预定义关键词），主题粒度更细（10–20 vs 7 个），因此 `_has_bertopic_data()` 探到表有数据就完全跳过关键词分类。

**离线训练：** 抽取 `review_score <= 2` 且文本 ≥ 10 字符的差评 → MiniLM-L12-v2 embedding（`batch_size=64`）→ HDBSCAN 聚类（`min_cluster_size=30`）→ c-TF-IDF 提取关键词 → 写入 `review_topics`（评论 → 主题 ID）和 `review_topic_meta`（标签为 Top 3 关键词 `/` 连接，如 `"entrega / atraso / prazo"`，离群点标为 `"outlier"`）。

**在线聚合：** 两条 SQL——从 `review_topic_meta` 取 Top 12 主题 + JOIN 五表生成品类 × 主题交叉表，输出每品类 Top 3 主题及其占比。

##### 2. 关键词主题分类（BERTopic 空时回退）

词典（`topic_keywords.yaml`）定义 7 主题 × 33 葡语关键词：

| 主题 | 关键词示例 | 含义 |
| --- | --- | --- |
| `delivery_delay` | atraso, demora, demorou | 配送延迟 |
| `not_received` | não recebi, não chegou | 未收到货 |
| `product_quality` | defeito, quebrado, ruim | 产品质量缺陷 |
| `wrong_item` | errado, diferente, troca | 错发 / 不符 |
| `customer_service` | atendimento, suporte | 客服体验 |
| `price_freight` | frete, caro, preço | 价格 / 运费不满 |
| `missing_parts` | faltando, incompleto | 缺件 / 不完整 |

词典加载三级降级：PyYAML → 内置极简解析器 → 硬编码默认词典，保证配置异常时仍可运行。分类采用 first-fit 策略（按顺序匹配，首个命中返回，全不命中返回 `"other"`）。SQL 采样 `review_score <= 2` 差评 JOIN 六表 `LIMIT 1000`。输出含 `topic_distribution`、Top 5 品类 / 卖家州 / 客户州、`complaints_by_category`（每品类主导主题及占比），标识 `method = "keyword_pt_baseline"`。

##### 3. 情感分析

**离线 backfill：** 默认 `pysentimiento/robertuito-sentiment-analysis`（葡 / 西 / 英），降级 `cardiffnlp/twitter-xlm-roberta-base-sentiment`。通过 `_FastWrapper` 绕过 datasets pipeline 直接调 `model(**enc).logits + softmax`，提速 15–30 倍。`polarity_score = pos_prob - neg_prob`（范围 `[-1, +1]`）。`batch_size=32`，`INSERT ... ON DUPLICATE KEY UPDATE` 幂等写库，`--only-missing` 增量续跑。

**在线聚合：** 5 条 GROUP BY——整体极性分布、按评分交叉、按品类 / 客户州 / 卖家州下钻（各取 Top 10 最差，过滤 sample < 30），JOIN 链路为 `review_sentiment → order_reviews → orders/order_items → products/customers/sellers`。

##### 4. 词云数据生成

好评（≥ 4）和差评（≤ 2）各 `ORDER BY RAND()` 采样 4000 条 → 正则规范化（保留葡语重音字符）→ 过滤 180 个葡语停用词（有意保留 bom / ruim）→ 过滤短词 → Counter 词频取 Top 80。输出好评 / 差评对比词频字典 `{word: weight}`。

#### 输出与下游消费

NLP Agent 运行完毕后将三类洞察写入 `state["review_insights"]`：

1. **差评主题分布：** BERTopic 或关键词分类产出的差评集中在哪些问题上（如配送延迟、产品质量），以及每个品类的差评 Top 原因
2. **全平台情感画像：** 正面 / 中性 / 负面评论占比、加权平均极性分、按品类 / 州的细粒度情感差异
3. **好评差评高频词对比：** 正负面评论各抽样 4000 条后统计的高频词字典，供词云渲染

Decision Agent 通过 `normalize_nlp_result()` 将上述数据统一转为标准化字段后用于诊断推理和策略建议；Visualization Agent 取用差评主题分布和情感数据规划佐证图表（饼图、柱状图）；Synthesizer 取用全部洞察作为最终 LLM 汇总的证据来源。Session Context 负责跨轮缓存，后续追问不再重复触发 NLP。

#### 数据库表设计

##### 1. `review_sentiment`

DDL：`utils/create_review_sentiment_table.sql`

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `review_id` | VARCHAR(64) PK | 与 `order_reviews.review_id` 1:1 对应 |
| `polarity` | ENUM('POS','NEU','NEG') | 三分类多数类 |
| `polarity_score` | FLOAT | `pos_prob - neg_prob`，范围 `[-1, +1]` |
| `pos_prob` | FLOAT | 正面概率 |
| `neu_prob` | FLOAT | 中性概率 |
| `neg_prob` | FLOAT | 负面概率 |
| `model_name` | VARCHAR(64) | 推理模型名 |
| `model_version` | VARCHAR(32) | 模型版本（可选） |
| `created_at` | DATETIME | 推理时间戳 |

##### 2. `review_topics`

DDL：`utils/create_review_topics_table.sql`

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `review_id` | VARCHAR(64) PK | 与 `order_reviews.review_id` 1:1 对应 |
| `topic_id` | INT | BERTopic 聚类 ID（`-1` = outlier） |
| `probability` | FLOAT | HDBSCAN 软聚类概率 |
| `model_name` | VARCHAR(64) | Embedding 模型标识 |
| `created_at` | DATETIME | 训练时间戳 |

##### 3. `review_topic_meta`

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `topic_id` | INT PK | BERTopic 聚类 ID |
| `label` | VARCHAR(128) | 主题标签（Top 3 关键词用 `/` 连接） |
| `top_words_json` | TEXT | JSON 数组 `[{word, weight}]` |
| `sample_count` | INT | 该主题包含的评论数 |
| `model_name` | VARCHAR(64) PK | Embedding 模型标识 |
| `created_at` | DATETIME | 训练时间戳 |

### 决策智能 Agent

#### 职责定位

决策智能 Agent 是本项目中负责“把分析结果变成经营动作”的模块。数据分析 Agent 负责查清楚指标，可视化 Agent 负责呈现趋势和对比，NLP Agent 负责把评论文本转成结构化洞察；决策智能 Agent 则在这些结果之上回答“问题是否严重、优先处理什么、应该怎么做”。因此它不是简单复述 SQL 结果，而是面向运营决策组织证据、判断优先级，并生成可执行建议。

从职责边界看，决策智能 Agent 不直接访问原始数据库，也不重新生成 SQL。它依赖 coordinator 传入的共享状态，消费其中的 `analysis_result`、`nlp_result`、`forecast_result`、`visualization_result`、`what_if_result` 和会话上下文。这样可以避免同一个 Agent 同时承担查数、画图、评论分析和决策推理，保证系统中每个 Agent 的职责相对清晰。

#### 输入与证据整合

决策智能 Agent 的第一步是把上游结果整理成统一的 Evidence Bundle。原始状态中可能包含 SQL 表格、业务摘要、关键行、评论主题、情感分布、预测趋势、图表说明和历史对话信息，如果直接交给大模型，很容易出现证据遗漏或过度发挥。Evidence Bundle 会把这些异构信息压缩成若干经营信号，例如配送时效异常、卖家评分偏低、某类商品差评集中、区域负面情绪偏高、未来 GMV 增长放缓等。

这种证据包的作用是让后续推理尽量基于结构化事实，而不是只依赖自然语言描述。比如 SQL 结果提供“哪个州延迟率高”，NLP 结果提供“用户评论中是否集中抱怨配送”，预测结果提供“未来销售是否可能放缓”，这些证据会被放入同一个决策上下文中，供后续优先级判断和行动计划生成使用。

#### 问题识别与优先级排序

在证据整理完成后，系统会识别几类常见运营问题，包括物流履约问题、卖家治理问题、品类体验问题、区域运营问题和预测放缓风险。每个问题会被表示为一个 ScoredProblem，并从影响范围、紧急程度和可执行性等维度进行评分。这样做的目的是避免所有问题看起来都同样重要，而是让系统能区分“必须马上处理的问题”和“可以继续观察的问题”。

例如，一个州的配送延迟率很高，但订单量很小，那么它的业务影响可能有限；相反，如果 SP 这类高订单州同时出现延迟率偏高和评论负面情绪集中，就会被判定为更高优先级。再比如，如果少数低评分卖家同时拉低整体评分并影响 GMV，系统会把它识别为卖家治理类问题，并在行动计划中给出更靠前的处理优先级。

#### 行动计划生成

决策建议的生成不是只靠一句 Prompt 完成，而是由规则层和 LLM 叙述层共同完成。规则层先根据 ScoredProblem 生成结构化行动项，包含建议动作、负责人角色、目标 KPI、时间周期、预期影响和风险提示；随后 LLM 负责把这些结构化结果组织成面向业务人员的中文报告。这样既保留了规则层的稳定性，又让最终回答具有更自然的解释能力。

典型流程可以概括为：先构造 Evidence Bundle，再识别问题类型并计算优先级，然后生成行动计划和根因解释，接着按需运行 What-if 分析，最后输出自然语言决策报告。以配送问题为例，如果系统发现某些州配送时长显著偏高，同时评论中“未收到货”“配送延迟”等主题占比较高，决策智能 Agent 会建议优先推进履约改善，并给出如“缩短平均配送时长”“提升准时率”“降低配送相关负面评论占比”等验收指标。

#### What-if 与决策结合

当用户问题带有反事实含义时，决策智能 Agent 会调用通用 What-if 工具链。系统会先通过 `plan_what_if` 判断用户是否真的提出了“如果某个干预发生，会带来什么变化”的问题，并把它规划为结构化 WhatIfPlan；随后由 `run_what_if` 执行显式计算，得到基线指标、模拟后指标和变化量。这个结果会进入 `decision_result.what_if_result`，并被最终报告解释。

这里的 What-if 不是精确预测，而是静态反事实估计。系统只计算用户或上游证据明确给出的基线、变化假设和公式，不会凭常识猜测 GMV 弹性、转化率提升或投入产出比。如果缺少必要输入，结果会标记为 `missing_inputs` 或 `directional_only`，并在回答中说明还需要补充哪些假设。这样可以让决策建议既能回答“如果这样做可能怎样”，又不把模拟结果包装成确定预测。

#### 输出结构与质量控制

决策智能 Agent 的核心输出是 DecisionResult。其中：

- `decision_theme` 表示本次建议更偏向物流优化、卖家治理、品类治理、区域运营还是综合运营
- `problem_statement` 概括主要问题
- `key_findings` 保存关键证据
- `root_causes` 解释可能原因
- `action_plan` 给出具体动作
- `what_if_result` 保存模拟结果
- `risks` 和 `assumptions` 说明建议成立的前提和风险
- `narrative_answer` 则是最终给用户阅读的自然语言答案

为了提高报告可靠性，系统还加入了质量检查与修订机制。质量检查会关注几个问题：建议是否过于空泛、是否缺少证据、是否在 What-if 未运行时给出模拟数值、是否没有说明关键假设和局限。如果发现问题，系统会要求叙述层基于已有证据重新整理回答；如果叙述层 LLM 失败，规则层也会生成确定性摘要，保证 coordinator 链路不会因为最终措辞失败而中断。

---

## 多智能体调度设计

本项目采用了协调器 Agent 统一调度多个子 Agent 的方式。这样设计的原因是，电商 BI 问题通常不是单一步骤可以完成的：有的问题需要先查 SQL，有的问题还要分析评论文本，有的问题需要画图，有的问题最后还要生成经营建议。如果只用一个 Agent 直接回答，容易出现职责混乱、SQL 结果和建议混在一起、或者还没查清数据就提前下结论的问题。

系统的调度核心基于 LangGraph 的 StateGraph 实现。整个流程不是固定流水线，而是“分解问题 → 判断下一步 → 调用一个子 Agent → 回到协调器继续判断”的迭代式结构。协调器维护一个共享状态 `AgentState`，里面保存用户问题、意图、子问题列表、SQL 结果、评论洞察、图表结果、预测结果、决策结果、已完成 Agent 列表和最终回答等信息。每个子 Agent 只读取自己需要的字段，并把结果写回这个共享状态。

整体流程可以概括为四步：

**第一步是问题分解。** 协调器会先判断用户问题是否属于 Olist 电商 BI 范围，然后识别意图，例如描述性分析、诊断性分析、预测性分析、规范性分析或 What-if 分析。如果用户一次问了多个问题，例如“2017 年哪个州销售额最高？交付准时率是多少？哪种支付方式最受欢迎？”，协调器会把它拆成多个可以独立转 SQL 的子问题。这样数据分析 Agent 每次只处理一个清晰任务，生成 SQL 的稳定性会更高。

**第二步是路由。** 路由模块每次只选择一个 `next_agent`，而不是一次性把所有 Agent 都跑完。这样可以根据当前状态动态决定下一步。例如：

- 纯描述性问题通常是 `data_analysis → synthesize`
- 带趋势和排名的问题可能是 `data_analysis → visualization → synthesize`
- 差评原因或经营诊断问题则更可能是 `data_analysis → nlp → visualization → decision → synthesize`

路由规则还要求不能过早 synthesize，如果 `suggested_agents` 中还有未完成的 NLP、可视化或决策任务，就必须继续调度。

**第三步是子 Agent 执行。** 数据分析 Agent 会逐个处理 `sub_questions`，优先判断是否命中预聚合视图，若命中就查询 `mv_monthly_sales`、`mv_state_sales`、`mv_delivery_perf` 等视图，若不命中则回退到基础表 JOIN。NLP Agent 会在问题涉及评论、差评、评分、投诉或诊断时运行，把评论文本转换为主题分布、情感聚合和词云数据。可视化 Agent 会根据 SQL 结果与 NLP 结果动态规划图表。决策智能 Agent 则在证据比较完整后生成优先级建议和 What-if 解释。

**第四步是最终汇总。** 协调器不会把所有中间 JSON、CSV 路径和 SQL 日志直接丢给用户，而是调用 synthesize 模块，把结构化证据整理成面向业务人员的中文回答。最终回答会保留关键数值、趋势解释、必要的图表说明和决策建议，但会过滤掉列画像、文件路径、重复的视图命中提示等技术噪声。这样用户看到的是一份分析结论，而不是一堆程序运行记录。

系统还加入了多轮会话管理。命令行和 Streamlit Dashboard 共用同一套 SessionManager，会把每轮问题、回答、trace 事件和图表结果保存到 `runtime/sessions/`。当用户继续追问“那 SP 州呢？”时，系统会先结合历史会话解析真实含义，再交给协调器执行。Web 页面中间区域展示对话和 Agent 执行进度，右侧区域按轮次展示可视化图表，因此用户既能看到最终结论，也能看到系统是如何一步步完成分析的。

从实现效果看，多智能体调度让每个 Agent 的边界比较清晰：数据分析 Agent 负责查数，可视化 Agent 负责出图，NLP Agent 负责文本洞察，决策 Agent 负责建议，协调器负责任务拆解、路由和汇总。这样的结构比单 Agent 更容易调试，也更符合本课程对 Agentic BI 的要求，因为它体现了“自然语言入口、多表数据分析、图表生成、决策建议和多轮交互”之间的完整闭环。

---

## 加分项完成情况

### What-if 分析

#### 工具实现

本项目的 What-if 分析不是把少数固定问题写死成模板，而是放在决策智能 Agent 内部作为一个通用反事实工具链实现。用户提出“如果下架高差评卖家会怎样”“如果配送时长缩短 2 天会怎样”“如果 GMV 基线为 100 万且转化率提升 10% 会怎样”这类问题时，系统会先用 `plan_what_if` 将自然语言问题整理成结构化 WhatIfPlan，明确干预对象、目标指标、基线值、变化值、计算公式、数据来源、假设条件和缺失输入；随后由 `run_what_if` 执行安全计算，输出 `baseline_metrics`、`simulated_metrics`、`delta_metrics`、`summary_text`、`limitations` 等结构化结果。当前通用计算支持加减、乘法、百分比变化和百分点变化，例如 `percent_change` 表示 `simulated = baseline * (1 + change)`，`percentage_point_change` 表示比率类指标增加或减少若干百分点。

#### Coordinator 触发链路

在 coordinator 的完整链路中，What-if 首先由问题分解阶段触发。`decompose_query` 会把用户问题识别为 `intent="what_if"`，并区分两类情况：

- 如果用户已经给出足够的基线和变化假设，例如“GMV 基线 100 万、转化提升 10%”，则可以不强行生成 SQL 子问题，直接建议调度 decision
- 如果问题需要查询当前业务数据作为基线，例如“下架当前差评率最高的卖家会怎样”，则会设置 `requires_data_analysis=true`，先生成可执行的 `sub_questions`，并建议 `data_analysis → decision`

随后路由模块每轮只选择一个 `next_agent`：有待查数子问题时先运行数据分析 Agent，SQL 结果写入共享状态后，再运行决策智能 Agent。决策 Agent 在生成行动建议前会读取 SQL 摘要、评论洞察、预测结果和会话上下文，调用 `plan_what_if → run_what_if` 得到模拟结果，并把它放入 `decision_result.what_if_result`。最终 coordinator 的 synthesize 阶段再把该结构化结果整合进面向业务用户的回答。

#### 证据不足时的处理

系统还为 What-if 设置了补充数据与降级机制，避免“没有依据也给数字”。如果 `run_what_if` 发现缺少 baseline、change、数据来源或必要的业务弹性，会返回 `status="missing_inputs"`；如果只能判断方向但无法量化，会返回 `status="directional_only"`。coordinator 的路由和 replan 逻辑会检查这些状态，在补充规划次数未超过上限时，优先回到 data_analysis 补查可验证输入，而不是直接进入最终汇总。若最终仍无法补齐证据，系统会在回答中说明缺口和局限，不用 0、经验系数或模型臆测替代真实计算。

#### 适用范围

这种设计的好处是，系统不需要为每一种业务问法单独写一个模拟函数。只要问题能被整理为“基线是多少、变化假设是什么、要观察哪个指标”，就可以沿用同一套计划和计算流程，例如 GMV 提升、订单量变化、评分改善、差评率下降、准时率提升等问题都可以进入相同的结构化表达。它并不是要证明所有 What-if 问题都能自动精确求解，而是把可计算部分先算清楚，把缺失假设明确列出来。对于需要复杂因果关系、需求转移、竞争反应或投入产出弹性的场景，系统会把它们作为边界条件说明，而不会直接编造一个看似精确的结果。

### Agent 记忆模块

本项目的 Agent 记忆模块主要解决两个问题：一是单个会话内的多轮追问如何理解上下文，二是多个历史会话如何创建、保存、切换和恢复。它没有直接采用 LangGraph 的 MemorySaver，而是在协调器外层实现了一套更贴合本项目 Dashboard 和命令行使用方式的会话管理机制。

#### 单会话记忆

在单会话记忆方面，系统会为每个 session 保存完整的轮次记录，包括用户原始问题、语义解析后的独立任务、最终回答、Agent 执行 trace、状态摘要和图表结果等。当用户继续提出“那 SP 州呢？”“如果只看 2017 年呢？”这类依赖前文的问题时，SessionManager 会先读取该 session 的历史内容，并调用会话语义解析模块判断本轮问题与前文的关系，生成更完整的 `resolved_task`。随后系统会把压缩后的 `conversation_history` 注入协调器的初始状态，使 LangGraph 在执行本轮任务时能够知道用户前几轮关注的业务对象、指标和约束条件。也就是说，本项目的多轮记忆不是简单拼接全部聊天记录，而是**“历史摘要 + 最近问答 + 语义解析”**的组合。

为了避免上下文不断膨胀，系统还维护了 `memory_summary`。每轮执行结束后，系统会根据已有摘要和最近若干轮对话生成新的会话摘要，只保留用户目标、已分析对象、关键结论、延续约束和后续可能需要继承的信息。下一轮执行时，系统优先使用这个摘要和少量最近轮次，而不是把所有 SQL 结果、trace 日志和完整回答全部塞入模型上下文。这样既能保留连续分析所需的业务记忆，也能降低长会话导致 prompt 过长、模型注意力分散或上下文溢出的风险。

#### 多会话管理

在多会话管理方面，系统使用 LocalSessionStore 将 session 以 JSON 文件形式持久化到 `runtime/sessions/`。每个 session 都有独立的 `session_id`、标题、创建时间、更新时间、轮次列表和会话摘要。命令行工具可以新建会话、指定已有会话继续追问、列出历史会话；Streamlit Dashboard 也复用同一套 session 存储，在侧边栏展示历史对话，并在切换会话后恢复对应的问答和图表。因此，多会话管理不仅是“保存聊天记录”，还承担了会话隔离、历史回看、跨入口共享和分析过程复现的作用。

#### 对标 LangGraph MemorySaver

如果对标 LangGraph 的 MemorySaver，本项目的机制替代了它最核心的“按会话保存并恢复上一轮状态”的能力：通过 `session_id` 找到历史记录，并把必要上下文重新注入本轮 Agent 状态。相比 MemorySaver，本项目额外提供了本地文件持久化、会话列表、Dashboard 历史展示、trace 事件保存、图表结果关联和摘要压缩等功能。可能少掉的是 LangGraph checkpointer 原生提供的节点级 checkpoint、从中间节点恢复、time travel 调试等能力。实现差异上，MemorySaver 更像图内部的状态快照机制，而本项目的记忆模块更像图外部的应用层 session 系统：它不依赖 LangGraph 自动恢复完整状态，而是主动选择哪些历史信息进入下一轮上下文，从而更容易控制上下文大小和前端展示结构。

### 评论文本融入决策建议

#### 整体链路

NLP Agent 产出的评论洞察经四步融入 Decision Agent 的建议生成：

**格式统一 → 信号生成 → 跨域评分 → 合成回复**

#### 格式统一

NLP 输出存在两种格式——BERTopic 路径产出的是主题标签（如 `"entrega / atraso / prazo"`）和每品类的 Top 3 原因列表，关键词路径产出的是预定义主题计数和每品类的主导原因。两者结构不同，无法被下游直接消费。

因此 Decision Agent 首先调用 `normalize_nlp_result()` 做适配：不管是哪种上游格式，统一转为四个标准化字段——`negative_topics`（差评主题及占比）、`worst_categories`（高差评率品类及原因）、`worst_states`（差评集中州）、`sentiment_overview`（全平台情感画像）。

#### 信号生成：将评论主题转为可计算的数值

这一步是整个链路的关键——把自然语言主题标签变成能与 SQL 指标同台比较的定量信号。

BERTopic 产出的是数十个细粒度主题标签，每个标签是一组葡语关键词（如 `"dois / apenas / só"` 表示数量 / 规格不符）。`build_evidence_bundle()` 按葡语关键词匹配将这些细粒度主题聚为 4 大宏观类别：

- 配送物流（匹配 entrega、demora、not_received 等）
- 产品质量（匹配 defeito、quebrado、danificado 等）
- 货不对板（匹配 diferente、errada、foto 等）
- 售后退款（匹配 cancelamento、devolver、estorno 等）

聚完类后，计算每类主题的评论数占全部差评的比例。这个比例是一个连续的数值——例如 38.8%——可以与预设阈值比较：配送类 ≥ 25% 触发配送负面信号，质量类 ≥ 15% 触发质量负面信号，等等。超阈值后生成一个 DecisionSignal，包含 `severity_score`（按 `(实际值 − 阈值) / 惩罚系数 + 基准分` 计算，截断到 `[0,1]`）和自然语言证据文本。

与此同时，从品类维度和州维度也各自触发信号：单品类差评率 ≥ 25% 触发品类质量信号，单州差评率 ≥ 22% 触发区域口碑信号。

#### 跨域评分：NLP 与 SQL 信号共同决定优先级

所有信号按问题域（delivery / seller / category / region / forecast）分组。每个域内，NLP 产出的信号和 SQL 产出的信号被放在同一组里比较。

以配送域为例：该域下既有 SQL 侧信号（准时率、平均配送天数），也有 NLP 侧信号（配送相关主题的差评占比）。三条信号的 `severity_score` 取最大值作为该域的 impact 分。生成的 problem 证据列表中同时包含 SQL 和 NLP 的证据描述——例如“9 个州准时率低于 80%”和“差评中 38.8% 与物流配送相关”并列呈现。

问题优先级由加权公式决定：

```text
0.5 × impact + 0.3 × urgency + 0.2 × feasibility
```

所有问题按得分降序排列后传入行动项生成模块，产出分级策略（P1 / P2），最终由 LLM 合成为用户可读的结论摘要、分项分析和决策建议。

#### 总结

评论文本融入决策的核心思路是 **非结构化 → 结构化 → 定量信号 → 跨域评分**。NLP 洞察不是独立展示的一个段落，而是经过关键词聚合、阈值检测、加权评分后，与 SQL 指标在同一套逻辑下共同决定问题的严重度排序和策略的优先级。最终的每条建议都可以追溯到具体的 NLP 数据——不仅是“用户不满”，而是“床浴用品品类差评中 36% 指向数量 / 规格不符，差评率 36.3%，触发品类治理 P1 行动”。

---

## 项目运行示例

本章节展示项目运行情况。用户提问后，Agent 会输出自己的任务编排与执行过程，在完成思考后整理并输出答案。页面采用左侧对话区 + 右侧可视化展示区的双栏布局，用户可以同时查看文本分析和关联图片。

### Agent 思考并执行任务

> *[此处插入截图：Agent 思考并执行任务]*

### Agent 输出答案

> *[此处插入截图：Agent 输出答案]*

### Agent 绘制图片

> *[此处插入截图：Agent 绘制图片]*

### 查看 Agent 思考过程

查看 Agent 思考过程，可以看出命中了预聚合视图。

> *[此处插入截图：命中预聚合视图]*

---

## 技术挑战与解决方案

### 复杂分析任务的自动分解与协同求解

#### 技术挑战

商业智能系统面对的往往不是简单统计查询，而是包含多个分析维度、多个指标以及潜在因果关系的复合问题。

例如该问题：“产品的重量、尺寸与运费之间有什么关系”。该问题同时涉及商品重量、体积、运费以及相关性分析等多个维度。若直接由单个 Agent 一次性生成 SQL 并完成分析，容易出现查询逻辑过于复杂、分析维度遗漏、结果解释能力不足等问题。同时，随着问题复杂度提升，单次推理的稳定性和可维护性也会显著下降。

#### 解决方案

为解决复杂问题的分析粒度问题，系统采用协调器 Agent 驱动的任务分解机制。协调器首先识别用户问题中的关键分析维度，将复杂问题拆解为多个能够独立求解的子问题，并将其分发给对应 Agent 处理。

以“产品重量、尺寸与运费之间的关系”为例，系统不会直接生成一条复杂查询，而是拆分为多个独立分析任务，例如：

- 商品重量与运费的关系分析
- 商品体积与运费的关系分析
- 不同品类下运费差异分析
- 高运费订单的特征分析

数据分析 Agent 按照“一子问题对应一条 SQL”的原则分别执行查询，并将结果保存为独立 CSV 文件。随后，可视化 Agent 根据结果生成散点图、分布图等分析图表；决策智能 Agent 综合多个子问题结果，形成最终业务结论和优化建议。

#### 效果与收益

该方案将复杂分析任务转化为多个可独立验证的分析单元，降低了单次推理难度，提高了 SQL 生成准确率和分析结果的可解释性。同时，各 Agent 只关注自身职责范围，减少了模块间耦合，使系统能够更方便地扩展新的分析能力和业务场景。

### 多 Agent 间状态共享与协作问题

#### 技术挑战

系统由协调器 Agent、数据分析 Agent、可视化 Agent、NLP Agent 和决策智能 Agent 等多个功能 Agent 组成。每个 Agent 负责不同阶段的任务处理，但共同服务于同一个用户问题。

如果 Agent 之间仅通过自然语言传递信息，容易出现上下文丢失、信息重复传递以及状态不一致等问题。例如，数据分析 Agent 已经完成的查询结果可能无法被后续 Agent 直接复用，从而导致重复执行查询或分析逻辑不一致。

随着任务链路增长，多 Agent 系统还会面临状态同步困难、结果追踪困难以及调试成本增加等工程问题。

#### 解决方案

系统基于 LangGraph 的有状态工作流机制，构建统一的 `AgentState` 作为全局状态容器。各 Agent 通过读取和更新共享状态完成协作，而不是直接依赖自然语言上下文传递信息。

`AgentState` 中维护用户问题、任务拆解结果、SQL 执行结果、CSV 文件路径、可视化结果以及 NLP 分析结果等关键数据。每个 Agent 仅负责更新自身职责范围内的状态字段，其余 Agent 可以直接读取已有结果继续后续处理。

例如，数据分析 Agent 查询生成的 CSV 路径会直接写入共享状态；可视化 Agent 无需重新查询数据库，而是直接读取对应数据文件生成图表；决策智能 Agent 则综合所有 Agent 输出的信息生成最终业务建议。

#### 效果与收益

统一状态管理机制降低了 Agent 之间的耦合度，提高了系统可维护性和扩展性。同时避免了重复查询与重复推理带来的资源浪费，使多 Agent 协作过程更加稳定、可追踪和易于调试。

### 动态可视化生成问题

#### 技术挑战

商业智能系统中的分析问题具有高度多样性，不同问题对应的数据结构和展示需求差异较大。

例如：

- 销售趋势分析更适合折线图
- 州销售排名更适合柱状图
- 支付方式分布更适合饼图或条形图
- 商品属性与运费关系更适合散点图

如果系统采用固定模板生成图表，容易出现图表与分析目标不匹配、信息表达效率低以及界面冗余等问题。同时，用户提出的问题往往无法提前预测，因此难以通过预定义仪表盘覆盖所有场景。

#### 解决方案

系统设计独立的可视化 Agent，负责根据用户问题、分析意图以及查询结果自动规划图表生成方案。

可视化 Agent 在生成图表前首先分析数据结构和业务语义，例如时间序列字段优先匹配折线图，类别对比数据优先匹配柱状图，数值相关性分析优先匹配散点图。对于评论分析场景，则优先生成词云图和主题分布图。

在需要补充分析维度时，可视化 Agent 还能够向协调器提出新的查询需求，由数据分析 Agent 执行补充查询后再完成图表生成。最终生成的图表以 PNG 形式输出，并在 Web 页面中与文字分析结果同步展示。

#### 效果与收益

动态可视化机制使图表能够根据用户问题实时生成，而非依赖固定模板。相比传统静态 BI 看板，该方案能够更准确地表达分析结果，提高用户理解效率，并增强系统在不同业务场景下的适应能力。

---

## 小组分工情况

| 姓名 | 学号 | 主要工作 | 比例 |
| --- | --- | --- | ---: |
| 尹诚成 | 2351279 | 导入原始数据、数据库部署、数据分析 Agent 开发、Web 页面开发 | 25% |
| 谭鹏翀 | 2351588 | 预聚合视图设计与创建、NLP / 评论洞察 Agent 开发 | 25% |
| 刘逸飞 | 2353935 | 预聚合视图对比、可视化 Agent、协调器 Agent | 25% |
| 李昊 | 2353815 | 决策智能 Agent 开发、多轮会话记忆、多会话存储管理 | 25% |
