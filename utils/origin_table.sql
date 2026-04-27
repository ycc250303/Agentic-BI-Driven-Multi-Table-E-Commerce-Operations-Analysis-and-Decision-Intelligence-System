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

create index idx_orders_order_id on orders (order_id);

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

create index idx_order_items_order_id on order_items (order_id);

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

create index idx_products_product_id on products (product_id);

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

create index idx_customers_customer_id on customers (customer_id);

create index idx_customers_customer_unique_id on customers (customer_unique_id);

create index idx_customers_customer_city on customers (customer_city);

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

create index idx_sellers_seller_id on sellers (seller_id);

create index idx_sellers_seller_city on sellers (seller_city);

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

create index idx_payments_order_id_payment_sequential on payments (order_id, payment_sequential);

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

create index idx_order_reviews_review_id on order_reviews (review_id);

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

create index idx_pcnt_product_category_name on product_category_name_translation (product_category_name);

create index idx_pcnt_product_category_name_english on product_category_name_translation (product_category_name_english);