# 数据分析 Agent 数据字典 Prompt（按需注入）

## 1) 原始表（Base Tables）

### `orders`
- 作用：订单主表，定义订单生命周期与关键时间戳。
- 主键：`order_id`
- 关键字段：
  - `order_id`：订单 ID
  - `customer_id`：客户 ID（关联 `customers.customer_id`）
  - `order_status`：订单状态
  - `order_purchase_timestamp`：下单时间
  - `order_approved_at`：支付审批通过时间
  - `order_delivered_carrier_date`：交付承运商时间
  - `order_delivered_customer_date`：客户签收时间
  - `order_estimated_delivery_date`：预计送达时间

### `order_items`
- 作用：订单明细表，记录订单内商品、卖家、价格和运费。
- 主键：`(order_id, order_item_id)`
- 关键字段：
  - `order_id`：订单 ID（关联 `orders.order_id`）
  - `order_item_id`：订单内明细序号
  - `product_id`：商品 ID（关联 `products.product_id`）
  - `seller_id`：卖家 ID（关联 `sellers.seller_id`）
  - `shipping_limit_date`：最晚发货时限
  - `price`：商品成交价格
  - `freight_value`：运费金额

### `products`
- 作用：商品属性表，用于品类、重量、体积等分析。
- 主键：`product_id`
- 关键字段：
  - `product_id`：商品 ID
  - `product_category_name`：葡语品类名
  - `product_name_lenght`：商品名称长度
  - `product_description_lenght`：商品描述长度
  - `product_photos_qty`：图片数量
  - `product_weight_g`：重量（克）
  - `product_length_cm`：长度（厘米）
  - `product_height_cm`：高度（厘米）
  - `product_width_cm`：宽度（厘米）

### `customers`
- 作用：客户主数据表，用于客户地域分布分析。
- 主键：`customer_id`
- 关键字段：
  - `customer_id`：客户 ID
  - `customer_unique_id`：客户去重 ID（跨订单识别同一客户）
  - `customer_zip_code_prefix`：邮编前缀
  - `customer_city`：客户城市
  - `customer_state`：客户州

### `sellers`
- 作用：卖家主数据表，用于卖家地域与绩效分析。
- 主键：`seller_id`
- 关键字段：
  - `seller_id`：卖家 ID
  - `seller_zip_code_prefix`：卖家邮编前缀
  - `seller_city`：卖家城市
  - `seller_state`：卖家州

### `payments`
- 作用：支付明细表，用于支付方式和分期行为分析。
- 主键：`(order_id, payment_sequential)`
- 关键字段：
  - `order_id`：订单 ID（关联 `orders.order_id`）
  - `payment_sequential`：支付序号
  - `payment_type`：支付方式
  - `payment_installments`：支付分期数
  - `payment_value`：支付金额

### `order_reviews`
- 作用：评论与评分表，用于满意度、差评与文本洞察分析。
- 主键：`review_id`
- 关键字段：
  - `review_id`：评论 ID
  - `order_id`：订单 ID（关联 `orders.order_id`）
  - `review_score`：评分
  - `review_comment_title`：评论标题
  - `review_comment_message`：评论文本
  - `review_creation_date`：评论创建时间
  - `review_answer_timestamp`：评论回复时间

### `geolocation`
- 作用：地理坐标表，用于城市/州地理分布可视化。
- 主键：`(geolocation_zip_code_prefix, geolocation_lat, geolocation_lng)`
- 关键字段：
  - `geolocation_zip_code_prefix`：邮编前缀
  - `geolocation_lat`：纬度
  - `geolocation_lng`：经度
  - `geolocation_city`：城市
  - `geolocation_state`：州

### `product_category_name_translation`
- 作用：品类中英文映射表，用于品类标准化展示。
- 主键：`product_category_name`
- 关键字段：
  - `product_category_name`：葡语品类名
  - `product_category_name_english`：英语品类名

---

## 2) 预聚合视图（Pre-Aggregation Views）

### `mv_monthly_sales`
- 粒度：`year_month`
- 字段：
  - `year_month`
  - `total_gmv`
  - `total_orders`
  - `avg_basket`
  - `total_freight`
- 用途：月度 GMV、订单量、客单价、运费趋势

### `mv_state_sales`
- 粒度：`year_month + customer_state`
- 字段：
  - `year_month`
  - `customer_state`
  - `total_gmv`
  - `total_orders`
  - `unique_customers`
- 用途：州级销售排名、区域对比

### `mv_category_sales`
- 粒度：`year_month + product_category_english`
- 字段：
  - `year_month`
  - `product_category_english`
  - `total_gmv`
  - `total_orders`
  - `avg_price`
- 用途：品类表现、下降品类识别

### `mv_delivery_perf`
- 粒度：`year_month + customer_state`
- 字段：
  - `year_month`
  - `customer_state`
  - `avg_delivery_days`
  - `on_time_rate`
  - `delayed_orders`
- 用途：配送时效、延迟诊断、准时率分析
- **易错口径（生成 SQL 时必须遵守）**：
  - **`on_time_rate` 为「该年-月 × 该州」单元内的比率**，不是全平台订单级比率。**禁止**用 `SELECT on_time_rate FROM mv_delivery_perf ... ORDER BY ... LIMIT 1`、`MAX(on_time_rate)` 或对 `on_time_rate` 做无权重 `GROUP BY` 冒充「全平台整体准时率」。
  - **全平台整体准时率**：须在 `orders`（并满足 `order_status='delivered'`、签收与预计送达非空）上按订单计算 `SUM(准时) / COUNT(*)`。
  - **各州延迟严重程度**：可在本视图对 `delayed_orders` 按 `customer_state` 做 `SUM` 后排序。
  - **「某州 + 某年」单一准时率**：若仅用本视图，需先将该州该年的多个月份聚成一行（如 `AVG(on_time_rate)`，并注明“按月单元比率简单平均近似”）；更稳妥方式是回退 `orders` 做订单级计算。

### `mv_seller_perf`
- 粒度：`year_month + seller_id + seller_state`
- 字段：
  - `year_month`
  - `seller_id`
  - `seller_state`
  - `total_gmv`
  - `total_orders`
  - `avg_review_score`
- 用途：卖家绩效、低评分卖家识别

### `mv_payment_dist`
- 粒度：`year_month + payment_type`
- 字段：
  - `year_month`
  - `payment_type`
  - `total_transactions`
  - `avg_installments`
  - `total_value`
- 用途：支付偏好与分期行为分析
- **易错口径**：`avg_installments` 已是「月 × 支付方式」粒度均值。跨月汇总到「支付方式」时，应使用 **`SUM(avg_installments * total_transactions) / NULLIF(SUM(total_transactions), 0)`** 按交易笔数加权；不要直接用 `AVG(avg_installments)`。

---

## 3) 常用口径说明

- 默认 GMV 口径优先采用：`price + freight_value`（若问题要求仅商品金额，改用 `price`）。
- 订单数口径优先：`COUNT(DISTINCT order_id)`。
- 客户数口径优先：`COUNT(DISTINCT customer_unique_id)`。
