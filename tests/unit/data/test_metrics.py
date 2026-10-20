from pathlib import Path

import pytest

from agentic_bi.core.models import EvidenceSource
from agentic_bi.data.metrics import MetricCatalog

CONFIG_PATH = Path("config/metrics.yaml")


def test_catalog_loads_repository_configuration() -> None:
    catalog = MetricCatalog.load(CONFIG_PATH)

    assert catalog.version == "1.0"
    assert "total_gmv" in catalog.units_for(("total_gmv",))


def test_metric_context_declares_default_and_explicit_revenue_scopes() -> None:
    catalog = MetricCatalog.load(CONFIG_PATH)

    context = catalog.render_metric_context()

    assert "默认成交额口径" in context
    assert "用户只说销售额、成交额或 GMV 时使用本指标" in context
    assert "只在用户明确要求仅商品金额、不含运费或同等口径时使用" in context
    assert context.count("只统计非已取消、非不可用的订单") == 24
    assert context.count("只统计已送达且客户签收时间不为空的订单") == 8


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
