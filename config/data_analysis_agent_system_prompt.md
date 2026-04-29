# 数据分析 Agent Prompt 入口（拆分版）

当前 Prompt 已拆分为 3 层，请按顺序加载：

1. `config/data_analysis_agent_prompt_system_core.md`
   - 常驻系统规则（必须每次加载）
   - 包含：MySQL 约束、视图优先策略、回退机制、输出格式

2. `config/data_analysis_agent_prompt_schema_dictionary.md`
   - 表/视图字段字典（建议按需注入）
   - 包含：每张原始表与预聚合视图的字段说明、主键、常用口径

3. `config/data_analysis_agent_prompt_routing_examples.md`
   - 路由映射与 few-shot（建议按需注入）
   - 包含：问题到视图映射、多主题拆分示例、回退示例

## 推荐加载策略

- 基础模式（低 token）：
  - 固定加载 `system_core`
  - 仅注入与问题相关的数据字典片段
  - 在复杂问题时再注入 `routing_examples`

- 增强模式（高成功率）：
  - 每轮加载 `system_core + routing_examples`
  - 同时按需拼接 `schema_dictionary` 的相关章节
