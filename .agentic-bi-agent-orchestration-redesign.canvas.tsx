import {
  BarChart,
  Callout,
  Card,
  CardBody,
  CardHeader,
  CollapsibleSection,
  Divider,
  Grid,
  H1,
  H2,
  H3,
  Link,
  Pill,
  Row,
  Stack,
  Stat,
  Table,
  Text,
  useState,
} from "cursor/canvas";

const VIEW_BENCHMARKS = ["月销售", "州销售", "品类", "配送", "卖家", "支付"];

type ViewMode = "架构" | "路线图" | "验证";

function FlowStep({
  title,
  caption,
  trailing,
}: {
  title: string;
  caption: string;
  trailing?: string;
}) {
  return (
    <Card>
      <CardHeader trailing={trailing}>{title}</CardHeader>
      <CardBody>
        <Text size="small" tone="secondary">
          {caption}
        </Text>
      </CardBody>
    </Card>
  );
}

function Arrow() {
  return (
    <Text style={{ textAlign: "center", alignSelf: "center" }} tone="tertiary">
      →
    </Text>
  );
}

function ArchitectureView() {
  return (
    <Stack gap={24}>
      <Stack gap={8}>
        <H2>一、协作模式：从串行总线改成计划编译器</H2>
        <Text tone="secondary">
          目标不是让更多 Agent 自由互调，而是让模型只做它擅长的语义理解与长尾修复，把依赖、并行、重试、停止条件和证据校验交给程序。
        </Text>
      </Stack>

      <Grid columns={2} gap={16}>
        <Card>
          <CardHeader trailing="现状">模型逐跳调度的多 Agent 总线</CardHeader>
          <CardBody>
            <Stack gap={10}>
              <Text>问题分解 → 协调器选一个能力 → 执行 → 回协调器 → 再选一个能力。</Text>
              <Text size="small" tone="secondary">
                分解结果已经包含建议能力，但每一步仍调用模型做路由；多条 SQL 子问题也逐条串行。代码最终又用规则覆盖部分模型决定，形成重复控制面。
              </Text>
              <Callout tone="danger" title="直接后果">
                复合问延迟随步骤线性增长；路线不易复现；NLP、预测、决策的输入边界松散；最终回答存在两个写入者。
              </Callout>
            </Stack>
          </CardBody>
        </Card>

        <Card>
          <CardHeader trailing="目标">语义计划编译器 + 专业子图</CardHeader>
          <CardBody>
            <Stack gap={10}>
              <Text>一次生成结构化执行计划，再编译为带依赖关系的任务图；独立任务并行，证据齐备后才允许生成图表、建议和最终回答。</Text>
              <Text size="small" tone="secondary">
                开放式循环只留在 SQL 长尾修复或证据审校内部，并设置最大轮次、超时和明确终止条件。
              </Text>
              <Callout tone="success" title="核心收益">
                减少重复模型调用；并行复合问；每条结论可追溯到证据；故障可从节点恢复；业务能力可独立测试。
              </Callout>
            </Stack>
          </CardBody>
        </Card>
      </Grid>

      <H3>目标控制流</H3>
      <Grid columns="1.3fr 28px 1.3fr 28px 2fr 28px 1.4fr" gap={8}>
        <FlowStep title="会话语义解析" caption="继承指标、维度、时间、州、品类等槽位；歧义时中断澄清。" trailing="输入" />
        <Arrow />
        <FlowStep title="ExecutionPlan" caption="一次产出任务、依赖、过滤、输出契约、超时与失败策略。" trailing="LLM" />
        <Arrow />
        <FlowStep title="并行专业子图" caption="指标/SQL × N、评论切片、预测、What-if；每个任务使用窄状态和隔离输出。" trailing="程序" />
        <Arrow />
        <FlowStep title="Evidence Gate" caption="充分则汇总；可补查则最多恢复一次；语义不确定则向用户澄清。" trailing="闸门" />
      </Grid>
      <Callout tone="info" title="只有一个最终答案写入者">
        决策能力只输出结构化建议与证据引用；最终汇总节点独占最终回答。图表、结论和动作建议都必须引用 evidence_id，禁止从宽共享状态里“顺手取值”。
      </Callout>

      <Stack gap={8}>
        <H2>二、业务方案：从“能问数据库”升级为运营决策包</H2>
        <Text tone="secondary">
          10 万级数据不是平台规模问题，而是业务口径、证据覆盖和建议可执行性问题。推荐把能力组织成四个可验收的数据产品，而不是继续增加 Agent 名称。
        </Text>
        <Table
          headers={["数据产品", "用户问题", "标准产物", "失败边界"]}
          rows={[
            ["经营体检", "销售、订单、客单价、支付结构如何变化？", "指标快照 + 同环比 + 维度贡献 + 异常点", "时间或指标口径不明时先澄清"],
            ["履约诊断", "哪些州、卖家或品类拖累时效与评分？", "分层对比 + 关键驱动 + 代表性评论证据", "评论未按同一切片过滤时不得并入结论"],
            ["趋势预测", "未来 6 周 GMV 区间是多少？", "周序列 + rolling backtest + WAPE/MAPE + 随步长扩大的区间", "数据在 2018 年截断，必须显式披露"],
            ["行动模拟", "下架高风险卖家后指标如何变化？", "基线 + 干预规则 + 重算结果 + 副作用", "缺因果弹性时只做可重算干预，不伪造因果效果"],
          ]}
          rowTone={["info", "warning", "info", "success"]}
          striped
        />
      </Stack>

      <Grid columns={3} gap={16}>
        <Card>
          <CardHeader trailing="保留">已有正确边界</CardHeader>
          <CardBody>
            <Stack gap={6}>
              <Text size="small">MySQL + 只读账号隔离</Text>
              <Text size="small">确定性的 Text-to-SQL 多阶段管线</Text>
              <Text size="small">协调器统一管理专业能力</Text>
              <Text size="small">32 题 execution accuracy 金标</Text>
              <Text size="small">应用层会话列表、标题与摘要</Text>
            </Stack>
          </CardBody>
        </Card>
        <Card>
          <CardHeader trailing="移除">当前重复或越界设计</CardHeader>
          <CardBody>
            <Stack gap={6}>
              <Text size="small">每完成一步再让模型选下一跳</Text>
              <Text size="small">所有能力共享宽状态</Text>
              <Text size="small">预测依附于可视化节点</Text>
              <Text size="small">决策能力提前写最终回答</Text>
              <Text size="small">线程 + 队列模拟图流式事件</Text>
            </Stack>
          </CardBody>
        </Card>
        <Card>
          <CardHeader trailing="新增">可验证的控制面</CardHeader>
          <CardBody>
            <Stack gap={6}>
              <Text size="small">结构化计划与依赖图编译</Text>
              <Text size="small">Evidence / Quality Gate</Text>
              <Text size="small">checkpoint + 原生 streaming</Text>
              <Text size="small">指标语义层与物理汇总表</Text>
              <Text size="small">AST 护栏、超时、取消与成本闸门</Text>
            </Stack>
          </CardBody>
        </Card>
      </Grid>

      <Stack gap={8}>
        <H2>三、技术实现：最小但完整的契约</H2>
        <Grid columns={2} gap={16}>
          <Card>
            <CardHeader trailing="控制">ExecutionPlan</CardHeader>
            <CardBody>
              <Text size="small">
                plan_id、resolved_intent、metrics、dimensions、filters、tasks[]、depends_on、capability、input_refs、output_contract、timeout_ms、failure_policy、clarification_question。
              </Text>
            </CardBody>
          </Card>
          <Card>
            <CardHeader trailing="数据">EvidenceEnvelope</CardHeader>
            <CardBody>
              <Text size="small">
                evidence_id、question_id、metric_id、grain、filters、source、sql_hash、row_count、snapshot/version、status、warnings、artifact_ref。
              </Text>
            </CardBody>
          </Card>
        </Grid>
        <Table
          headers={["层", "建议实现", "关键边界"]}
          rows={[
            ["协调器", "StateGraph 负责编译 DAG；动态独立任务用 Send；多出边同一 super-step 并行", "模型不做确定步骤的逐跳调度；每个节点幂等"],
            ["专业能力", "SQL、NLP、预测、可视化、决策拆为窄输入/输出子图", "子图不彼此自由调用；都通过证据契约交接"],
            ["记忆", "checkpointer 保存线程内运行状态；store/应用层保存跨轮业务槽位与摘要", "checkpoint 不是会话产品模型；大对象只传 artifact_ref"],
            ["流式", "直接使用 stream/astream 的 updates、custom、messages 事件", "事件需含 run_id、task_id、sequence、status、evidence_id；支持取消与背压"],
            ["恢复", "节点级重试 + 幂等键；证据不足最多一次恢复计划；歧义用 interrupt", "禁止无限 evaluator-optimizer 循环"],
          ]}
          rowTone={["info", "info", "success", "success", "warning"]}
          striped
        />
      </Stack>

      <Callout tone="danger" title="SQL 护栏是当前真实高风险项">
        现有正则校验会接受 SLEEP、LOAD_FILE、INTO DUMPFILE、BENCHMARK 和 information_schema 查询。只读账号应继续保留，但还需要 AST 解析、表/视图 allowlist、函数 denylist、禁止 INTO/锁/系统模式、数据库执行超时、取消传播；高风险长尾查询可先做 EXPLAIN FORMAT=JSON 成本预检。
      </Callout>

      <Stack gap={8}>
        <H2>四、数据层：保留 MySQL，重做语义与加速边界</H2>
        <Grid columns="1fr 1.6fr" gap={20} align="center">
          <Stack gap={10}>
            <Row gap={24} wrap>
              <Stat value="99,441" label="订单" />
              <Stat value="112,650" label="订单明细" />
              <Stat value="1,000,163" label="地理明细" tone="info" />
            </Row>
            <Text size="small" tone="secondary">
              全部 CSV 约 120 MB。正确对外口径是“约 10 万订单、11.3 万订单明细、9 张业务表；地理明细约 100 万行”。这个量级不需要 Spark、湖仓或 ClickHouse。
            </Text>
            <Callout tone="warning" title="mv_* 不是物化视图">
              当前 6 个 mv_* 对象都是 MySQL 普通 VIEW。它们能统一口径，但不能宣称形成物理预聚合加速层。
            </Callout>
          </Stack>
          <Stack gap={6}>
            <H3>仓库实测：规范 JOIN、相关子查询、普通 VIEW</H3>
            <BarChart
              categories={VIEW_BENCHMARKS}
              series={[
                { name: "规范 JOIN", data: [801, 1050, 895, 387, 3836, 653], tone: "info" },
                { name: "相关子查询", data: [1442, 1166, 3663, 399, 5718, 1108], tone: "danger" },
                { name: "普通 VIEW", data: [792, 1023, 974, 394, 4014, 605], tone: "neutral" },
              ]}
              valueSuffix=" ms"
              height={280}
              showValues={false}
            />
            <Text size="small" tone="tertiary">
              普通 VIEW 与等价 JOIN 基本同量级；显著收益来自避免低效相关子查询，而非 VIEW 自身物化。
            </Text>
          </Stack>
        </Grid>
        <Text>
          推荐将 GMV、订单、客单价、准时率、评分、支付结构等定义为“指标即代码”：声明粒度、可用维度、过滤规则、连接图、单位、时间口径与可加和性。高频指标编译成参数化 SQL 并命中物理汇总表；Text-to-SQL 只处理语义层覆盖不到的长尾问题。
        </Text>
      </Stack>
    </Stack>
  );
}

function RoadmapView() {
  return (
    <Stack gap={24}>
      <Stack gap={8}>
        <H2>迁移路线：先纠正正确性，再重构运行时</H2>
        <Text tone="secondary">
          “允许颠覆”不等于一次性重写。每一阶段都保留可运行基线，并用同一组问题验证收益。
        </Text>
      </Stack>

      <Table
        headers={["优先级", "改造包", "具体动作", "验收出口"]}
        rows={[
          ["P0", "恢复基线", "修复协调器语法回归；冻结 32 题、复合问、多轮问与安全对抗集", "测试重新全绿；现状指标可复现"],
          ["P0", "计划与并行", "ExecutionPlan 替代逐跳路由；独立 SQL 子问题并行；只保留一次有限恢复", "复合问轨迹确定；模型路由调用显著减少；p95 延迟相对下降"],
          ["P0", "证据与语义", "指标即代码；Evidence Gate；NLP 接收州/品类/时间过滤；最终回答单写入者", "每条 claim/chart/action 可追溯；跨能力过滤一致"],
          ["P0", "查询安全", "AST + allowlist/denylist + 超时/取消 + EXPLAIN 成本闸门", "危险 SQL 集全部拒绝或在预算内终止"],
          ["P1", "持久化与流式", "checkpointer + thread_id；原生 stream/astream；应用会话与图状态分层", "中断可恢复；刷新仍可读；事件有序且可取消"],
          ["P1", "专业子图", "SQL、NLP、预测、可视化、决策使用窄状态独立测试", "节点/边/partial execution 均有契约测试"],
          ["P1", "真实加速层", "热点指标物理汇总；保留 VIEW 作稳定接口；用 EXPLAIN ANALYZE 决定索引", "基准证明收益；不再把普通 VIEW 当物化"],
          ["P1", "分析能力归位", "预测独立；周序列 + rolling backtest；What-if 区分重算与因果", "预测报告误差与区间；无法量化的干预明确拒绝"],
          ["P2", "评测闭环", "生产失败 trace 入数据集；离线实验 + 线上 evaluator + 回归门禁", "每次变更可回答“正确率、忠实度、延迟哪里变了”"],
        ]}
        rowTone={["danger", "danger", "danger", "danger", "warning", "warning", "warning", "warning", "info"]}
        striped
      />

      <Grid columns={3} gap={16}>
        <Card>
          <CardHeader trailing="Agent/编排">需要大改</CardHeader>
          <CardBody>
            <Text size="small">
              推翻逐跳模型路由和宽共享状态；引入计划编译、并行 worker、证据闸门、有限恢复与唯一最终答案写入者。
            </Text>
          </CardBody>
        </Card>
        <Card>
          <CardHeader trailing="Dashboard">接口改，布局不必推翻</CardHeader>
          <CardBody>
            <Text size="small">
              展示任务 DAG、证据状态、澄清与降级；事件源切换到图原生流。现有聊天、会话列表、trace 和图表布局可以沿用。
            </Text>
          </CardBody>
        </Card>
        <Card>
          <CardHeader trailing="数据库">保留 MySQL</CardHeader>
          <CardBody>
            <Text size="small">
              新增语义层、物理汇总和查询预算；10 万订单无需大数据栈。地理表按邮编前缀预聚合即可消除最明显冗余。
            </Text>
          </CardBody>
        </Card>
      </Grid>

      <Stack gap={8}>
        <H2>明确不做</H2>
        <Grid columns={2} gap={16}>
          <Callout tone="neutral" title="不做全面开放 ReAct">
            路径可预知的分析工作流没有必要付出不可复现、长尾循环和安全面扩大的代价。开放循环只放在受限局部。
          </Callout>
          <Callout tone="neutral" title="不靠增加 Agent 数量制造复杂度">
            先把四个专业能力的输入、输出、证据与停止条件做实，再谈新增异常扫描等离线能力。
          </Callout>
          <Callout tone="neutral" title="不上 Spark、湖仓、向量库解决关系聚合">
            120 MB 的数据和百万级最大表仍是单机 MySQL 的舒适区；这里的瓶颈是口径与查询形态。
          </Callout>
          <Callout tone="neutral" title="不用 LSTM 包装百点序列">
            周序列仅约百个点。ETS/ARIMA + rolling backtest 更可解释，也更容易诚实报告误差。
          </Callout>
          <Callout tone="neutral" title="不让决策层绕过证据直接查库">
            决策消费上游证据；需要补查时回到计划层产生可审计任务，而不是形成第二套隐式查询链路。
          </Callout>
          <Callout tone="neutral" title="不分析数据集中不存在的退货率">
            Olist 公开数据没有退货表。只能回答取消率、低分占比等有字段支持的问题，或明确标注不可回答。
          </Callout>
        </Grid>
      </Stack>
    </Stack>
  );
}

function ValidationView() {
  return (
    <Stack gap={24}>
      <Stack gap={8}>
        <H2>验证：用正确率、忠实度、延迟和恢复能力证明重构</H2>
        <Text tone="secondary">
          下面的仓库历史结果是基线，不是承诺。新架构必须在冻结数据集上做配对对比，不能用个别演示问题替代评测。
        </Text>
      </Stack>

      <Grid columns="1.4fr 1fr" gap={20} align="center">
        <Stack gap={6}>
          <H3>现有 32 题 Text-to-SQL execution accuracy</H3>
          <BarChart
            categories={["单次最好", "Qwen 三次均值", "Qwen 始终通过", "DeepSeek 三次均值"]}
            series={[{ name: "通过率", data: [87.5, 80.21, 71.88, 75.0], tone: "info" }]}
            valueSuffix="%"
            height={260}
            showValues
            yMax={100}
          />
          <Text size="small" tone="tertiary">
            Qwen 三次范围 78.12%–84.38%；三次始终通过 23/32。首要问题是复杂题稳定性，而非缺少更多 Agent。
          </Text>
        </Stack>
        <Callout tone="warning" title="当前工作区基线先修复">
          协调器图文件存在缩进错误。本地测试结果为 227 passed、3 failed、2 deselected，3 个失败都由该语法回归触发；另有 1 处尾随空白。本评审未修改这些用户现有改动。
        </Callout>
      </Grid>

      <Table
        headers={["评测面", "指标", "建议门槛或比较方式", "对应风险"]}
        rows={[
          ["语义计划", "指标/维度/过滤/依赖完全匹配率", "在新增复合问与歧义问集上人工金标；按字段报告，不只给总分", "理解错但 SQL 可执行"],
          ["查数", "EX/denotation、三次稳定通过率", "至少不低于当前单次最好 87.5%；重点提升 71.88% 稳定通过基线", "偶发成功不能上线"],
          ["证据", "claim precision、证据覆盖率、过滤一致率", "每条可核事实必须引用 evidence_id；跨 SQL/NLP/图表过滤完全一致", "结论看似合理但与数据错位"],
          ["多轮", "槽位继承、澄清、拒答正确率", "时间/州/品类/指标分别建对抗集；歧义不允许静默猜测", "错误上下文被带入后续轮次"],
          ["性能", "p50/p95 总延迟、LLM 调用数、并行效率", "与当前串行基线做同题配对；单独报告 SQL 和 LLM 时间", "只优化模型调用却掩盖慢查询"],
          ["韧性", "超时、取消、节点重试、断点恢复", "故障注入验证同一任务不产生重复副作用或重复事件", "恢复后状态污染或重复写入"],
          ["安全", "危险 SQL、提示注入、越权表访问", "拒绝 SLEEP/LOAD_FILE/INTO/BENCHMARK/系统模式；执行预算内强制终止", "只读权限仍可能泄露或耗尽资源"],
        ]}
        rowTone={["info", "info", "success", "warning", "info", "warning", "danger"]}
        striped
      />

      <Stack gap={8}>
        <H2>官方推荐 vs 本仓库选型</H2>
        <Table
          headers={["议题", "官方/行业建议", "本仓库应采用", "理由"]}
          rows={[
            ["Workflow / Agent", "明确路径用 workflow；动态未知子任务再用 orchestrator-worker", "保留确定性主图，ExecutionPlan 编译动态 worker；不改成超级 ReAct", "电商分析步骤和证据依赖可定义，长尾只在局部存在"],
            ["并行", "独立任务可并行；LangGraph 可用多出边或 Send", "SQL 子问题、条件已确定的评论切片并行", "当前串行是复合问延迟的结构性来源"],
            ["持久化", "checkpointer 提供线程状态、恢复和 time travel；store 管长期记忆", "图内 checkpoint + 应用会话元数据/业务摘要分层", "会话列表与节点恢复是两个不同问题"],
            ["流式", "直接使用 stream/astream 的 updates、custom、messages", "替换手写后台线程与队列，但保留前端事件投影", "减少两套运行状态与竞态"],
            ["Text-to-SQL", "最小权限、执行前应用校验、必要时人工审核", "继续确定性查数管线；升级 AST/预算/成本闸门；高风险才人工审核", "没有必要为了示例改成 create_agent"],
            ["语义层", "集中定义指标、连接与权限；缩小领域上下文", "轻量指标即代码 + 销售/履约/品类/评论上下文切片", "仅 9 张表，不需要重型 domain router，但需要统一口径"],
          ]}
          rowTone={["success", "success", "info", "info", "warning", "success"]}
          striped
        />
      </Stack>

      <Stack gap={6}>
        <H2>来源与可核对证据</H2>
        <CollapsibleSection title="LangGraph 官方：工作流、并行与 orchestrator-worker" defaultOpen>
          <Link href="https://docs.langchain.com/oss/python/langgraph/workflows-agents">
            Workflows and agents
          </Link>
        </CollapsibleSection>
        <CollapsibleSection title="LangGraph 官方：Graph API、持久化、流式、子图与测试">
          <Stack gap={6}>
            <Link href="https://docs.langchain.com/oss/python/langgraph/graph-api">Graph API</Link>
            <Link href="https://docs.langchain.com/oss/python/langgraph/persistence">Persistence</Link>
            <Link href="https://docs.langchain.com/oss/python/langgraph/streaming">Streaming</Link>
            <Link href="https://docs.langchain.com/oss/python/langgraph/use-subgraphs">Subgraphs</Link>
            <Link href="https://docs.langchain.com/oss/python/langgraph/test">Testing</Link>
          </Stack>
        </CollapsibleSection>
        <CollapsibleSection title="SQL Agent、安全与评测闭环">
          <Stack gap={6}>
            <Link href="https://docs.langchain.com/oss/python/langgraph/sql-agent">LangGraph SQL Agent</Link>
            <Link href="https://docs.langchain.com/langsmith/evaluation">LangSmith evaluation</Link>
            <Link href="https://dev.mysql.com/doc/refman/8.4/en/explain.html">MySQL EXPLAIN</Link>
            <Link href="https://dev.mysql.com/doc/refman/8.4/en/view-algorithms.html">MySQL VIEW algorithms</Link>
          </Stack>
        </CollapsibleSection>
        <CollapsibleSection title="行业架构：有效 Agent、企业 NL2SQL 与语义层">
          <Stack gap={6}>
            <Link href="https://www.anthropic.com/engineering/building-effective-agents">Anthropic — Building effective agents</Link>
            <Link href="https://aws.amazon.com/blogs/machine-learning/enterprise-grade-natural-language-to-sql-generation-using-llms-balancing-accuracy-latency-and-scale/">AWS/Cisco — Enterprise-grade NL2SQL</Link>
            <Link href="https://docs.getdbt.com/docs/use-dbt-semantic-layer/dbt-sl">dbt Semantic Layer</Link>
          </Stack>
        </CollapsibleSection>
      </Stack>
    </Stack>
  );
}

export default function AgenticBiAgentOrchestrationRedesign() {
  const [view, setView] = useState<ViewMode>("架构");

  return (
    <Stack gap={28}>
      <Stack gap={10}>
        <H1>Agentic BI：从逐跳多 Agent 总线到证据驱动任务图</H1>
        <Text tone="secondary">
          结论：保留专业能力与 MySQL，推翻串行逐跳路由。大模型一次生成业务语义计划，程序编译依赖并行执行，证据闸门决定补查、澄清、降级或汇总。
        </Text>
        <Row gap={8} wrap>
          {(["架构", "路线图", "验证"] as ViewMode[]).map((item) => (
            <Pill key={item} active={view === item} onClick={() => setView(item)}>
              {item}
            </Pill>
          ))}
        </Row>
      </Stack>

      <Grid columns={4} gap={16}>
        <Stat value="1 次" label="计划阶段模型路由" tone="success" />
        <Stat value="并行" label="独立 SQL / NLP 任务" tone="info" />
        <Stat value="100%" label="可核事实必须引用证据（目标）" tone="success" />
        <Stat value="0" label="无界 Agent 循环" tone="warning" />
      </Grid>

      <Callout tone="warning" title="最重要的判断">
        “不考虑成本”允许使用更好的模型和更完整的评测，但不能成为增加自治层级的理由。当前最昂贵的问题不是 token，而是错误口径、跨能力过滤不一致、不可恢复的串行轨迹和无法证明的建议。
      </Callout>

      <Divider />

      {view === "架构" ? <ArchitectureView /> : null}
      {view === "路线图" ? <RoadmapView /> : null}
      {view === "验证" ? <ValidationView /> : null}

      <Divider />
      <Text size="small" tone="tertiary">
        评审日期：2026-10-13。仓库证据来自协调器、SQL/NLP/Decision/Session 实现、数据 CSV 计数、预聚合基准和 32 题评测记录。所有目标值均标注为建议门槛，未当作已实现结果。
      </Text>
    </Stack>
  );
}
