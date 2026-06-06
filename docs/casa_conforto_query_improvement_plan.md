# casa_conforto 类目查询失败场景改进清单

## 1. 问题背景

用户执行：

```powershell
python -m agents.coordinator_agent.run_session --new --query "人们对 casa_conforto 类产品的评价如何？入行此类产品是否有前景？" --sse
```

系统最终回答中出现：

> 目前系统未能直接提取到 casa_conforto 类产品的具体评分和评价数量。

但数据库中 `products.product_category_name` 明确存在 `casa_conforto`。经排查，这不是 SSE 输出问题，也不是 `products` 表缺数据，而是多处链路缺少“类目字面量保真”和“空结果自愈”能力。

## 2. 已验证事实

在 `.env` 指向的当前数据库中验证到：

- `products.product_category_name = 'casa_conforto'` 存在，产品数为 `111`。
- 使用原始类目字段正确查询评论，可得到：
  - 平均评分：`3.84`
  - 评论数：`396`
  - 差评数：`86`
  - 差评率：约 `21.72%`
- `mv_category_sales.product_category_english` 中也存在 `casa_conforto`：
  - 总 GMV：`58572.04`
  - 订单数：`397`
- 系统本轮实际生成的错误过滤值为：
  - `house comfort`
  - `household_comfort`
- 上述两个过滤值在当前库中均查不到，因此 SQL 执行成功但返回 `0` 行。

仓库中的 `data/product_category_name_translation.csv` 包含：

```csv
casa_conforto,home_confort
casa_conforto_2,home_comfort_2
```

注意：原始 Olist 映射里是 `home_confort`，不是 `house comfort`，也不是 `household_comfort`。

## 3. 直接根因

### 3.1 SQL Agent 错误翻译了用户给出的数据库类目值

用户输入中的 `casa_conforto` 是一个明确的数据库维度值，形态上也是典型的 snake_case 类目编码。SQL Agent 不应把它自由翻译成英文自然语言。

本次 rewrite 阶段将其解释为：

```text
casa_conforto -> house comfort
```

后续 generate_sql 阶段又将市场前景查询改成：

```text
casa_conforto -> household_comfort
```

这导致评价查询和销售趋势查询都错过了真实数据。

### 3.2 当前 SQL 校验只检查语法与安全，不检查字面量存在性

`agents/sql_agent/tools/check_sql.py` 明确是本地校验，不访问数据库。它能发现非 SELECT、格式不合规、危险语句等问题，但不能发现：

- `WHERE product_category_english = 'household_comfort'` 这种值不存在的问题。
- SQL 返回 0 行是否违背用户显式查询对象的问题。

### 3.3 0 行结果被当作成功结果继续流转

`execute_sql` 返回：

```json
{
  "ok": true,
  "row_count_returned": 0
}
```

Coordinator 目前只在 `ok=false` 时追加 warning。也就是说，SQL 执行成功但业务结果为空时，不会触发修正、重试或降级提示。

最终 Synthesizer 收到的证据是“查过但没行”，于是生成了“未能直接提取”的业务话术。

### 3.4 当前数据库中的翻译表异常，加剧了问题

当前数据库里的 `product_category_name_translation` 只查到 1 行异常数据：

```text
product_category_name = ''
product_category_name_english = 'health_beauty'
```

这说明当前库的翻译表没有正确导入。即便 SQL Agent 想通过翻译表映射 `casa_conforto`，也得不到正确的 `home_confort`。

该问题不是本次查不到的唯一原因，因为最稳妥的 SQL 应该直接使用 `products.product_category_name='casa_conforto'`。但翻译表异常会放大 LLM 乱猜英文类目的概率，也会影响其他品类展示和视图聚合。

## 4. 需要改进的地方

### P0-1. 强化类目值保真规则

涉及位置：

- `config/data_analysis_agent/rewrite_to_query_tool.md`
- `config/data_analysis_agent/generate_sql_tool.md`
- `config/data_analysis_agent/schema_dictionary.md`

改进要求：

1. 当用户输入中出现 snake_case 形态的类目名，如 `casa_conforto`、`cama_mesa_banho`，必须优先视为数据库原始枚举值。
2. 不允许把显式类目值自由翻译成英文自然语言。
3. 若需要展示英文名，只能作为 SELECT 展示字段，不能替代 WHERE 过滤条件。
4. 生成 SQL 时应优先使用：

```sql
WHERE `p`.`product_category_name` = 'casa_conforto'
```

5. 如果同时支持翻译表，可使用兜底 OR 条件：

```sql
WHERE `p`.`product_category_name` = 'casa_conforto'
   OR `pct`.`product_category_name_english` = 'casa_conforto'
```

6. 对 `mv_category_sales` 这种已经 COALESCE 后的视图，应优先尝试原始值：

```sql
WHERE `product_category_english` = 'casa_conforto'
```

如果系统有可靠映射表，再追加映射值：

```sql
WHERE `product_category_english` IN ('casa_conforto', 'home_confort')
```

### P0-2. 增加维度值存在性校验

建议新增一个轻量工具，例如：

```text
validate_dimension_values_tool
```

职责：

- 从 rewrite/generate 阶段提取维度过滤值。
- 对关键维度执行只读存在性检查。
- 在执行正式 SQL 前发现明显错误的类目名。

针对品类可检查：

```sql
SELECT 'products.product_category_name' AS source, COUNT(*) AS cnt
FROM products
WHERE product_category_name = %s
UNION ALL
SELECT 'product_category_name_translation.product_category_name_english', COUNT(*)
FROM product_category_name_translation
WHERE product_category_name_english = %s
UNION ALL
SELECT 'mv_category_sales.product_category_english', COUNT(*)
FROM mv_category_sales
WHERE product_category_english = %s
```

预期行为：

- 如果 `house comfort` / `household_comfort` 的计数全为 0，而用户原始词 `casa_conforto` 有命中，应自动反馈给 SQL 生成环节重试。
- 如果所有候选都为 0，应明确告诉上游“过滤值不存在”，而不是生成看似正常但必为空的 SQL。

### P0-3. 0 行结果触发自愈重试

当前 `execute_sql` 成功但返回 0 行时不会触发失败。建议在 SQL pipeline 中补充业务空结果判断。

触发条件：

- 用户问题存在显式实体或维度值，如 `casa_conforto`。
- SQL 执行成功。
- 所有核心 SQL 返回 0 行。
- SQL 中使用了与用户原始词不同的过滤字面量。

重试策略：

1. 把执行摘要反馈给 `generate_sql_tool`：

```text
上一次 SQL 执行成功但返回 0 行。
用户原始类目为 casa_conforto。
上次 SQL 使用了不存在的过滤值 household_comfort。
请保留原始类目值，优先过滤 products.product_category_name = 'casa_conforto'。
```

2. 最多重试 1 到 2 次，避免死循环。
3. 重试后仍为空，则在最终回答中明确说明：

```text
已尝试按原始类目和英文映射查询，均未命中。
```

而不是笼统写“系统未能直接提取”。

### P0-4. 修复并校验翻译表导入

当前库中的 `product_category_name_translation` 明显不完整。需要修复数据装载流程。

建议动作：

1. 检查 `utils/load_data_to_mysql.py` 中 schema 文件路径。

当前代码指向：

```python
SCHEMA_SQL = ROOT_DIR / "utils" / "origin_table.sql"
```

但仓库实际文件是：

```text
utils/create_origin_table.sql
```

需要统一文件名，避免初始化脚本无法可靠建表。

2. 读取 CSV 时使用 `utf-8-sig`，避免 BOM 造成首列字段名无法匹配。

建议：

```python
with csv_file.open("r", encoding="utf-8-sig", newline="") as f:
```

3. 对主键字段为空的行直接报错或跳过并记录，而不是 `INSERT IGNORE` 后静默留下异常空主键。

4. 导入后增加表级质量检查：

```sql
SELECT COUNT(*) FROM product_category_name_translation;
SELECT * FROM product_category_name_translation
WHERE product_category_name = 'casa_conforto';
SELECT COUNT(*) FROM product_category_name_translation
WHERE product_category_name = '';
```

期望：

- 翻译表行数应接近 CSV 行数。
- `casa_conforto -> home_confort` 必须存在。
- 空 `product_category_name` 行数应为 0。

### P1-1. Synthesizer 应识别“空结果”和“无证据”的差异

当前最终回答把“SQL 查了 0 行”自然语言化为“未能直接提取”，但没有解释原因，也没有暴露关键诊断信息。

建议在 `build_synthesis_evidence` 中加入：

```json
{
  "empty_sql_results": [
    {
      "question": "...",
      "sql_filter_values": ["house comfort"],
      "row_count": 0,
      "suspected_reason": "category literal may not exist"
    }
  ]
}
```

Synthesizer prompt 应要求：

- 如果 SQL 为空但存在显式过滤值，要说明“查询条件未命中”，而不是说“数据限制”。
- 如果系统已发现候选值不存在，要明确提示可能是类目映射错误。
- 不得用相关品类替代目标品类作结论，除非明确标注为“参考”。

### P1-2. 增加预聚合视图与原始字段关系说明

`mv_category_sales.product_category_english` 的名字容易误导 SQL Agent，以为它一定是英文名。但该视图实际使用：

```sql
COALESCE(pct.product_category_name_english, p.product_category_name)
```

如果翻译缺失或翻译表异常，视图中会保留原始葡语类目名。

需要在 `schema_dictionary.md` 中明确：

- `product_category_english` 是展示名，不保证一定英文。
- 过滤用户给出的原始类目值时，不应强制转换为英文。
- 对于精确类目筛选，原始表 `products.product_category_name` 是更可靠的事实源。

### P2-1. 增加回归测试

建议新增测试覆盖：

1. `rewrite_to_query` 类目保真测试

输入：

```text
人们对 casa_conforto 类产品的评价如何？
```

断言：

- 输出中保留 `casa_conforto`。
- 不出现 `house comfort`、`household_comfort`。

2. `generate_sql` 类目过滤测试

断言生成 SQL 包含：

```sql
`p`.`product_category_name` = 'casa_conforto'
```

或视图场景：

```sql
`product_category_english` = 'casa_conforto'
```

3. 0 行自愈测试

模拟第一次 SQL 返回 0 行，且过滤值为 `household_comfort`，期望二次生成使用 `casa_conforto`。

4. 翻译表导入测试

断言导入后：

```sql
SELECT product_category_name_english
FROM product_category_name_translation
WHERE product_category_name = 'casa_conforto'
```

返回 `home_confort`。

5. 端到端 session 测试

执行同类问题后，最终回答必须包含：

- 平均评分 `3.84`
- 评论数 `396`
- 至少一个销售规模指标，如 GMV `58572.04` 或订单数 `397`

### P2-2. 增加运行期可观测性

建议在 trace event 中增加以下元数据：

```json
{
  "dimension_filters": [
    {
      "field": "product_category_english",
      "value": "household_comfort",
      "source": "llm_generated",
      "matched_rows": 0
    }
  ],
  "empty_result": true,
  "retry_reason": "dimension value did not match database"
}
```

这样前端/SSE 日志中可以直接看到问题是“过滤值不命中”，而不是只看到“SQL 成功、返回 0 行”。

## 5. 推荐修复顺序

### 第一阶段：立刻阻断错误回答

1. 修改 prompt：保留 snake_case 类目值，不自由翻译。
2. SQL 生成优先按 `products.product_category_name` 过滤。
3. 0 行结果触发 warning，至少让最终回答不要说成“数据限制”。

### 第二阶段：让系统自动修复

1. 增加维度值存在性校验工具。
2. 将 0 行结果反馈给 `generate_sql_tool` 重试。
3. 在 trace 中记录过滤值和命中行数。

### 第三阶段：补齐数据与测试

1. 修复翻译表导入脚本。
2. 重新导入并校验 `product_category_name_translation`。
3. 增加 `casa_conforto` 端到端回归测试。

## 6. 正确查询示例

### 6.1 casa_conforto 评论概览

```sql
SELECT
    p.product_category_name AS category,
    ROUND(AVG(r.review_score), 2) AS avg_review_score,
    COUNT(DISTINCT r.review_id) AS total_reviews,
    SUM(CASE WHEN r.review_score <= 2 THEN 1 ELSE 0 END) AS bad_reviews,
    ROUND(
        SUM(CASE WHEN r.review_score <= 2 THEN 1 ELSE 0 END)
        / NULLIF(COUNT(DISTINCT r.review_id), 0),
        4
    ) AS bad_review_rate
FROM orders o
JOIN order_reviews r ON o.order_id = r.order_id
JOIN order_items oi ON o.order_id = oi.order_id
JOIN products p ON oi.product_id = p.product_id
WHERE p.product_category_name = 'casa_conforto'
GROUP BY p.product_category_name;
```

### 6.2 casa_conforto 销售规模

```sql
SELECT
    product_category_english AS category,
    ROUND(SUM(total_gmv), 2) AS total_gmv,
    SUM(total_orders) AS total_orders
FROM mv_category_sales
WHERE product_category_english = 'casa_conforto'
GROUP BY product_category_english;
```

### 6.3 casa_conforto 月度趋势

```sql
SELECT
    year_month,
    ROUND(SUM(total_gmv), 2) AS total_gmv,
    SUM(total_orders) AS total_orders
FROM mv_category_sales
WHERE product_category_english = 'casa_conforto'
GROUP BY year_month
ORDER BY year_month;
```

## 7. 验收标准

修复完成后，同一命令再次执行时应满足：

1. 评价部分能直接给出 `casa_conforto` 的评分和评论数量。
2. 销售前景部分能直接给出该类目的 GMV、订单数和月度趋势。
3. 最终回答不得再声称“未能直接提取具体评分和评价数量”。
4. 如果翻译表异常，系统仍能依靠 `products.product_category_name` 正确查询。
5. 若未来遇到其他不存在的类目值，系统能明确提示“类目值未命中”，而不是用全局或相关品类结果替代目标类目。
