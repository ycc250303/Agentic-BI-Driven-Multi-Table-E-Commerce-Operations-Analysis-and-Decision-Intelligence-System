from __future__ import annotations

from ..schemas import ActionPlanItem, ScoredProblem


def generate_action_plan(problems: list[ScoredProblem]) -> list[ActionPlanItem]:
    plan: list[ActionPlanItem] = []
    for index, problem in enumerate(problems[:3], start=1):
        priority = f"P{index}"
        if problem.problem_type == "delivery":
            plan.append(
                ActionPlanItem(
                    priority=priority,
                    action="对高延迟区域启动专项履约改善计划，并按州拆解仓配与卖家发货问题。",
                    owner="物流",
                    reason="配送时效和相关负面评论同时超阈值，已影响客户体验。",
                    target_kpi="on_time_rate",
                    target_value="4 周内提升至 82% 以上",
                    time_horizon="2-4 weeks",
                    expected_impact="降低延迟投诉，提升准时交付率与区域口碑。",
                )
            )
        elif problem.problem_type == "seller":
            plan.append(
                ActionPlanItem(
                    priority=priority,
                    action="建立高风险卖家整改与流量降权机制，并设置发货与售后 SLA。",
                    owner="商家管理",
                    reason="少数低评分卖家正在拉低整体评分，且 What-if 显示治理收益明显。",
                    target_kpi="avg_review_score",
                    target_value="6 周内将重点卖家评分提升到 3.8 以上",
                    time_horizon="4-6 weeks",
                    expected_impact="改善平台评分，减少高投诉卖家对整体体验的拖累。",
                )
            )
        elif problem.problem_type == "category":
            plan.append(
                ActionPlanItem(
                    priority=priority,
                    action="对问题品类开展 SKU 质检、差评商品下架审核与详情页说明优化。",
                    owner="品类运营",
                    reason="品类销量下滑与质量负面反馈同时出现，说明供给质量存在问题。",
                    target_kpi="negative_review_rate",
                    target_value="1 个周期内下降 5 个百分点",
                    time_horizon="3-6 weeks",
                    expected_impact="减少质量类投诉，修复问题品类转化与复购。",
                )
            )
        elif problem.problem_type == "region":
            plan.append(
                ActionPlanItem(
                    priority=priority,
                    action="对重点区域实施专项运营治理，调整履约承诺并增加客服补偿策略。",
                    owner="平台运营",
                    reason="重点区域销售贡献较高，但口碑与负面情绪显著偏弱。",
                    target_kpi="regional_negative_rate",
                    target_value="重点区域负面率下降至 22% 以下",
                    time_horizon="3-5 weeks",
                    expected_impact="稳住高价值区域口碑，降低销售增长被体验透支的风险。",
                )
            )
        elif problem.problem_type == "forecast":
            plan.append(
                ActionPlanItem(
                    priority=priority,
                    action="围绕核心高潜区域和品类提前部署保增长计划，修复影响转化的关键体验问题。",
                    owner="平台运营",
                    reason="预测已提示未来增长放缓，需要提前干预以减少下滑风险。",
                    target_kpi="forecasted_gmv_growth",
                    target_value="未来 6 周保持正增长",
                    time_horizon="2-6 weeks",
                    expected_impact="减缓增长放缓趋势，提升经营韧性。",
                )
            )
        else:
            plan.append(
                ActionPlanItem(
                    priority=priority,
                    action="建立核心经营指标周度监控和异常复盘机制。",
                    owner="平台运营",
                    reason="当前没有单一高风险问题，但仍需持续追踪经营趋势。",
                    target_kpi="weekly_monitoring_coverage",
                    target_value="覆盖核心 KPI 的 100%",
                    time_horizon="2 weeks",
                    expected_impact="提高异常发现速度，为后续专项治理提供基础。",
                )
            )
    return plan
