from __future__ import annotations

import json

from agents.sql_agent.tools.plan_sql_guard import plan_sql_consistency


def _gen(sqls: list[str]) -> str:
    return json.dumps({"query_sqls": sqls})


def _plan(subs: list[dict]) -> str:
    return json.dumps(
        {
            "query_for_sql": "q",
            "sub_questions": subs,
            "hit_pre_agg_view": False,
            "candidate_views": [],
            "confidence": 0.9,
        }
    )


def test_empty_sub_questions_pass():
    ok, _ = plan_sql_consistency("not-json", _gen(["SELECT 1"]))
    assert ok is True
    ok2, _ = plan_sql_consistency(_plan([]), _gen(["SELECT 1"]))
    assert ok2 is True


def test_top10_requires_matching_limit():
    plan = _plan(
        [
            {
                "id": "q1",
                "question_zh": "差评品类 Top10",
                "metric_key": "bad_review_count",
                "aggregation": "top10",
                "scope": {"kind": "platform"},
            }
        ]
    )
    ok, brief = plan_sql_consistency(
        plan, _gen(["SELECT `product_category` FROM `products`"])
    )
    assert ok is False
    assert "LIMIT 10" in brief
    ok2, _ = plan_sql_consistency(
        plan,
        _gen(["SELECT `product_category` FROM `products` ORDER BY 1 DESC LIMIT 10"]),
    )
    assert ok2 is True


def test_inherit_requires_nested_select():
    plan = _plan(
        [
            {
                "id": "q2",
                "question_zh": "该州支付",
                "metric_key": "payment_popularity",
                "aggregation": "",
                "scope": {"kind": "inherit_previous", "inherit_from": "q1"},
            }
        ]
    )
    ok, brief = plan_sql_consistency(
        plan,
        _gen(
            [
                "SELECT `payment_type` FROM `mv_payment_dist` GROUP BY `payment_type`"
            ]
        ),
    )
    assert ok is False
    assert "继承" in brief
    ok2, _ = plan_sql_consistency(
        plan,
        _gen(
            [
                "SELECT `payment_type` FROM `payments` WHERE `order_id` IN "
                "(SELECT `order_id` FROM `orders` WHERE `customer_id` = 'x')"
            ]
        ),
    )
    assert ok2 is True


def test_platform_on_time_rejects_delivery_view_only():
    plan = _plan(
        [
            {
                "id": "q1",
                "question_zh": "平台准时率",
                "metric_key": "on_time_rate",
                "aggregation": "",
                "scope": {"kind": "platform"},
            }
        ]
    )
    ok, brief = plan_sql_consistency(
        plan,
        _gen(["SELECT AVG(`on_time_rate`) FROM `mv_delivery_perf`"]),
    )
    assert ok is False
    assert "orders" in brief
    ok2, _ = plan_sql_consistency(
        plan,
        _gen(
            [
                "SELECT SUM(1) / COUNT(*) FROM `orders` WHERE `order_status` = 'delivered'"
            ]
        ),
    )
    assert ok2 is True


def test_inherit_nested_limit_does_not_count_as_outer():
    plan = _plan(
        [
            {
                "id": "q2",
                "question_zh": "继承对象上的准时率",
                "metric_key": "on_time_rate",
                "aggregation": "",
                "scope": {"kind": "inherit_previous", "inherit_from": "q1"},
            }
        ]
    )
    ok, _ = plan_sql_consistency(
        plan,
        _gen(
            [
                "SELECT SUM(1) / COUNT(*) AS `on_time_rate` FROM `orders` `o` "
                "INNER JOIN `customers` `c` ON `o`.`customer_id` = `c`.`customer_id` "
                "WHERE `c`.`customer_state` = ("
                "SELECT `customer_state` FROM `mv_state_sales` "
                "GROUP BY `customer_state` ORDER BY SUM(`total_gmv`) DESC LIMIT 1)"
            ]
        ),
    )
    assert ok is True


def test_non_top_outer_limit_20_rejected():
    plan = _plan(
        [
            {
                "id": "q1",
                "question_zh": "各支付方式交易分布",
                "metric_key": "payment_popularity",
                "aggregation": "",
                "scope": {"kind": "platform"},
            }
        ]
    )
    ok, brief = plan_sql_consistency(
        plan,
        _gen(
            [
                "SELECT `payment_type` FROM `mv_payment_dist` "
                "GROUP BY `payment_type` ORDER BY 1 DESC LIMIT 20"
            ]
        ),
    )
    assert ok is False
    assert "LIMIT 20" in brief


def test_rate_topk_requires_having():
    plan = _plan(
        [
            {
                "id": "q1",
                "question_zh": "延迟率排名",
                "metric_key": "delay_rate",
                "aggregation": "top10",
                "scope": {"kind": "platform"},
            }
        ]
    )
    ok, brief = plan_sql_consistency(
        plan,
        _gen(
            [
                "SELECT `customer_state` FROM `orders` `o` "
                "INNER JOIN `customers` `c` ON `o`.`customer_id` = `c`.`customer_id` "
                "GROUP BY `c`.`customer_state` ORDER BY 1 DESC LIMIT 10"
            ]
        ),
    )
    assert ok is False
    assert "HAVING" in brief
    ok2, _ = plan_sql_consistency(
        plan,
        _gen(
            [
                "SELECT `customer_state` FROM `orders` `o` "
                "INNER JOIN `customers` `c` ON `o`.`customer_id` = `c`.`customer_id` "
                "GROUP BY `c`.`customer_state` HAVING COUNT(*) >= 20 "
                "ORDER BY 1 DESC LIMIT 10"
            ]
        ),
    )
    assert ok2 is True


def test_rate_without_topk_does_not_require_having():
    plan = _plan(
        [
            {
                "id": "q1",
                "question_zh": "平台准时率",
                "metric_key": "on_time_rate",
                "aggregation": "",
                "scope": {"kind": "platform"},
            }
        ]
    )
    ok, _ = plan_sql_consistency(
        plan,
        _gen(
            [
                "SELECT SUM(1) / COUNT(*) FROM `orders` WHERE `order_status` = 'delivered'"
            ]
        ),
    )
    assert ok is True


def test_non_top_limit_1_rejected():
    plan = _plan(
        [
            {
                "id": "q1",
                "question_zh": "各支付方式交易分布",
                "metric_key": "payment_popularity",
                "aggregation": "",
                "scope": {"kind": "platform"},
            }
        ]
    )
    ok, brief = plan_sql_consistency(
        plan,
        _gen(
            [
                "SELECT `payment_type` FROM `mv_payment_dist` "
                "GROUP BY `payment_type` ORDER BY 1 DESC LIMIT 1"
            ]
        ),
    )
    assert ok is False
    assert "LIMIT 1" in brief


def test_sql_count_must_match_sub_questions():
    plan = _plan(
        [
            {
                "id": "q1",
                "question_zh": "按月多指标",
                "metric_key": "gmv_total",
                "measure_keys": ["gmv_total", "total_orders", "avg_basket"],
                "aggregation": "trend",
                "scope": {"kind": "platform"},
            }
        ]
    )
    ok, brief = plan_sql_consistency(
        plan,
        _gen(
            [
                "SELECT `year_month`, SUM(`total_gmv`) AS `total_gmv` FROM `mv_monthly_sales` GROUP BY `year_month`",
                "SELECT `year_month`, SUM(`total_orders`) AS `total_orders` FROM `mv_monthly_sales` GROUP BY `year_month`",
            ]
        ),
    )
    assert ok is False
    assert "条数" in brief


def test_non_top_having_rejected():
    plan = _plan(
        [
            {
                "id": "q1",
                "question_zh": "各州准时率",
                "metric_key": "on_time_rate",
                "aggregation": "",
                "scope": {"kind": "platform"},
            }
        ]
    )
    ok, brief = plan_sql_consistency(
        plan,
        _gen(
            [
                "SELECT `c`.`customer_state`, SUM(1)/COUNT(*) AS `on_time_rate` "
                "FROM `orders` `o` INNER JOIN `customers` `c` "
                "ON `o`.`customer_id` = `c`.`customer_id` "
                "GROUP BY `c`.`customer_state` HAVING COUNT(*) >= 20"
            ]
        ),
    )
    assert ok is False
    assert "HAVING" in brief


def test_measure_keys_must_appear_in_same_sql():
    plan = _plan(
        [
            {
                "id": "q1",
                "question_zh": "按月多指标",
                "metric_key": "gmv_total",
                "measure_keys": ["gmv_total", "total_orders", "avg_basket"],
                "aggregation": "trend",
                "scope": {"kind": "platform"},
            }
        ]
    )
    ok, brief = plan_sql_consistency(
        plan,
        _gen(
            [
                "SELECT `year_month`, SUM(`total_gmv`) AS `total_gmv` "
                "FROM `mv_monthly_sales` GROUP BY `year_month`"
            ]
        ),
    )
    assert ok is False
    assert "measure_keys" in brief
    ok2, _ = plan_sql_consistency(
        plan,
        _gen(
            [
                "SELECT `year_month`, SUM(`total_gmv`) AS `total_gmv`, "
                "SUM(`total_orders`) AS `total_orders`, "
                "SUM(`total_gmv`) / NULLIF(SUM(`total_orders`), 0) AS `avg_basket` "
                "FROM `mv_monthly_sales` GROUP BY `year_month`"
            ]
        ),
    )
    assert ok2 is True


def test_freight_metric_rejects_sales_view_only():
    plan = _plan(
        [
            {
                "id": "q1",
                "question_zh": "运费占比",
                "metric_key": "freight_share",
                "aggregation": "top10",
                "scope": {"kind": "platform"},
            }
        ]
    )
    ok, brief = plan_sql_consistency(
        plan,
        _gen(
            [
                "SELECT `customer_state` FROM `mv_state_sales` "
                "GROUP BY `customer_state` ORDER BY SUM(`total_gmv`) DESC LIMIT 10"
            ]
        ),
    )
    assert ok is False
    assert "order_items" in brief
