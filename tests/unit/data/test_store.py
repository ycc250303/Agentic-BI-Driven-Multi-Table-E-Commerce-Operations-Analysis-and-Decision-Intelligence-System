from pathlib import Path

from agentic_bi.core.models import ArtifactKind
from agentic_bi.data.store import Store


def test_write_csv_returns_stable_reference(tmp_path: Path) -> None:
    store = Store(tmp_path)

    artifact = store.write_csv(
        task_id="task-1",
        columns=("customer_state", "total_gmv"),
        rows=(
            {"customer_state": "SP", "total_gmv": 100.5},
            {"customer_state": "RJ", "total_gmv": 80.0},
        ),
    )

    assert artifact.kind == ArtifactKind.CSV
    assert artifact.size_bytes > 0
    assert artifact.uri.startswith("file://")
    assert Path(artifact.uri.removeprefix("file://")).is_file()


def test_write_sql_does_not_embed_sql_in_reference(tmp_path: Path) -> None:
    store = Store(tmp_path)

    artifact = store.write_sql(
        task_id="task-1",
        sql="SELECT 1 AS value",
    )

    assert artifact.kind == ArtifactKind.SQL
    assert "SELECT" not in artifact.artifact_id
    assert len(artifact.content_hash) == 64
