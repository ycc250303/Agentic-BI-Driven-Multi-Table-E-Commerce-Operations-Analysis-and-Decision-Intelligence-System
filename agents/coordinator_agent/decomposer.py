from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from agents.coordinator_agent.planner import IntentName, classify_intent


class DecomposeResult(BaseModel):
    intent: IntentName = "descriptive"
    sub_questions: list[str] = Field(default_factory=list)
    suggested_agents: list[str] = Field(default_factory=list)
    reasoning: str = ""
    off_topic: bool = False

    @field_validator("sub_questions")
    @classmethod
    def _strip_questions(cls, items: list[str]) -> list[str]:
        return [str(q).strip() for q in items if str(q).strip()]

    @model_validator(mode="after")
    def _require_questions_unless_off_topic(self) -> DecomposeResult:
        if not self.off_topic and not self.sub_questions:
            raise ValueError("sub_questions 不能为空（off_topic=false 时）")
        return self


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _load_prompt(name: str) -> str:
    return (_project_root() / "config" / "coordinator_agent" / name).read_text(
        encoding="utf-8"
    )


def _extract_json_object(text: str) -> str:
    s = text.strip()
    if s.startswith("```"):
        s = re.sub(r"^```(?:json)?\s*", "", s, flags=re.IGNORECASE)
        s = re.sub(r"\s*```$", "", s)
    return s.strip()


def _split_jiqi_query(user_query: str) -> list[str] | None:
    """「A 及其 B」拆成两条可查数子问题（规则兜底，配合 decompose_query.md）。"""
    text = user_query.strip()
    if "及其" not in text:
        return None
    left, right = text.split("及其", 1)
    left = left.strip().rstrip("，,")
    right = right.strip().rstrip("，,")
    if not left or not right:
        return None
    if not right.endswith(("？", "?")):
        right = right + "？"
    if not left.endswith(("？", "?")):
        if "是什么" in right or "哪些" in right:
            left = left + "是什么？"
        elif "怎样" in right or "如何" in right:
            left = left + "怎样？"
        else:
            left = left + "？"
    return [left, right]


def _split_compound_query(user_query: str) -> list[str]:
    """规则拆分：按问号、分号及常见并列连词切分。"""
    text = user_query.strip()
    if not text:
        return []

    parts = re.split(r"[？?；;]+", text)
    chunks: list[str] = []
    for part in parts:
        p = part.strip().strip("，,")
        if not p:
            continue
        sub = re.split(r"(?:，|,|\s+以及\s+|\s+并且\s+|\s+同时\s+)", p)
        for s in sub:
            s = s.strip().strip("，,")
            if not s:
                continue
            if not s.endswith(("？", "?")):
                s = s + "？"
            chunks.append(s)

    if not chunks:
        q = text if text.endswith(("？", "?")) else text + "？"
        return [q]

    seen: set[str] = set()
    unique: list[str] = []
    for c in chunks:
        if c not in seen:
            seen.add(c)
            unique.append(c)
    return unique


_GMV_PREDICTIVE_HINTS = ("销售额", "gmv", "销售", "营收", "营业额")
_FORECAST_QUERY_HINTS = ("预测", "未来", "6周", "六周", "外推")


def _is_gmv_sales_predictive(user_query: str, intent: IntentName) -> bool:
    if intent != "predictive":
        return False
    q = user_query.lower()
    has_fc = any(h in user_query or h in q for h in _FORECAST_QUERY_HINTS)
    has_gmv = any(h in user_query or h in q for h in _GMV_PREDICTIVE_HINTS)
    return has_fc and has_gmv


def normalize_predictive_sub_questions(
    user_query: str,
    intent: IntentName,
    sub_questions: list[str],
) -> list[str]:
    """销售额预测不由 SQL 直接产出未来值；统一改为查历史月度趋势供模型外推。"""
    if not _is_gmv_sales_predictive(user_query, intent):
        return sub_questions
    return [
        "查询 mv_monthly_sales 历史月度 GMV 与订单量（2016-09 至 2018-10），"
        "用于未来 6 周销售额预测与趋势解读"
    ]


def finalize_suggested_agents(result: DecomposeResult, user_query: str) -> DecomposeResult:
    """分解结果与规则对齐：该调度上的 Agent 必须写进 suggested_agents。"""
    from agents.nlp_agent.run import should_run_nlp
    from agents.viz_agent.viz_planner import query_suggests_visualization

    agents = list(result.suggested_agents)
    if "data_analysis" not in agents:
        agents.insert(0, "data_analysis")
    if should_run_nlp(user_query, result.intent) and "nlp" not in agents:
        insert_at = agents.index("data_analysis") + 1 if "data_analysis" in agents else 0
        agents.insert(insert_at, "nlp")
    if (
        query_suggests_visualization(user_query, result.intent)
        and "visualization" not in agents
    ):
        agents.append("visualization")
    if (
        result.intent in ("prescriptive", "what_if", "diagnostic", "predictive")
        and "decision" not in agents
    ):
        agents.append("decision")
    sub_questions = normalize_predictive_sub_questions(
        user_query, result.intent, list(result.sub_questions)
    )
    updates: dict[str, object] = {}
    if agents != result.suggested_agents:
        updates["suggested_agents"] = agents
    if sub_questions != result.sub_questions:
        updates["sub_questions"] = sub_questions
    if not updates:
        return result
    return result.model_copy(update=updates)


def _default_suggested_agents(intent: IntentName, user_query: str) -> list[str]:
    from agents.nlp_agent.run import should_run_nlp
    from agents.viz_agent.viz_planner import query_suggests_visualization

    agents = ["data_analysis"]
    if query_suggests_visualization(user_query, intent):
        agents.append("visualization")
    if should_run_nlp(user_query, intent):
        agents.append("nlp")
    if intent in ("prescriptive", "what_if", "diagnostic", "predictive"):
        agents.append("decision")
    return agents


def decompose_query_rule(user_query: str) -> DecomposeResult:
    intent = classify_intent(user_query)
    sub_questions = _split_compound_query(user_query)
    if len(sub_questions) == 1:
        jiqi = _split_jiqi_query(sub_questions[0])
        if jiqi:
            sub_questions = jiqi
    if len(sub_questions) == 1 and sub_questions[0].rstrip("？?") == user_query.rstrip("？?"):
        sub_questions = [user_query if user_query.endswith(("？", "?")) else user_query + "？"]
    suggested = _default_suggested_agents(intent, user_query)
    reasoning = (
        f"规则拆分：intent={intent}，共 {len(sub_questions)} 个单问题，"
        f"建议 Agent：{', '.join(suggested)}。"
    )
    return finalize_suggested_agents(
        DecomposeResult(
            intent=intent,
            sub_questions=sub_questions,
            suggested_agents=suggested,
            reasoning=reasoning,
        ),
        user_query,
    )


def decompose_query_llm(user_query: str, *, model=None) -> DecomposeResult:
    from langchain_core.messages import HumanMessage, SystemMessage

    from agents.decision_agent.llm import get_llm

    llm = model or get_llm()
    system = _load_prompt("decompose_query.md")
    human = f"【用户问题】\n{user_query}\n\n请输出 JSON。"
    try:
        resp = llm.invoke([SystemMessage(content=system), HumanMessage(content=human)])
        raw = _extract_json_object(str(resp.content))
        result = DecomposeResult.model_validate_json(raw)
        result = finalize_suggested_agents(result, user_query)
        if len(result.sub_questions) == 1:
            only = result.sub_questions[0]
            if only.rstrip("？?") == user_query.rstrip("？?"):
                return result
        return result
    except Exception:
        return decompose_query_rule(user_query)


def decompose_query(user_query: str, *, use_llm: bool = True, model=None) -> DecomposeResult:
    if use_llm:
        return decompose_query_llm(user_query, model=model)
    return decompose_query_rule(user_query)


def decompose_to_state_patch(user_query: str, result: DecomposeResult) -> dict:
    if result.off_topic:
        from agents.coordinator_agent.guardrails import off_topic_state_patch

        return off_topic_state_patch(user_query)
    task_plan = [f"子问题 {i + 1}：{q}" for i, q in enumerate(result.sub_questions)]
    task_plan.append(f"建议调度：{' → '.join(result.suggested_agents)} → 汇总回答")
    return {
        "user_query": user_query,
        "question": user_query,
        "intent": result.intent,
        "sub_questions": result.sub_questions,
        "suggested_agents": result.suggested_agents,
        "plan_reasoning": result.reasoning,
        "task_plan": task_plan,
        "sql_runs": [],
        "agents_done": {},
        "execution_log": [],
        "orchestrator_iterations": 0,
    }


def dump_decompose_json(result: DecomposeResult) -> str:
    return json.dumps(result.model_dump(), ensure_ascii=False, indent=2)
