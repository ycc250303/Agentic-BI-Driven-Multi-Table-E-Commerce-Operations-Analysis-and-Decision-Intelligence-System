"""
对 rewrite_to_query_tool 的结构化输出做语义一致性校验（不访问数据库）。
规则由 config/data_analysis_agent/rewrite_plan_rules.yaml 驱动。
"""

from __future__ import annotations

import sys
from functools import lru_cache
from pathlib import Path
from typing import Any

_sql_agent_dir = Path(__file__).resolve().parents[1]
if str(_sql_agent_dir) not in sys.path:
    sys.path.insert(0, str(_sql_agent_dir))

import yaml
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from tools.rewrite_to_query import RewriteToQueryOutput


class ValidateRewritePlanOutput(BaseModel):
    plan_ok: bool = Field(description="rewrite 结构化计划是否通过语义校验")
    brief: str = Field(description="通过/失败原因简述")


def _project_root() -> Path:
    current = Path(__file__).resolve()
    for parent in current.parents:
        if (parent / "config" / "data_analysis_agent").exists():
            return parent
    raise RuntimeError("未找到项目根目录下的 config/data_analysis_agent 目录。")


@lru_cache(maxsize=1)
def _load_rules() -> dict[str, Any]:
    rules_path = (
        _project_root() / "config" / "data_analysis_agent" / "rewrite_plan_rules.yaml"
    )
    raw = yaml.safe_load(rules_path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        return {"rules": []}
    rules = raw.get("rules") or []
    if not isinstance(rules, list):
        rules = []
    return {"rules": rules}


def _contains_all(text: str, phrases: list[str]) -> bool:
    compact = text.replace(" ", "").lower()
    return all((p or "").replace(" ", "").lower() in compact for p in phrases)


def _rule_applies(rule: dict[str, Any], user_query: str, payload: RewriteToQueryOutput) -> bool:
    when = rule.get("when") or {}
    phrases = when.get("user_query_contains_all") or []
    min_sub_questions = int(when.get("min_sub_questions") or 0)
    if phrases and not _contains_all(user_query, [str(p) for p in phrases]):
        return False
    if len(payload.sub_questions) < min_sub_questions:
        return False
    return True


def _assert_inherit_or_filter(
    payload: RewriteToQueryOutput,
    source_index: int,
    target_indices: list[int],
    allowed_filter_keywords: list[str],
) -> bool:
    if source_index >= len(payload.sub_questions):
        return False
    source_id = payload.sub_questions[source_index].id
    for idx in target_indices:
        if idx >= len(payload.sub_questions):
            return False
        sq = payload.sub_questions[idx]
        if sq.scope.kind == "inherit_previous" and sq.scope.inherit_from == source_id:
            continue
        if sq.scope.kind == "explicit_filter":
            ef = sq.scope.explicit_filter or ""
            if any(k in ef for k in allowed_filter_keywords):
                continue
        return False
    return True


def _assert_metric_key_any_of(payload: RewriteToQueryOutput, any_of: list[str]) -> bool:
    metric_keys = {sq.metric_key for sq in payload.sub_questions}
    return bool(metric_keys & set(any_of))


def _assert_query_for_sql_not_contains_any(
    payload: RewriteToQueryOutput, phrases: list[str]
) -> bool:
    q = (payload.query_for_sql or "").replace(" ", "").lower()
    for p in phrases:
        if (p or "").replace(" ", "").lower() in q:
            return False
    return True


def _evaluate_assertion(assertion: dict[str, Any], payload: RewriteToQueryOutput) -> bool:
    assertion_type = str(assertion.get("type") or "").strip()
    if assertion_type == "inherit_or_filter":
        return _assert_inherit_or_filter(
            payload=payload,
            source_index=int(assertion.get("source_index") or 0),
            target_indices=[int(x) for x in (assertion.get("target_indices") or [])],
            allowed_filter_keywords=[
                str(x) for x in (assertion.get("allowed_filter_keywords") or [])
            ],
        )
    if assertion_type == "metric_key_any_of":
        return _assert_metric_key_any_of(
            payload=payload,
            any_of=[str(x) for x in (assertion.get("any_of") or [])],
        )
    if assertion_type == "query_for_sql_not_contains_any":
        return _assert_query_for_sql_not_contains_any(
            payload=payload,
            phrases=[str(x) for x in (assertion.get("phrases") or [])],
        )
    return True


def _validate_with_rules(user_query: str, payload: RewriteToQueryOutput) -> tuple[bool, str]:
    for rule in _load_rules().get("rules", []):
        if not isinstance(rule, dict):
            continue
        if not _rule_applies(rule, user_query, payload):
            continue
        assertions = rule.get("assertions") or []
        for assertion in assertions:
            if not isinstance(assertion, dict):
                continue
            if _evaluate_assertion(assertion, payload):
                continue
            message = str(rule.get("message") or "rewrite 语义规则校验未通过")
            rule_id = str(rule.get("id") or "unknown_rule")
            return False, f"[{rule_id}] {message}"
    return True, ""


def validate_rewrite_plan(
    user_query: str,
    rewrite_json: str,
) -> ValidateRewritePlanOutput:
    try:
        payload = RewriteToQueryOutput.model_validate_json(rewrite_json.strip())
    except Exception as e:
        return ValidateRewritePlanOutput(
            plan_ok=False, brief=f"rewrite_json 非法或不符合 RewriteToQueryOutput：{e}"
        )

    if not payload.sub_questions:
        return ValidateRewritePlanOutput(plan_ok=False, brief="sub_questions 不能为空。")

    plan_ok, brief = _validate_with_rules(user_query=user_query, payload=payload)
    if not plan_ok:
        return ValidateRewritePlanOutput(plan_ok=False, brief=brief)

    return ValidateRewritePlanOutput(
        plan_ok=True,
        brief="通过：sub_questions 结构完整，规则引擎校验通过。",
    )


class ValidateRewritePlanRunner:
    def invoke(self, user_query: str, rewrite_json: str) -> str:
        out = validate_rewrite_plan(user_query=user_query, rewrite_json=rewrite_json)
        return out.model_dump_json(indent=2, ensure_ascii=False)


def build_validate_rewrite_plan_tool():
    runner = ValidateRewritePlanRunner()
    return StructuredTool.from_function(
        func=runner.invoke,
        name="validate_rewrite_plan_tool",
        description=(
            "按 rewrite_plan_rules.yaml 校验 rewrite_to_query_tool 的结构化语义计划。"
        ),
    )


if __name__ == "__main__":
    demo_query = "2017年哪个州的销售额最高？交付准时率是多少？哪种支付方式最受欢迎？"
    demo_rewrite = RewriteToQueryOutput(
        query_for_sql="示例",
        sub_questions=[
            {
                "id": "q1",
                "question_zh": "2017年哪个州销售额最高？",
                "metric_key": "state_gmv_rank",
                "dimensions": ["customer_state"],
                "time_range": "2017",
                "aggregation": "top1",
                "scope": {"kind": "platform"},
            },
            {
                "id": "q2",
                "question_zh": "该州准时率是多少？",
                "metric_key": "on_time_rate",
                "dimensions": [],
                "time_range": "2017",
                "aggregation": "overall_rate",
                "scope": {"kind": "inherit_previous", "inherit_from": "q1"},
            },
        ],
        hit_pre_agg_view=True,
        candidate_views=["mv_state_sales", "mv_delivery_perf"],
        confidence=0.9,
    ).model_dump_json(indent=2, ensure_ascii=False)
    print(
        ValidateRewritePlanRunner().invoke(
            user_query=demo_query,
            rewrite_json=demo_rewrite,
        )
    )
