# Decision-Agent Fixtures

## 本地构造样例

以下文件用于规则、证据包、What-if 和冒烟测试：

- `high_delivery_risk.json`
- `high_seller_risk.json`
- `category_risk.json`
- `forecast_slowdown.json`

## 其他分支真实上游快照

以下文件来自 `origin/agent-tpc` 分支的真实运行结果，使用 `git worktree` 在 `.worktrees/agent-tpc` 中运行后导出：

- `upstream_review_insights_from_agent_tpc.json`
- `upstream_what_if_from_agent_tpc.json`
- `upstream_state_from_agent_tpc.json`

运行命令摘要：

```powershell
git worktree add '.worktrees/agent-tpc' origin/agent-tpc

@'
import json
import sys
from pathlib import Path
root = Path('.worktrees/agent-tpc').resolve()
sys.path.insert(0, str(root))
from dotenv import load_dotenv
load_dotenv(Path('.env').resolve())
from agents.nlp_agent.run import ReviewInsightAgent
agent = ReviewInsightAgent(sample_size=300, wordcloud_top_n=30, wordcloud_sample=600)
out = agent.run(state=None)
Path('agents/decision_agent/tests/fixtures/upstream_review_insights_from_agent_tpc.json').write_text(
    json.dumps(out, ensure_ascii=False, indent=2),
    encoding='utf-8',
)
'@ | .venv\Scripts\python.exe -
```

说明：

- `upstream_review_insights_from_agent_tpc.json` 中的 `sentiment` 和 `topics_bertopic` 当前为降级结果，因为本地数据库没有 `review_sentiment` 与 `review_topic_meta` 表。
- `upstream_what_if_from_agent_tpc.json` 来自旧分支固定 SQL 查询，会访问 MySQL 原始业务表；当前 Decision-Agent 只为兼容旧 state 消费其输出快照，新的 What-if 主路径使用通用 `WhatIfPlan`。
- `upstream_state_from_agent_tpc.json` 是将上述真实快照与当前标准 `analysis_result` / `forecast_result` 组合后的联调 state。
