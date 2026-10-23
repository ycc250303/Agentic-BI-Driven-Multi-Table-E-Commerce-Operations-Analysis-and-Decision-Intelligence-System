from pathlib import Path

import pytest

from agentic_bi.core.models import EvidenceSource
from agentic_bi.data.metrics import MetricCatalog

CONFIG_PATH = Path("config/metrics.yaml")


def test_catalog_loads_repository_configuration() -> None:
    catalog = MetricCatalog.load(CONFIG_PATH)

    assert catalog.version == "2.0"
    assert "total_gmv" in catalog.units_for(("total_gmv",))


def test_catalog_loading_uses_structure_validation_only(monkeypatch: pytest.MonkeyPatch) -> None:
    def parse_unexpectedly(*_args: object, **_kwargs: object) -> None:
        pytest.fail("配置加载入口不解析 SQL 表达式")

    monkeypatch.setattr("sqlglot.parse", parse_unexpectedly)
    assert MetricCatalog.load(CONFIG_PATH).version == "2.0"


def test_metric_context_declares_default_and_explicit_revenue_scopes() -> None:
    catalog = MetricCatalog.load(CONFIG_PATH)

    context = catalog.render_metric_context()

    assert "默认成交额口径" in context
    assert "用户只说销售额、成交额或 GMV 时使用本指标" in context
    assert "只在用户明确要求仅商品金额、不含运费或同等口径时使用" in context
    assert "只统计非已取消、非不可用的订单" in context
    assert "只统计已送达且客户签收时间不为空的订单" in context
    assert "分母为零" in context
    assert "not_delivered" in context
    assert "合法取值" in context


def test_catalog_rejects_unknown_metric() -> None:
    catalog = MetricCatalog.load(CONFIG_PATH)

    with pytest.raises(ValueError, match="未知指标"):
        catalog.validate_intent(
            metric_ids=("invented_metric",),
            dimensions=(),
            filter_fields=(),
            sort_by=None,
        )


def test_catalog_rejects_unsupported_dimension() -> None:
    catalog = MetricCatalog.load(CONFIG_PATH)

    with pytest.raises(ValueError, match="不支持以下维度"):
        catalog.validate_intent(
            metric_ids=("on_time_rate",),
            dimensions=("seller_id",),
            filter_fields=(),
            sort_by=None,
        )


def test_schema_context_only_contains_relevant_sources() -> None:
    catalog = MetricCatalog.load(CONFIG_PATH)

    context = catalog.render_schema_context(
        metric_ids=("total_transactions",),
        dimensions=("payment_type",),
    )

    assert "mv_payment_dist" in context
    assert "payments" in context
    assert "payment_type" in context
    assert "支付方式" in context
    assert "只统计非已取消、非不可用的订单" in context


def test_evidence_sources_keep_name_and_source_kind() -> None:
    catalog = MetricCatalog.load(CONFIG_PATH)

    sources = catalog.evidence_sources(("mv_state_sales", "order_items"))

    assert sources == (
        EvidenceSource(name="mv_state_sales", kind="view"),
        EvidenceSource(name="order_items", kind="table"),
    )


def test_result_columns_must_use_standard_names() -> None:
    catalog = MetricCatalog.load(CONFIG_PATH)

    with pytest.raises(ValueError, match="缺少标准输出列"):
        catalog.validate_result_columns(
            columns=("gmv_total",),
            metric_ids=("total_gmv",),
            dimensions=(),
        )


def test_filter_only_dimension_loads_without_grouping() -> None:
    catalog = MetricCatalog.load(CONFIG_PATH)

    catalog.validate_intent(
        metric_ids=("total_gmv",), dimensions=(), filter_fields=("order_status",), sort_by=None
    )
    with pytest.raises(ValueError, match="不支持以下维度"):
        catalog.validate_intent(
            metric_ids=("total_gmv",), dimensions=("order_status",), filter_fields=(), sort_by=None
        )


def test_filter_dependencies_are_included_in_sources() -> None:
    catalog = MetricCatalog.load(CONFIG_PATH)
    sources = catalog.allowed_sources(
        metric_ids=("total_orders",), dimensions=(), filter_fields=("payment_type",)
    )
    assert set(sources) == {"orders", "payments"}


def test_metric_rejects_filter_outside_its_supported_dimensions() -> None:
    catalog = MetricCatalog.load(CONFIG_PATH)
    with pytest.raises(ValueError, match="不支持以下过滤维度"):
        catalog.validate_intent(
            metric_ids=("on_time_rate",), dimensions=(), filter_fields=("seller_id",), sort_by=None
        )


def test_view_candidates_require_compatible_grain() -> None:
    catalog = MetricCatalog.load(CONFIG_PATH)
    payment = catalog.allowed_sources(
        metric_ids=("avg_installments",), dimensions=("payment_type",)
    )
    assert "mv_payment_dist" not in payment
    exact = catalog.allowed_sources(
        metric_ids=("avg_installments",), dimensions=("sales_month", "payment_type")
    )
    assert "mv_payment_dist" in exact
    orders = catalog.allowed_sources(metric_ids=("total_orders",), dimensions=("sales_month",))
    assert set(orders) == {"orders"}
    gmv = catalog.allowed_sources(metric_ids=("total_gmv",), dimensions=("seller_id",))
    assert "mv_seller_perf" not in gmv


@pytest.mark.parametrize(
    "content",
    [
        "[]",
        'version: "2.0"',
        CONFIG_PATH.read_text(encoding="utf-8").replace("version: '2.0'", "version: '3.0'"),
        CONFIG_PATH.read_text(encoding="utf-8").replace("kind: inner", "kind: cross", 1),
        CONFIG_PATH.read_text(encoding="utf-8").replace(
            "minimum_ranking_samples: 20", "minimum_ranking_samples: 0", 1
        ),
        CONFIG_PATH.read_text(encoding="utf-8") + "\nunknown_field: true\n",
    ],
    ids=["root_type", "missing_fields", "version", "join_kind", "sample_range", "extra_field"],
)
def test_catalog_rejects_invalid_structure(tmp_path: Path, content: str) -> None:
    path = tmp_path / "metrics.yaml"
    path.write_text(content, encoding="utf-8")
    with pytest.raises(ValueError):
        MetricCatalog.load(path)


def test_multi_metric_context_preserves_individual_view_requirements() -> None:
    catalog = MetricCatalog.load(CONFIG_PATH)
    context = catalog.render_schema_context(
        metric_ids=("total_transactions", "avg_installments"), dimensions=("payment_type",)
    )
    assert context.count("视图绑定（仅完整自然月范围）") == 1
    assert '"aggregate":"COALESCE(SUM(total_transactions), 0)"' in context
