from __future__ import annotations

from agents.viz_agent.viz_planner import (
    VizChartTask,
    _dedupe_viz_charts,
    _ensure_sql_run_chart_tasks,
    _enrich_diagnostic_review_charts,
    _infer_hint_from_columns,
    _normalize_chart_tasks,
    _strip_unrenderable_insight_charts,
    chart_task_fingerprint,
    extract_columns_from_exec_payload,
    heuristic_viz_suite,
)


def test_infer_hint_no_wordcloud_without_text_column():
    cols = ["product_category_english", "bad_review_count"]
    hint = _infer_hint_from_columns(cols, "Top 10 差评品类及其主要差评原因是什么？")
    assert hint != "wordcloud"


def test_dedupe_only_identical_global_compare_wordclouds():
    charts = [
        VizChartTask(
            title="评论中高频差评关键词(所有品类)",
            data_source="wordcloud",
            chart_type_hint="wordcloud",
        ),
        VizChartTask(
            title="好评 vs 差评 评论词云对比",
            data_source="wordcloud",
            chart_type_hint="wordcloud",
        ),
    ]
    deduped = _dedupe_viz_charts(charts)
    assert len(deduped) == 1
    assert chart_task_fingerprint(deduped[0]) == "wordcloud:compare:global"


def test_allow_compare_wordcloud_and_sql_text_wordcloud():
    sql_runs = [
        {
            "execute_sql_json": (
                '{"ok": true, "column_profiles": ['
                '{"name": "review_comment_message"}, {"name": "review_score"}], '
                '"row_count_returned": 100}'
            ),
        },
    ]
    charts = [
        VizChartTask(
            title="好评 vs 差评 评论词云对比",
            data_source="wordcloud",
            chart_type_hint="wordcloud",
        ),
        VizChartTask(
            title="某品类差评评论词云",
            data_source="sql_run",
            sql_run_index=0,
            chart_type_hint="wordcloud",
        ),
    ]
    deduped = _dedupe_viz_charts(charts, sql_runs=sql_runs)
    assert len(deduped) == 2
    fps = {chart_task_fingerprint(c, sql_runs=sql_runs) for c in deduped}
    assert "wordcloud:compare:global" in fps
    assert any(fp.startswith("sql_run:0:wordcloud:") for fp in fps)


def test_normalize_sql_run_wordcloud_without_text_to_bar():
    sql_runs = [
        {
            "execute_sql_json": (
                '{"ok": true, "column_profiles": ['
                '{"name": "keyword"}, {"name": "freq"}], '
                '"row_count_returned": 20}'
            ),
        },
    ]
    charts = [
        VizChartTask(
            title="评论中高频差评关键词(所有品类)",
            data_source="sql_run",
            sql_run_index=0,
            chart_type_hint="wordcloud",
        ),
    ]
    normalized = _normalize_chart_tasks(charts, sql_runs=sql_runs)
    assert normalized[0].chart_type_hint == "bar"
    assert chart_task_fingerprint(normalized[0], sql_runs=sql_runs) != "wordcloud:compare:global"


def test_enrich_does_not_add_duplicate_global_wordcloud():
    charts = [
        VizChartTask(
            title="评论中高频差评关键词(所有品类)",
            data_source="wordcloud",
            chart_type_hint="wordcloud",
        ),
    ]
    enriched = _enrich_diagnostic_review_charts(
        user_query="Top 10 差评品类及其主要差评原因是什么？",
        charts=charts,
        review_insights={"topic_distribution": {"delivery_delay": 10}},
    )
    global_wc = [c for c in enriched if c.data_source == "wordcloud"]
    assert len(global_wc) == 1


def test_enrich_adds_global_wordcloud_when_sql_was_mislabeled():
    sql_runs = [
        {
            "execute_sql_json": (
                '{"ok": true, "column_profiles": ['
                '{"name": "keyword"}, {"name": "count"}], '
                '"row_count_returned": 10}'
            ),
        },
    ]
    charts = _normalize_chart_tasks(
        [
            VizChartTask(
                title="评论中高频差评关键词(所有品类)",
                data_source="sql_run",
                sql_run_index=0,
                chart_type_hint="wordcloud",
            ),
        ],
        sql_runs=sql_runs,
    )
    enriched = _enrich_diagnostic_review_charts(
        user_query="Top 10 差评品类及其主要差评原因是什么？",
        charts=charts,
        review_insights={},
        sql_runs=sql_runs,
    )
    assert any(c.data_source == "wordcloud" for c in enriched)
    assert any(c.data_source == "sql_run" for c in enriched)


def test_extract_columns_from_summary_zh_without_profiles():
    payload = {
        "ok": True,
        "data_summary_zh": (
            "查询返回 10 行，耗时约 199.4 ms。共 2 列："
            "product_category_english, bad_review_count。"
        ),
    }
    cols = extract_columns_from_exec_payload(payload)
    assert cols == ["product_category_english", "bad_review_count"]


def test_ensure_sql_run_charts_when_llm_omits_them():
    sql_runs = [
        {
            "question": "差评数量排名前10的品类有哪些？",
            "execute_sql_json": (
                '{"ok": true, "data_summary_zh": "共 2 列：'
                "product_category_english, bad_review_count。\"}"
            ),
        },
        {
            "question": "这些差评的主要吐槽主题和原因为什么？",
            "execute_sql_json": (
                '{"ok": true, "data_summary_zh": "共 6 列：'
                "review_score, review_comment_title, review_comment_message, "
                'review_creation_date, order_id, order_purchase_timestamp。"}'
            ),
        },
    ]
    charts = _ensure_sql_run_chart_tasks(
        [
            VizChartTask(
                title="好评与差评评论词云对比",
                data_source="wordcloud",
                chart_type_hint="wordcloud",
            ),
        ],
        sql_runs=sql_runs,
        user_query="Top 10 差评品类及其主要差评原因是什么？",
        intent="diagnostic",
    )
    sql_indices = {
        c.sql_run_index for c in charts if c.data_source == "sql_run"
    }
    assert sql_indices == {0, 1}


def test_strip_insight_chart_when_nlp_data_empty():
    charts = [
        VizChartTask(
            title="Top差评品类 × 差评主题矩阵",
            data_source="review_insights",
            insight_chart_type="complaints_by_category",
            chart_type_hint="heatmap",
        ),
        VizChartTask(
            title="差评数量排名前10的品类有哪些",
            data_source="sql_run",
            sql_run_index=0,
            chart_type_hint="bar",
        ),
    ]
    kept = _strip_unrenderable_insight_charts(charts, {})
    assert len(kept) == 1
    assert kept[0].data_source == "sql_run"


def test_ensure_sql_run_skips_reason_question_without_reason_columns():
    sql_runs = [
        {
            "question": "这些品类的主要差评原因分布是什么样的？",
            "execute_sql_json": (
                '{"ok": true, "data_summary_zh": "共 3 列：'
                "product_category_english, bad_review_count, bad_review_rate。\"}"
            ),
        },
    ]
    charts = _ensure_sql_run_chart_tasks(
        [],
        sql_runs=sql_runs,
        user_query="Top 10 差评品类及其主要差评原因是什么？",
        intent="diagnostic",
    )
    assert not any(c.data_source == "sql_run" for c in charts)


def test_heuristic_diagnostic_at_most_one_global_compare_wordcloud():
    sql_runs = [
        {
            "question": "Top 10 差评品类是什么？",
            "execute_sql_json": (
                '{"ok": true, "column_profiles": ['
                '{"name": "product_category_english"}, {"name": "bad_review_count"}], '
                '"row_count_returned": 10}'
            ),
            "analysis_result": {"business_summary": "ok"},
        },
        {
            "question": "主要差评原因是什么？",
            "execute_sql_json": (
                '{"ok": true, "column_profiles": ['
                '{"name": "topic"}, {"name": "count"}], '
                '"row_count_returned": 8}'
            ),
            "analysis_result": {"business_summary": "ok"},
        },
    ]
    plan = heuristic_viz_suite(
        user_query="Top 10 差评品类及其主要差评原因是什么？",
        intent="diagnostic",
        sql_runs=sql_runs,
        review_insights={"topic_distribution": {"delivery_delay": 5}},
    )
    fingerprints = [
        chart_task_fingerprint(c, sql_runs=sql_runs) for c in plan.charts
    ]
    assert fingerprints.count("wordcloud:compare:global") <= 1
    sql_tasks = [c for c in plan.charts if c.data_source == "sql_run"]
    assert len(sql_tasks) >= 2
