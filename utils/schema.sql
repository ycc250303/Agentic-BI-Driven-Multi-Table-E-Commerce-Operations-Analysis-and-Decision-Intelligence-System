-- =============================================================================
-- schema.sql — 原始表 / NLP 衍生表 / 预聚合视图
-- 由 python utils/setup.py 按 -- @section 分段执行，勿整文件一次性跑：
--   load 会 DROP 9 张原始表；nlp-tables 会 DROP 情感/主题表。
-- =============================================================================

-- @section origin

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

-- 1.订单表
create table orders (
    order_id varchar(32) NOT NULL COMMENT '订单ID',
    customer_id varchar(32) NOT NULL COMMENT '客户ID',
    order_status varchar(32) NOT NULL COMMENT '订单状态',
    order_purchase_timestamp DATETIME NULL COMMENT '下单时间戳',
    order_approved_at DATETIME NULL COMMENT '支付审批通过时间',
    order_delivered_carrier_date DATETIME NULL COMMENT '交付给承运商时间',
    order_delivered_customer_date DATETIME NULL COMMENT '客户签收时间',
    order_estimated_delivery_date DATETIME NULL COMMENT '预计送达时间',
    primary key (order_id)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_0900_ai_ci COMMENT = '订单主表';

-- order_id 已是主键，不再建同名二级索引
create index idx_orders_customer_id on orders (customer_id);

-- 2.订单项目表
create table order_items (
    order_id varchar(32) NOT NULL COMMENT '订单ID',
    order_item_id int NOT NULL COMMENT '订单内明细序号',
    product_id varchar(32) NOT NULL COMMENT '产品ID',
    seller_id varchar(32) NOT NULL COMMENT '商家ID',
    shipping_limit_date datetime NULL COMMENT '最晚发货时限',
    price decimal(10, 2) NULL COMMENT '商品成交价格',
    freight_value decimal(10, 2) NULL COMMENT '运费金额',
    primary key (order_id, order_item_id)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_0900_ai_ci COMMENT = '订单项目表';

-- PRIMARY(order_id, order_item_id) 左前缀已覆盖按 order_id 查找
create index idx_order_items_product_id on order_items (product_id);

create index idx_order_items_seller_id on order_items (seller_id);

create index idx_order_items_shipping_limit_date on order_items (shipping_limit_date);

-- 3.产品表
create table products (
    product_id varchar(32) NOT NULL COMMENT '产品ID',
    product_category_name varchar(255) NOT NULL COMMENT '产品分类名称',
    product_name_lenght int NOT NULL COMMENT '产品名称长度',
    product_description_lenght int NOT NULL COMMENT '产品描述长度',
    product_photos_qty int NOT NULL COMMENT '产品照片数量',
    product_weight_g int NOT NULL COMMENT '产品重量(g)',
    product_length_cm int NOT NULL COMMENT '产品长度(cm)',
    product_height_cm int NOT NULL COMMENT '产品高度(cm)',
    product_width_cm int NOT NULL COMMENT '产品宽度(cm)',
    primary key (product_id)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_0900_ai_ci COMMENT = '产品表';

create index idx_products_product_category_name on products (product_category_name);

-- 4.客户表
create table customers (
    customer_id varchar(32) NOT NULL COMMENT '客户ID',
    customer_unique_id varchar(32) NOT NULL COMMENT '客户唯一ID',
    customer_zip_code_prefix int NOT NULL COMMENT '客户邮编前缀',
    customer_city varchar(255) NOT NULL COMMENT '客户城市',
    customer_state varchar(2) NOT NULL COMMENT '客户州',
    primary key (customer_id)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_0900_ai_ci COMMENT = '客户表';

create index idx_customers_customer_unique_id on customers (customer_unique_id);

-- 仅按州过滤不能走 (city, state) 左前缀，故保留 state；单列 city 由 city_state 覆盖
create index idx_customers_customer_state on customers (customer_state);

create index idx_customers_customer_city_state on customers (customer_city, customer_state);

-- 5.商家表
create table sellers (
    seller_id varchar(32) NOT NULL COMMENT '商家ID',
    seller_zip_code_prefix int NOT NULL COMMENT '商家邮编前缀',
    seller_city varchar(255) NOT NULL COMMENT '商家城市',
    seller_state varchar(2) NOT NULL COMMENT '商家州',
    primary key (seller_id)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_0900_ai_ci COMMENT = '商家表';

create index idx_sellers_seller_state on sellers (seller_state);

create index idx_sellers_seller_city_state on sellers (seller_city, seller_state);

-- 6.支付表
create table payments (
    order_id varchar(32) NOT NULL COMMENT '订单ID',
    payment_sequential int NOT NULL COMMENT '支付序号',
    payment_type varchar(255) NOT NULL COMMENT '支付方式',
    payment_installments int NOT NULL COMMENT '支付分期数',
    payment_value decimal(10, 2) NOT NULL COMMENT '支付金额',
    primary key (order_id, payment_sequential)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_0900_ai_ci COMMENT = '支付表';

-- 7.评论表
create table order_reviews (
    review_id varchar(32) NOT NULL COMMENT '评论ID',
    order_id varchar(32) NOT NULL COMMENT '订单ID',
    review_score int NOT NULL COMMENT '评论评分',
    review_comment_title varchar(255) NOT NULL COMMENT '评论标题',
    review_comment_message text NOT NULL COMMENT '评论内容',
    review_creation_date datetime NOT NULL COMMENT '评论时间',
    review_answer_timestamp datetime NOT NULL COMMENT '评论回答时间',
    primary key (review_id)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_0900_ai_ci COMMENT = '评论表';

create index idx_order_reviews_order_id on order_reviews (order_id);

-- 8.地理位置表
create table geolocation (
    geolocation_zip_code_prefix int NOT NULL COMMENT '地理位置邮编前缀',
    geolocation_lat decimal(10, 6) NOT NULL COMMENT '地理位置纬度',
    geolocation_lng decimal(10, 6) NOT NULL COMMENT '地理位置经度',
    geolocation_city varchar(255) NOT NULL COMMENT '地理位置城市',
    geolocation_state varchar(2) NOT NULL COMMENT '地理位置州',
    primary key (
        geolocation_zip_code_prefix,
        geolocation_lat,
        geolocation_lng
    )
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_0900_ai_ci COMMENT = '地理位置表';

create index idx_geolocation_city_state on geolocation (
    geolocation_city,
    geolocation_state
);

-- 9.产品类目翻译表
create table product_category_name_translation (
    product_category_name varchar(255) NOT NULL COMMENT '产品类目名称',
    product_category_name_english varchar(255) NOT NULL COMMENT '产品类目名称英文',
    primary key (product_category_name)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_0900_ai_ci COMMENT = '产品类目翻译表';

create index idx_pcnt_product_category_name_english on product_category_name_translation (product_category_name_english);
-- @section nlp

-- =============================================================================
--  review_sentiment 表 DDL
--  ---------------------------------------------------------------------------
--  归属：NLP / 评论洞察 Agent (`agents/nlp_agent`)
--
--  作用：
--    存放对 `order_reviews.review_comment_message`（葡语评论文本）做情感分析后
--    的预测结果。NLP Agent 采用「**离线灌库 + 在线读库**」模式：
--
--    1) 离线灌库（耗时操作，约 7 分钟）：
--         python -m agents.nlp_agent.tools.sentiment --backfill
--       会一次性对 `order_reviews` 全量带文本评论（约 4 万条）跑葡语情感模型
--       `pysentimiento/bertweet-pt-sentiment`（运行在 Apple Silicon MPS GPU 上），
--       将每条评论的极性 / 三分类概率 / 综合分数写入本表。
--
--    2) 在线读库（毫秒级）：
--       NLP Agent 接收用户提问时，不再调用模型推理；而是直接 SELECT 本表做
--       聚合（按品类 / 按州 / 按 review_score 交叉），输出 `state["review_insights"]
--       ["sentiment"]` 给 Decision Agent 消费。
--
--  与原始表的关系：
--    - 通过 `review_id` 与 `order_reviews` 1:1 关联
--    - 不修改 / 不依赖任何原始表结构；本表纯属增量
--    - 可被 Data Analysis Agent JOIN 查询，例如：
--        SELECT s.polarity, AVG(r.review_score)
--        FROM review_sentiment s JOIN order_reviews r USING(review_id)
--        GROUP BY s.polarity;
--
--  幂等性：
--    - 灌库脚本使用 `INSERT ... ON DUPLICATE KEY UPDATE`，重复执行只会刷新分数
--    - 默认只跑还未落库的 review_id（断点续跑友好）；`--force` 强制重跑
--
--  字段口径：
--    - polarity_score = pos_prob - neg_prob，落在 [-1, +1]
--    - polarity 取三分类概率最大者
--    - 灌库时不会处理 review_comment_message 为 NULL / 空字符串 的评论
-- =============================================================================

DROP TABLE IF EXISTS review_sentiment;

CREATE TABLE review_sentiment (
    review_id       VARCHAR(64) NOT NULL COMMENT '评论ID（与 order_reviews.review_id 1:1）',
    polarity        ENUM('POS','NEU','NEG') NOT NULL COMMENT '情感极性（三分类概率最大者）',
    polarity_score  FLOAT       NOT NULL COMMENT '综合极性分数：pos_prob - neg_prob，∈ [-1, +1]',
    pos_prob        FLOAT       NOT NULL COMMENT '正面概率',
    neu_prob        FLOAT       NOT NULL COMMENT '中性概率',
    neg_prob        FLOAT       NOT NULL COMMENT '负面概率',
    model_name      VARCHAR(64) NOT NULL COMMENT '推理模型名称（如 pysentimiento/bertweet-pt-sentiment）',
    model_version   VARCHAR(32) DEFAULT NULL COMMENT '模型版本（可选）',
    created_at      DATETIME    NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '推理时间',

    PRIMARY KEY (review_id),
    KEY idx_polarity   (polarity),
    KEY idx_created_at (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
  COMMENT='评论情感分数（NLP Agent 离线灌库；与 order_reviews 通过 review_id 关联）';

-- =============================================================================
--  review_topics + review_topic_meta 双表 DDL
--  ---------------------------------------------------------------------------
--  归属：NLP / 评论洞察 Agent (`agents/nlp_agent`)
--  作用：存放 BERTopic 无监督主题建模的离线训练结果，供在线 Agent 毫秒级查询。
--
--  与关键词法的区别：
--    - 关键词法（topic_keyword.py）：8 类预设主题，覆盖率约 35%，60% 评论落到 other
--    - BERTopic（topic_model.py）：自动从葡语原文里发现 15-25 个真实主题（无预设）
--
--  灌库流程：
--    python -m agents.nlp_agent.tools.topic_model --backfill
--      ├─ 抽取 review_score<=2 的差评（约 1.4 万条带文本）
--      ├─ 多语种 sentence-transformers embedding（paraphrase-multilingual-MiniLM-L12-v2）
--      ├─ UMAP 降维 → HDBSCAN 聚类 → 每条评论得到 topic_id
--      ├─ c-TF-IDF 给每个主题提取 Top 关键词
--      └─ 双表落库：评论级 review_topics + 主题级 review_topic_meta
--
--  在线读取：
--    aggregate_bertopic() 直接 JOIN review_topics + order_reviews + products，
--    按 (品类, 主题) 双维度 GROUP BY，输出"X 品类的差评 38% 是物流损坏"这种结论。
-- =============================================================================

DROP TABLE IF EXISTS review_topics;
DROP TABLE IF EXISTS review_topic_meta;

-- ── 表 1：评论 → 主题 ID（每条差评一行）────────────────────────────
CREATE TABLE review_topics (
    review_id     VARCHAR(64) NOT NULL COMMENT '评论ID（与 order_reviews.review_id 1:1）',
    topic_id      INT         NOT NULL COMMENT '主题ID（-1 表示离群点 / 未归类）',
    probability   FLOAT       DEFAULT NULL COMMENT '评论属于该主题的置信度（HDBSCAN 软概率）',
    model_name    VARCHAR(64) NOT NULL COMMENT '模型 + embedding 标识',
    created_at    DATETIME    NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '推理时间',

    PRIMARY KEY (review_id),
    KEY idx_topic_id (topic_id),
    KEY idx_created_at (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
  COMMENT='每条差评的 BERTopic 主题归属（NLP Agent 离线灌库）';


-- ── 表 2：主题 → 关键词 / 大小（每个主题一行）─────────────────────
CREATE TABLE review_topic_meta (
    topic_id       INT          NOT NULL COMMENT '主题ID（-1 = 离群点）',
    label          VARCHAR(128) NOT NULL COMMENT '主题人类可读标签（取 Top 3 关键词拼接）',
    top_words_json TEXT         NOT NULL COMMENT '主题 Top N 关键词及其 TF-IDF 权重，JSON 数组',
    sample_count   INT          NOT NULL COMMENT '该主题包含的评论数',
    model_name     VARCHAR(64)  NOT NULL COMMENT '模型 + embedding 标识（与 review_topics 一致）',
    created_at     DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '训练完成时间',

    PRIMARY KEY (topic_id, model_name),
    KEY idx_sample (sample_count)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
  COMMENT='BERTopic 主题元信息（每主题一行，含 Top 关键词）';

-- @section views

-- ============================================================================
-- 预聚合视图创建脚本
-- 用途：为提升查询性能，创建6个预聚合视图作为加速层
-- 说明：所有视图基于原始表一次性计算，使用CREATE VIEW创建虚拟视图
-- ============================================================================

-- ============================================================================
-- 1. mv_monthly_sales - 月度销售趋势视图
-- 粒度：年-月
-- 用途：月度销售趋势、GMV环比增长分析
-- ============================================================================
DROP VIEW IF EXISTS mv_monthly_sales;

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

-- ============================================================================
-- 2. mv_state_sales - 各州销售情况视图
-- 粒度：年-月-州
-- 用途：各州销售额排名、区域市场对比
-- ============================================================================
DROP VIEW IF EXISTS mv_state_sales;

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

-- ============================================================================
-- 3. mv_category_sales - 品类销售情况视图
-- 粒度：年-月-品类
-- 用途：品类表现分析、识别下降品类
-- ============================================================================
DROP VIEW IF EXISTS mv_category_sales;

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
GROUP BY DATE_FORMAT(o.order_purchase_timestamp, '%Y-%m'), COALESCE(pct.product_category_name_english, p.product_category_name);

-- ============================================================================
-- 4. mv_delivery_perf - 配送绩效视图
-- 粒度：年-月-州
-- 用途：配送延迟诊断、准时率分析
-- ============================================================================
DROP VIEW IF EXISTS mv_delivery_perf;

CREATE VIEW mv_delivery_perf AS
SELECT
    DATE_FORMAT(o.order_purchase_timestamp, '%Y-%m') AS `year_month`,
    c.customer_state,
    AVG(DATEDIFF(o.order_delivered_customer_date, o.order_purchase_timestamp)) AS avg_delivery_days,
    SUM(CASE WHEN o.order_delivered_customer_date <= o.order_estimated_delivery_date THEN 1 ELSE 0 END) * 1.0 / COUNT(*) AS on_time_rate,
    SUM(CASE WHEN o.order_delivered_customer_date > o.order_estimated_delivery_date THEN 1 ELSE 0 END) AS delayed_orders
FROM orders o
INNER JOIN customers c ON o.customer_id = c.customer_id
WHERE o.order_status = 'delivered'
  AND o.order_delivered_customer_date IS NOT NULL
GROUP BY DATE_FORMAT(o.order_purchase_timestamp, '%Y-%m'), c.customer_state;

-- ============================================================================
-- 5. mv_seller_perf - 卖家绩效视图（推荐）
-- 粒度：年-月-卖家
-- 用途：卖家绩效监控、高差评卖家定位
-- ============================================================================
DROP VIEW IF EXISTS mv_seller_perf;

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

-- ============================================================================
-- 6. mv_payment_dist - 支付分布视图（推荐）
-- 粒度：年-月-支付类型
-- 用途：支付偏好分析、分期率对比
-- ============================================================================
DROP VIEW IF EXISTS mv_payment_dist;

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

-- ============================================================================
-- 脚本执行完成
-- 说明：以上视图使用CREATE VIEW创建，会自动反映基础表数据变化
-- ============================================================================
