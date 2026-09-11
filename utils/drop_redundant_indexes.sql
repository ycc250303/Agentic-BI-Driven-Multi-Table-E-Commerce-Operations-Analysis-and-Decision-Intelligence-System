-- 删除与主键（或主键左前缀 / 复合索引左前缀）重复的二级索引。
-- 适用于已经导入数据的库；新建库请直接用 create_origin_table.sql（其中已不再创建这些索引）。
-- 不删表、不改数据。可重复执行：索引不存在则跳过由调用方处理。

ALTER TABLE orders DROP INDEX idx_orders_order_id;
ALTER TABLE order_items DROP INDEX idx_order_items_order_id;
ALTER TABLE products DROP INDEX idx_products_product_id;
ALTER TABLE customers DROP INDEX idx_customers_customer_id;
ALTER TABLE customers DROP INDEX idx_customers_customer_city;
ALTER TABLE sellers DROP INDEX idx_sellers_seller_id;
ALTER TABLE sellers DROP INDEX idx_sellers_seller_city;
ALTER TABLE payments DROP INDEX idx_payments_order_id_payment_sequential;
ALTER TABLE order_reviews DROP INDEX idx_order_reviews_review_id;
ALTER TABLE product_category_name_translation DROP INDEX idx_pcnt_product_category_name;
