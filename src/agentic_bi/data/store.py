"""把完整查询结果和规范化 SQL 保存为轻量引用。"""

from __future__ import annotations

import csv
import io
import json
import re
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

from pydantic import JsonValue

from agentic_bi.core.models import ArtifactKind, ArtifactRef


class Store:
    """在本地目录原子写入查询产物。"""

    def __init__(self, root: Path) -> None:
        self._root = root

    def write_csv(
        self,
        *,
        task_id: str,
        columns: tuple[str, ...],
        rows: tuple[dict[str, JsonValue], ...],
    ) -> ArtifactRef:
        """写入完整查询结果 CSV。"""
        buffer = io.StringIO(newline="")
        writer = csv.DictWriter(buffer, fieldnames=list(columns))
        writer.writeheader()

        for row in rows:
            writer.writerow({column: _csv_value(row.get(column)) for column in columns})

        return self._write(
            task_id=task_id,
            kind=ArtifactKind.CSV,
            suffix=".csv",
            content=buffer.getvalue().encode("utf-8-sig"),
        )

    def write_sql(self, *, task_id: str, sql: str) -> ArtifactRef:
        """写入经过 AST 规范化的实际执行 SQL。"""
        content = f"{sql.rstrip()}\n".encode()
        return self._write(
            task_id=task_id,
            kind=ArtifactKind.SQL,
            suffix=".sql",
            content=content,
        )

    def _write(
        self,
        *,
        task_id: str,
        kind: ArtifactKind,
        suffix: str,
        content: bytes,
    ) -> ArtifactRef:
        digest = sha256(content).hexdigest()
        safe_task_id = re.sub(r"[^a-zA-Z0-9_-]+", "-", task_id).strip("-")
        safe_task_id = safe_task_id[:80] or "task"
        artifact_id = f"{safe_task_id}-{kind.value}-{digest[:16]}"

        task_directory = self._root / safe_task_id
        task_directory.mkdir(parents=True, exist_ok=True)
        destination = task_directory / f"{artifact_id}{suffix}"

        temporary_path: Path | None = None
        try:
            with NamedTemporaryFile(
                dir=task_directory,
                prefix=".tmp-",
                delete=False,
            ) as temporary:
                temporary.write(content)
                temporary.flush()
                temporary_path = Path(temporary.name)
            temporary_path.replace(destination)
        finally:
            if temporary_path is not None and temporary_path.exists():
                temporary_path.unlink()

        created_at = datetime.now(UTC)
        return ArtifactRef(
            artifact_id=artifact_id,
            kind=kind,
            uri=destination.resolve().as_uri(),
            content_hash=digest,
            size_bytes=len(content),
            created_at=created_at,
        )


def _csv_value(value: Any) -> str | int | float | bool:
    """把 JSON 值转换为稳定 CSV 单元格。"""
    if value is None:
        return ""
    if isinstance(value, dict | list):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    if isinstance(value, str | int | float | bool):
        return value
    return str(value)
