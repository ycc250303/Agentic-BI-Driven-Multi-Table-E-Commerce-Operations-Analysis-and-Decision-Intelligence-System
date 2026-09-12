# 预聚合视图使用文档

## 📋 项目概述

为满足作业要求中关于"预聚合视图（Pre-Aggregation）"的需求，本项目构建了6个预聚合视图作为查询加速层，用于提升Agentic BI系统的数据分析性能。

---

### 作业要求对应

根据[assignment.md](assignment.md)第58-82行要求：

- ✅ 在 `utils/` 目录下提供预聚合视图创建脚本（SQL）
- ✅ 所有视图基于原始表一次性计算
- ✅ 可通过脚本一键刷新
- ✅ 提供视图元数据供Agent使用

---

## 📊 视图列表

| 视图名称 | 粒度 | 记录数 | 核心字段 | 用途 |
|---------|------|--------|---------|------|
| **mv_monthly_sales** | 年-月 | 24 | sales_month, total_gmv, total_orders, avg_basket, total_freight | 月度销售趋势、GMV环比增长 |
| **mv_state_sales** | 年-月-州 | 558 | sales_month, customer_state, total_gmv, total_orders, unique_customers | 各州销售额排名、区域市场对比 |
| **mv_category_sales** | 年-月-品类 | 1,282 | sales_month, product_category_english, total_gmv, total_orders, avg_price | 品类表现分析、识别下降品类 |
| **mv_delivery_perf** | 年-月-州 | 556 | sales_month, customer_state, avg_delivery_days, on_time_rate, delayed_orders | 配送延迟诊断、准时率分析 |
| **mv_seller_perf** | 年-月-卖家 | 16,308 | sales_month, seller_id, seller_state, total_gmv, total_orders, avg_review_score | 卖家绩效监控、高差评卖家定位 |
| **mv_payment_dist** | 年-月-支付类型 | 87 | sales_month, payment_type, total_transactions, avg_installments, total_value | 支付偏好分析、分期率对比 |

---

## 📁 文件结构

```
Agentic-BI-Driven-Multi-Table-E-Commerce-Operations-Analysis-and-Decision-Intelligence-System/
│
├── utils/
│   ├── setup.py                      # 建库 / 导 CSV / 刷新视图
│   ├── schema.sql                    # 原始表 + NLP 表 + 预聚合视图 DDL
│   └── readme.md
│
└── config/
    └── view_metadata.json            # 视图元数据配置
```

### 文件说明

#### 1. `utils/schema.sql`（`@section views`）
预聚合视图的 SQL 定义，包含：
- 6 个视图的完整 CREATE VIEW 语句
- 详细的注释说明
- 年月列命名为 `sales_month`（YYYY-MM），避免 MySQL 保留字 `YEAR_MONTH`

**特点**：
- 基于原始表一次性计算
- 过滤掉 canceled 和 unavailable 状态的订单
- 自动反映基础表数据变化

#### 2. `utils/setup.py views`
一键删除并重建所有视图，并打印各视图行数。

**使用方法**：
```bash
python utils/setup.py views
```

#### 3. `config/view_metadata.json`
视图元数据配置文件，供数据分析Agent使用，包含：
- 每个视图的详细描述
- 字段列表及业务含义
- 适用查询场景示例
- Agent匹配规则和使用指南

**结构示例**：
```json
{
  "views": {
    "mv_monthly_sales": {
      "description": "月度销售趋势视图",
      "fields": [...],
      "use_cases": [...],
      "example_questions": [...]
    }
  },
  "agent_usage_guide": {
    "matching_rules": [...],
    "fallback_strategy": "..."
  }
}
```

---

## 🚀 使用方法

### 方法1：命令行刷新视图

```bash
python utils/setup.py views
```

## ⚠️ 重要注意事项

### 1. 年月列名为 sales_month

视图把购买时间聚成 `YYYY-MM` 字符串，物理列名是 **`sales_month`**（不是保留字 `YEAR_MONTH`）。查询时直接写裸标识符即可，不要加反引号：

```sql
SELECT * FROM mv_monthly_sales ORDER BY sales_month DESC;
```

旧名 `year_month` 已废弃；若仍按旧名查询会报未知列。

### 2. 订单状态过滤

所有视图已自动过滤掉以下状态的订单：
- `canceled` - 已取消
- `unavailable` - 不可用

**例外**：`mv_delivery_perf` 只包含 `delivered`（已送达）状态的订单。

### 3. 视图类型说明

本项目使用 **CREATE VIEW** 创建虚拟视图，特点：
- ✅ 优点：自动反映基础表数据变化，无需手动刷新
- ⚠️ 注意：查询时实时计算，不是物化表

如需更新视图定义（如修改SQL逻辑），重新运行 `python utils/setup.py views` 即可。

### 4. 数据时间范围

- **开始时间**: 2016-09
- **结束时间**: 2018-10
- **总月份数**: 24个月

---

## 🔧 Agent集成指南

### 数据分析Agent使用流程

数据分析Agent应参考 `config/view_metadata.json` 实现以下逻辑：

#### 步骤1：问题分析

用户问题示例：
> "2017年每个月的销售额是多少？"

#### 步骤2：视图匹配

Agent根据关键词匹配可用视图：
- 时间维度关键词："月"、"月份"、"月度"
- 销售维度关键词："销售"、"销售额"、"GMV"

匹配结果：`mv_monthly_sales`

#### 步骤3：SQL生成

```python
# 伪代码示例
def generate_sql(question, matched_view):
    if matched_view == "mv_monthly_sales":
        return "SELECT * FROM mv_monthly_sales WHERE sales_month LIKE '2017%'"
```

#### 步骤4：查询执行

优先使用预聚合视图查询，性能更优。

#### 步骤5：回退机制

如果问题维度不在任何预聚合视图中，回退到基础表查询：

```python
# 示例：查询具体订单详情
if "订单详情" in question and "order_id" in question:
    # 回退到基础表
    sql = """
        SELECT o.*, c.customer_state
        FROM orders o
        JOIN customers c ON o.customer_id = c.customer_id
        WHERE o.order_id = 'xxx'
    """
```

### 匹配规则参考

| 问题关键词 | 推荐视图 |
|-----------|---------|
| 月度/月份/月度趋势 | mv_monthly_sales |
| 州/地区/区域/SP/RJ/MG | mv_state_sales |
| 品类/类别/产品/商品 | mv_category_sales |
| 配送/物流/准时/延迟 | mv_delivery_perf |
| 卖家/商家 | mv_seller_perf |
| 支付/付款/分期/credit_card | mv_payment_dist |

---

## 📈 验证结果

所有视图已通过数据验证，结果正确：

### 1. mv_monthly_sales（月度销售）
- 24个月数据，GMV和订单量趋势合理
- 2017年11月达到峰值

### 2. mv_state_sales（各州销售）
- SP（圣保罗州）销售额最高，符合巴西经济现状
- RJ（里约热内卢）、MG（米纳斯吉拉斯）紧随其后

### 3. mv_category_sales（品类销售）
- relogios_presentes（手表礼品）领先
- beleza_saude（健康美容）、esporte_lazer（运动休闲）居前

### 4. mv_delivery_perf（配送绩效）
- 北部地区（AM、AP、PA）配送时间较长
- 符合地理实际情况

### 5. mv_payment_dist（支付分布）
- credit_card 占主导（约76%）
- boleto（汇票）次之（约19%）

### 6. mv_seller_perf（卖家绩效）
- Top卖家集中在SP、RJ等经济发达州
- 评分分布合理

---

## 🔍 常见问题 FAQ

### Q1: 为什么查询时报未知列 year_month？

**A**: 年月列已改名为 `sales_month`。正确写法：

```sql
ORDER BY sales_month DESC
```

### Q2: 视图数据会自动更新吗？

**A**: 是的。使用CREATE VIEW创建的虚拟视图会自动反映基础表的最新数据。如果基础表有新增或修改，视图查询时会自动包含最新数据。

### Q3: 如何修改视图定义？

**A**:
1. 编辑 `utils/schema.sql` 的 `@section views`
2. 运行 `python utils/setup.py views` 重建视图

### Q4: 为什么 mv_delivery_perf 的记录数少于其他视图？

**A**: 因为配送绩效视图只包含 `delivered`（已送达）状态的订单，且需要 `order_delivered_customer_date` 不为空。

### Q5: Agent如何判断是否使用预聚合视图？

**A**: 参考 `config/view_metadata.json` 中的 `agent_usage_guide` 部分，包含详细的匹配规则和回退策略。

### Q6: 性能对比测试如何做？

**A**: 由 lyf 负责的测试程序会对比：
- 使用预聚合视图的查询时间
- 使用基础表JOIN的查询时间

结果将在项目报告中展示。

---

## 🛠️ 技术细节

### 数据库配置

```python
DB_CONFIG = {
    "host": "111.229.81.45",
    "port": 3306,
    "user": "agentic_bi",
    "password": "agentic_bi",
    "database": "agentic_bi",
    "charset": "utf8mb4",
}
```

### 依赖项

```txt
mysql-connector-python==9.5.0
```

### SQL语法要点

1. **DATE_FORMAT函数**：将日期转换为年月格式
   ```sql
   DATE_FORMAT(order_purchase_timestamp, '%Y-%m') AS sales_month
   ```

2. **COALESCE函数**：处理NULL值，优先使用英文翻译
   ```sql
   COALESCE(english_name, portuguese_name) AS product_category_english
   ```

3. **CASE WHEN**：计算准时率
   ```sql
   SUM(CASE WHEN delivered_date <= estimated_date THEN 1 ELSE 0 END) * 1.0 / COUNT(*) AS on_time_rate
   ```

---