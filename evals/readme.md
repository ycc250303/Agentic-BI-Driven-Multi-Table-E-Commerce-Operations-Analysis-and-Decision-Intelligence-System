# 数据分析评测

`evals/` 存放数据分析 Agent 的离线评测：本地样本、同步到 LangSmith 的实验入口，以及查数与澄清两类终态各自的评分规则。

## 评测方法

维护来源是 `evals/datasets/analysis_mvp.json`。启动后按每条样本的 `metadata.case_id` 生成稳定 Example ID，把输入、参考输出、元数据和 LangSmith 原生 Split 同步到数据集 `agentic-bi-analysis`：已有样本更新，本地新增的样本创建，远程多出的样本删除，同步后再读回核对。随后用真实模型、只读库和完整分析链路逐条作答，串行跑一次实验。查数样本比较终态、规范化后的核心语义，以及完整 CSV 与 Gold SQL 的执行结果；澄清样本比较待补充终态、稳定澄清原因、问题是否存在，以及是否确实没有 Evidence。

## 启动命令

在仓库根目录执行。项目已安装，`.env` 已配置模型密钥、MySQL 只读账号和 `LANGSMITH_API_KEY`，库与 `mv_*` 视图已建好。

```bash
python evals/analysis_experiment.py
```

终端打印数据集标识、实验链接和每条问题实际产生的 feedback。查数样本包含 `status_match`、`semantic_match`、`execution_accuracy`；澄清样本包含 `status_match`、`semantic_match`、`clarification_has_question`、`clarification_has_no_evidence`。实验名前缀为 `analysis-{提供商}-{模型}`，重复次数为 1。

每次执行只进行一轮串行评测。需要观察模型输出波动时，由开发者重复执行同一命令，每次运行都会在 LangSmith 中生成独立实验。

## 数据集结构

根对象包含 `dataset_name`、`description` 和非空 `examples`。`metadata.case_id` 在数据集内唯一。`split` 写在样本顶层。

查数题 24 条，`easy`、`mid`、`hard` 各 8 条。查数题的 `split` 与 `metadata.difficulty` 相同。澄清题 6 条，`split` 为 `clarification`，难度仍写在 `metadata.difficulty`，三档各 2 条。

- `easy`：Gold SQL 只访问 1 张原始表。澄清题只缺一个可以直接问清的条件，例如指代或时间。
- `mid`：访问 2 张原始表。澄清题缺少评价指标，或分组粒度无法从目录确定。
- `hard`：访问 3 张及以上原始表。澄清题同时涉及多个无法综合的指标，或包含前后依赖的两步查数。

每档查数题里都有直接聚合，也有日期函数、日期间隔、条件表达式、列间加减或除法。查数题覆盖订单、订单明细、客户、卖家、商品、类目翻译、支付和评论。销售、订单量、客户、运费、商品金额、支付和评分只统计非已取消、非不可用的订单。配送天数、准时率、延迟率和延迟订单数只统计已送达且客户签收时间不为空的订单。英文品类使用翻译表，缺少译文时保留原品类名。成交额是商品价格加运费；品类视图中的成交额列是仅商品价格合计，不包含运费。

澄清题的六个角度是：缺少上文指代、时间范围无法确定、评价指标缺失、分组粒度无法确定、多个指标没有综合规则、前后依赖的两个查数任务。分组维度必须落在全部所选指标的允许维度交集内，并且问题原文要包含该维度的目录名称。配送类指标只允许销售月份、客户州、客户城市。比较高低或多少时没有点名维度，需要重新确认分组维度。

| 位置 | 字段 | 含义 |
| --- | --- | --- |
| `inputs` | `task_id` | 任务标识，传给 `AnalysisRequest` |
| `inputs` | `question` | 交给数据分析 Agent 的自然语言问题；澄清样本可以故意缺少必要上下文 |
| `inputs` | `locale` | 结论文案语言，当前为 `zh-CN` |
| `outputs` | `expected_status` | 期望终态，当前为 `success` 或 `needs_input` |
| `outputs` | `intent` | 查数样本的参考语义：`metric_ids`、`dimensions`、`filters`、`time_range` |
| `outputs` | `gold_sql` | 查数样本的参考 SQL；澄清样本为 `null` |
| `outputs` | `expected_clarification_code` | 澄清样本的稳定原因；查数样本不提供 |
| `metadata` | `case_id` | 稳定样本标识，用于同步 |
| `metadata` | `question_family` | 问法族，供检索，不参与评分 |
| `metadata` | `difficulty` | 难度标签：`easy`、`mid`、`hard` |
| `metadata` | `tables` | 查数题 Gold SQL 访问的原始表 |
| 顶层 | `split` | LangSmith 原生 Split |

## 通过标准

查数样本通过，要求 `status_match = true`、`semantic_match = true` 和
`execution_accuracy = true` 同时成立。澄清样本通过，要求 `status_match = true`、
`semantic_match = true`、`clarification_has_question = true` 和
`clarification_has_no_evidence = true` 同时成立。`semantic_match` 在澄清样本中表示稳定原因匹配，
便于按同一列汇总语义正确率。评估器没有生成 `case_pass` 总分，也不会因某个分数为 `false`
自动让评估进程返回非零状态。

### `status_match = true`

实际终态与数据集中的期望终态严格相等：

```text
outputs.status == reference_outputs.expected_status
```

- `expected_status` 为 `success` 时，实际终态必须为 `success`；`partial` 不通过。
- `expected_status` 为 `needs_input` 时，实际终态必须为 `needs_input`。

### `semantic_match = true`

参考终态为 `success` 时，实际 `intent` 与数据集参考 `intent` 经过规范化后必须完全相同。
评估范围包含指标口径、结果粒度、业务筛选和时间范围四组会改变查询结果的业务语义：

- `metric_ids`：本次查询需要计算的标准业务指标。每个值指向指标目录中的确定口径、单位和
  聚合方式；例如 `total_gmv` 表示商品成交价格与运费之和，单位为 BRL。多个指标的原始顺序
  不影响业务含义，因此排序后比较。
- `dimensions`：查询结果按照哪些业务属性分组，决定每一行数据代表的粒度；例如
  `customer_state` 表示按照客户收货地址所在州分别汇总，为空表示整个查询范围汇总为一个结果。
  多个维度的原始顺序不影响分组含义，因此排序后比较。
- `filters`：时间范围之外的业务筛选条件，用来限定哪些记录参与计算。每个条件中的 `field`
  表示被筛选的业务属性，例如客户州；`operator` 表示比较关系，例如等于、包含或区间；
  `value` 表示用于比较的目标值。所有条件按稳定 JSON 排序后比较，条件的原始顺序不影响结果；
  `in` 和 `not_in` 的候选值列表也会排序，`between` 的两个值分别表示区间下边界和上边界，
  交换边界会失败。
- `time_range`：哪些业务日期参与计算的左闭右开区间。`start` 表示包含的开始日期，`end`
  表示不包含的结束日期；例如完整的 2017 年表示从 `2017-01-01` 开始，到 `2018-01-01`
  结束。两个日期必须与参考值相同，JSON 对象的键顺序不影响结果。

参考终态为 `needs_input` 时，实际 `clarification_code` 必须与数据集中的
`expected_clarification_code` 相同：

```text
outputs.clarification_code == reference_outputs.expected_clarification_code
```

澄清问题的自然语言文本不做逐字比较；`clarification_has_question` 仍要求至少一条可展示问题。

### `execution_accuracy = true`

参考终态为 `success` 时，目标函数读取 Evidence 中唯一 CSV Artifact 的全部行，评估器使用
只读数据库执行 `gold_sql`，随后比较两组完整结果。以下条件必须全部满足：

1. CSV 结果行数与 Gold SQL 结果行数相同。
2. 比较列以 Gold SQL 的输出列为准；CSV 的额外列不参与比较，缺少 Gold 列会造成对应值无法匹配。
3. 行顺序不影响结果；重复行按照出现次数比较。
4. CSV 空字符串按 `None` 比较。
5. Gold 结果中的数值列会使对应 CSV 字符串转换为 `Decimal` 后再比较。
6. 列名以 `_gmv`、`_freight` 结尾，或者以 `avg_` 开头时，两侧数值统一保留两位小数。
7. 经过上述处理后，两组行的多重集合完全相同。

成功路径还要求 Evidence 存在，并且必须且只能包含一个使用本地 `file` URI 的 CSV Artifact；
不满足时目标函数直接抛出异常，本条样本无法得到正常的 `execution_accuracy` 分数。

参考终态为 `needs_input` 时不生成 `execution_accuracy`。这类样本使用
`clarification_has_no_evidence` 检查以下三个条件：

```text
outputs.has_evidence is false
outputs.returned_row_count is None
outputs.rows == []
```

结合 `status_match = true`，表示 Agent 返回 `needs_input`，并且没有形成查询证据。
失败、成功或部分成功终态都无法借助空结果获得查数正确分数。

## 目标函数与评估器

`target` 把样本 `inputs` 校验为 `AnalysisRequest` 并调用 `run_analysis`，返回评估器使用的公开字段。

| 字段 | 含义 |
| --- | --- |
| `status` | 分析终态 |
| `error_code` | 失败时的错误码，成功时为空 |
| `intent` | `metric_ids`、`dimensions`、`filters`、`time_range`。只从 Evidence 提取，供查数样本比较 |
| `rows` | 证据指向的 CSV Artifact 的全部行；没有证据时为空列表 |
| `has_evidence` | 是否形成 Evidence，用于阻止错误澄清终态借助空行通过 |
| `returned_row_count` | 证据声明的返回行数；没有证据时为空 |
| `clarification_code` | 待补充终态的稳定澄清原因；其他终态为空 |
| `clarification_questions` | 待澄清问题；没有已识别语义时为空列表 |

成功结果必须且只能有一个本地 `file` CSV Artifact。

`analysis_evaluators` 接收目标输出和参考输出，根据 `expected_status` 选择查数评分或澄清评分。每个分数是布尔值，随 `client.evaluate` 写入实验 feedback。
