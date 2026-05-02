# 数据分析 Agent 路由与示例 Prompt（Few-shot）

## 1) 问题到视图的优先映射

- “每月销售额/GMV/订单趋势” -> `mv_monthly_sales`
- “各州销售额排名/区域对比” -> `mv_state_sales`
- “品类表现/下降品类/品类客单” -> `mv_category_sales`
- “准时率/平均配送时长/延迟州” -> `mv_delivery_perf`
- “卖家绩效/评分低卖家” -> `mv_seller_perf`
- “支付方式占比/分期数” -> `mv_payment_dist`

## 2) 多主题问题拆分规则

若一个问题同时包含多个业务主题，拆成多个子查询并优先命中对应视图，再汇总结果：

- 例：“2017年哪个州销售额最高？交付准时率是多少？哪种支付方式最受欢迎？”
  - 子查询 1 -> `mv_state_sales`
  - 子查询 2 -> `mv_delivery_perf`
  - 子查询 3 -> `mv_payment_dist`

## 3) Few-shot 示例

### 示例 A：命中单视图
用户问题：`2017 年每个月 GMV 是多少？`

应优先使用：`mv_monthly_sales`

```sql
SELECT
  year_month,
  total_gmv
FROM mv_monthly_sales
WHERE year_month BETWEEN '2017-01' AND '2017-12'
ORDER BY year_month;
```

### 示例 B：命中多视图
用户问题：`2017年哪个州销售额最高？交付准时率是多少？哪种支付方式最受欢迎？`

策略：拆分为 3 条 SQL，分别命中 `mv_state_sales`、`mv_delivery_perf`、`mv_payment_dist`，最终在应用层合并摘要。

### 示例 C：回退原始表
用户问题：`产品重量、体积与运费之间有什么关系？`

原因：预聚合视图不含 `product_weight_g / product_length_cm / product_height_cm / product_width_cm` 等明细字段，需回退 `orders + order_items + products` 做明细抽取与聚合。

## 4) 视图优先原则（再次强调）

1. 能命中视图就不用大表实时 JOIN。
2. 视图能二次计算得到的指标仍算命中。
3. 只有视图维度或字段不满足时才回退原始表。
