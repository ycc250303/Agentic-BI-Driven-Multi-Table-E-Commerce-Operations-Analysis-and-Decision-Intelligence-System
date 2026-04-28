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
