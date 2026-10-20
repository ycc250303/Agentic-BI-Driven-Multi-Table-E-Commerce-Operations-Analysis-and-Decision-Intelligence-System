"""数据分析 Agent 的 LangSmith 冒烟实验。"""

from __future__ import annotations

import csv
import json
from collections import Counter
from collections.abc import Mapping
from decimal import Decimal
from pathlib import Path
from typing import Any, cast
from urllib.parse import unquote, urlparse
from uuid import NAMESPACE_URL, uuid5

from langsmith import Client

from agentic_bi.agents.analysis.run import run_analysis
from agentic_bi.agents.analysis.schemas import AnalysisRequest
from agentic_bi.core.models import ArtifactKind
from agentic_bi.core.observability import configure_langsmith
from agentic_bi.core.settings import Settings
from agentic_bi.data.database import ReadOnlyDatabase

_DATASET_PATH = Path(__file__).with_name("datasets") / "analysis_mvp.json"
_DIFFICULTIES = frozenset({"easy", "mid", "hard"})


def load_dataset() -> dict[str, Any]:
    """读取本地数据集，并校验同步所需的稳定字段。"""
    data: object = json.loads(_DATASET_PATH.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise TypeError("评估数据集根节点必须是对象")
    if not isinstance(data.get("dataset_name"), str) or not data["dataset_name"]:
        raise ValueError("评估数据集必须提供 dataset_name")
    if not isinstance(data.get("description"), str) or not data["description"]:
        raise ValueError("评估数据集必须提供 description")
    examples = data.get("examples")
    if not isinstance(examples, list) or not examples:
        raise ValueError("评估数据集必须包含 examples")

    case_ids: list[str] = []
    for example in examples:
        if not isinstance(example, dict):
            raise TypeError("每条评估样本必须是对象")
        metadata = example.get("metadata")
        case_id = None if not isinstance(metadata, dict) else metadata.get("case_id")
        if not isinstance(case_id, str) or not case_id:
            raise ValueError("每条评估样本必须提供 metadata.case_id")
        if metadata.get("difficulty") not in _DIFFICULTIES:
            raise ValueError(f"样本 {case_id} 的 difficulty 必须是 easy、mid 或 hard")
        if not isinstance(example.get("split"), str) or not example["split"]:
            raise ValueError(f"样本 {case_id} 必须使用 LangSmith 原生 split")
        case_ids.append(case_id)
    if len(case_ids) != len(set(case_ids)):
        raise ValueError("metadata.case_id 不能重复")
    return data


def sync_dataset(client: Client, data: Mapping[str, Any]) -> str:
    """以本地 JSON 为准同步 LangSmith，并重新读取检查内容与 Split。"""
    dataset_name = str(data["dataset_name"])
    if client.has_dataset(dataset_name=dataset_name):
        dataset = client.read_dataset(dataset_name=dataset_name)
    else:
        dataset = client.create_dataset(
            dataset_name=dataset_name,
            description=str(data["description"]),
        )

    uploads = [_upload_example(dataset_name, example) for example in data["examples"]]
    remote_by_id = {
        str(example.id): example for example in client.list_examples(dataset_id=dataset.id)
    }
    expected_ids = {str(example["id"]) for example in uploads}
    missing: list[dict[str, Any]] = []
    for example in uploads:
        example_id = str(example["id"])
        if example_id not in remote_by_id:
            missing.append(example)
            continue
        client.update_example(
            example_id,
            inputs=example["inputs"],
            outputs=example["outputs"],
            metadata=example["metadata"],
            split=example["split"],
            dataset_id=dataset.id,
        )
    if missing:
        client.create_examples(dataset_id=dataset.id, examples=missing, max_concurrency=1)
    for example_id in remote_by_id.keys() - expected_ids:
        client.delete_example(example_id)

    expected = {_example_snapshot(example) for example in uploads}
    actual = _remote_snapshots(client, str(dataset.id))
    if actual != expected:
        raise RuntimeError("LangSmith 数据集同步后仍与本地 JSON 不一致")
    return str(dataset.id)


def _upload_example(dataset_name: str, example: Mapping[str, Any]) -> dict[str, Any]:
    """为本地样本补充稳定 LangSmith Example ID。"""
    metadata = example["metadata"]
    case_id = str(metadata["case_id"])
    return {
        "id": str(uuid5(NAMESPACE_URL, f"{dataset_name}:{case_id}")),
        "inputs": example["inputs"],
        "outputs": example["outputs"],
        "metadata": metadata,
        "split": example["split"],
    }


def _remote_snapshots(client: Client, dataset_id: str) -> set[str]:
    """读取远程样本及其原生 Split，形成可比较快照。"""
    examples = list(client.list_examples(dataset_id=dataset_id))
    split_by_id: dict[str, list[str]] = {str(example.id): [] for example in examples}
    for split in client.list_dataset_splits(dataset_id=dataset_id):
        for example in client.list_examples(dataset_id=dataset_id, splits=[split]):
            split_by_id[str(example.id)].append(split)
    return {
        _stable_json(
            {
                "id": str(example.id),
                "inputs": example.inputs,
                "outputs": example.outputs,
                "metadata": _user_metadata(example.metadata),
                "split": sorted(split_by_id[str(example.id)]),
            }
        )
        for example in examples
    }


def _example_snapshot(example: Mapping[str, Any]) -> str:
    """把本地上传样本转换成远程检查格式。"""
    return _stable_json({**example, "split": [example["split"]]})


def _user_metadata(metadata: Mapping[str, Any] | None) -> dict[str, Any]:
    """移除 LangSmith 依据原生 Split 自动生成的平台元数据。"""
    values = dict(metadata or {})
    values.pop("dataset_split", None)
    return values


def target(inputs: dict[str, Any]) -> dict[str, Any]:
    """执行真实分析链路，并返回核心语义与完整 CSV 结果。"""
    result = run_analysis(AnalysisRequest.model_validate(inputs))
    value = result.value
    evidence = None if value is None else value.evidence
    clarification = None if value is None else value.clarification
    return {
        "status": result.status.value,
        "error_code": None if result.error is None else result.error.code.value,
        "intent": _core_intent(evidence=evidence),
        "rows": _read_csv_rows(evidence),
        "has_evidence": evidence is not None,
        "returned_row_count": None if evidence is None else evidence.returned_row_count,
        "clarification_code": None if clarification is None else clarification.code.value,
        "clarification_questions": ([] if clarification is None else list(clarification.questions)),
    }


def _core_intent(*, evidence: Any) -> dict[str, Any]:
    """提取会直接改变查询结果的四组业务语义。"""
    if evidence is not None:
        return {
            "metric_ids": list(evidence.metric_ids),
            "dimensions": list(evidence.grain),
            "filters": evidence.scope.get("filters", []),
            "time_range": evidence.scope.get("time_range"),
        }
    return {"metric_ids": [], "dimensions": [], "filters": [], "time_range": None}


def _read_csv_rows(evidence: Any) -> list[dict[str, str]]:
    """读取 Evidence 指向的完整 CSV；没有 Evidence 时返回空结果。"""
    if evidence is None:
        return []
    artifacts = [item for item in evidence.artifacts if item.kind == ArtifactKind.CSV]
    if len(artifacts) != 1:
        raise ValueError("成功结果必须且只能包含一个 CSV Artifact")
    parsed = urlparse(artifacts[0].uri)
    if parsed.scheme != "file" or parsed.netloc not in {"", "localhost"}:
        raise ValueError("评估只允许读取本地 file CSV Artifact")
    with Path(unquote(parsed.path)).open(encoding="utf-8-sig", newline="") as file:
        return list(csv.DictReader(file))


def analysis_evaluators(
    outputs: dict[str, Any],
    reference_outputs: dict[str, Any],
) -> list[dict[str, Any]]:
    """按参考终态选择查数评分或澄清评分。"""
    expected_status = reference_outputs["expected_status"]
    status_ok = outputs["status"] == expected_status
    if expected_status == "success":
        semantic_ok = _canonical_intent(outputs["intent"]) == _canonical_intent(
            reference_outputs["intent"]
        )
        execution_ok = _execution_matches(outputs["rows"], reference_outputs["gold_sql"])
        return [
            {"key": "status_match", "score": status_ok},
            {"key": "semantic_match", "score": semantic_ok},
            {"key": "execution_accuracy", "score": execution_ok},
        ]

    clarification_code_ok = (
        outputs["clarification_code"] == reference_outputs["expected_clarification_code"]
    )
    clarification_has_question = len(outputs["clarification_questions"]) > 0
    clarification_has_no_evidence = (
        not outputs["has_evidence"]
        and outputs["returned_row_count"] is None
        and not outputs["rows"]
    )
    return [
        {"key": "status_match", "score": status_ok},
        {"key": "semantic_match", "score": clarification_code_ok},
        {"key": "clarification_has_question", "score": clarification_has_question},
        {"key": "clarification_has_no_evidence", "score": clarification_has_no_evidence},
    ]


def _canonical_intent(intent: Mapping[str, Any]) -> dict[str, Any]:
    """消除指标、维度、过滤条件和集合过滤值的无业务顺序差异。"""
    filters = [_canonical_filter(item) for item in intent.get("filters", [])]
    filters.sort(key=_stable_json)
    return {
        "metric_ids": sorted(intent.get("metric_ids", [])),
        "dimensions": sorted(intent.get("dimensions", [])),
        "filters": filters,
        "time_range": intent.get("time_range"),
    }


def _canonical_filter(filter_spec: Mapping[str, Any]) -> dict[str, Any]:
    """规范化一个过滤条件，同时保留区间边界顺序。"""
    operator = filter_spec["operator"]
    value = filter_spec.get("value")
    if operator in {"in", "not_in"} and isinstance(value, list):
        value = sorted(value, key=_stable_json)
    return {"field": filter_spec["field"], "operator": operator, "value": value}


def _execution_matches(rows: list[dict[str, Any]], gold_sql: str) -> bool:
    """用只读账号执行 Gold SQL，并与完整 CSV 行集合比较。"""
    database = ReadOnlyDatabase(Settings())
    try:
        gold_rows = [dict(row) for row in database.execute(gold_sql).rows]
    finally:
        database.close()
    return _same_rows(rows, gold_rows)


def _same_rows(rows: list[dict[str, Any]], gold_rows: list[dict[str, Any]]) -> bool:
    """按 Gold 列比较无序行集合，并规范化数值类型。"""
    if len(rows) != len(gold_rows):
        return False
    if not gold_rows:
        return True
    columns = tuple(gold_rows[0])
    numeric = {
        column
        for column in columns
        if all(
            value is None or (isinstance(value, int | float) and not isinstance(value, bool))
            for value in (row.get(column) for row in gold_rows)
        )
    }
    return Counter(_project(row, columns, numeric) for row in rows) == Counter(
        _project(row, columns, numeric) for row in gold_rows
    )


def _project(
    row: Mapping[str, Any],
    columns: tuple[str, ...],
    numeric: set[str],
) -> tuple[tuple[str, Any], ...]:
    """按照 Gold 列和类型投影一行结果。"""
    values: list[tuple[str, Any]] = []
    for column in columns:
        value = row.get(column)
        if value == "":
            value = None
        elif column in numeric and value is not None:
            value = Decimal(str(value))
            if column.endswith(("_gmv", "_freight")) or column.startswith("avg_"):
                value = value.quantize(Decimal("0.01"))
        values.append((column, value))
    return tuple(values)


def _stable_json(value: Any) -> str:
    """生成集合排序和数据集一致性检查使用的稳定 JSON。"""
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def main() -> None:
    """同步本地数据集，并串行运行一次冒烟实验。"""
    settings = Settings()
    configure_langsmith(settings)
    client = Client()
    dataset = load_dataset()
    dataset_id = sync_dataset(client, dataset)
    print(f"数据集：{dataset['dataset_name']} {dataset_id}")

    results = client.evaluate(
        target,
        data=str(dataset["dataset_name"]),
        evaluators=[cast(Any, analysis_evaluators)],
        experiment_prefix=f"analysis-{settings.llm_provider.value}-{settings.model_for()}",
        max_concurrency=1,
        num_repetitions=1,
        metadata={
            "model_provider": settings.llm_provider.value,
            "model": settings.model_for(),
        },
    )
    print(f"实验：{results.url}")
    frame = cast(Any, results.to_pandas())
    score_columns = [name for name in frame.columns if name.startswith("feedback.")]
    print(frame[["inputs.question", *score_columns]].to_string(index=False))


if __name__ == "__main__":
    main()
