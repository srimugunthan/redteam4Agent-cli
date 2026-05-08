from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import aiosqlite

from agentrt.adapters.base import (
    AgentResponse,
    AttackPayload,
    AttackResult,
    CampaignResult,
    JudgeVerdict,
)

_DDL = """
CREATE TABLE IF NOT EXISTS runs (
    run_id        TEXT PRIMARY KEY,
    campaign_name TEXT,
    started_at    TEXT,
    completed_at  TEXT,
    config_json   TEXT
);

CREATE TABLE IF NOT EXISTS attack_results (
    result_id    TEXT PRIMARY KEY,
    run_id       TEXT REFERENCES runs(run_id),
    attack_id    TEXT,
    success      INTEGER,
    confidence   REAL,
    payload_json TEXT,
    trace_json   TEXT,
    verdict_json TEXT
);
"""

# Sentinel distinguishing "caller passed no jsonl_dir argument" from "caller
# explicitly passed None (disable JSONL)".
_UNSET = object()


class TraceStore:
    """Append-only store for attack results.

    Every save() call writes to SQLite (canonical, queryable) and appends to a
    JSONL side-car file (human-readable, greppable) simultaneously — DD-17.

    A single database connection is held open for the lifetime of the store so
    that in-memory SQLite (':memory:') works correctly across multiple method
    calls.  Call init() before any other method, and close() (or use as an
    async context manager) when done.

    Args:
        db_path:   SQLite file path.  Use ':memory:' for in-process tests.
        jsonl_dir: Directory for '{run_id}.jsonl'.  If omitted, defaults to the
                   parent directory of db_path (disabled for ':memory:').
                   Pass None explicitly to suppress JSONL output — useful in
                   unit tests that only care about SQLite round-trips.
    """

    def __init__(
        self,
        db_path: str | Path,
        jsonl_dir: str | Path | None | object = _UNSET,
    ) -> None:
        self._db_path = str(db_path)
        if jsonl_dir is _UNSET:
            self._jsonl_dir: Optional[Path] = (
                Path(db_path).parent if self._db_path != ":memory:" else None
            )
        elif jsonl_dir is None:
            self._jsonl_dir = None
        else:
            self._jsonl_dir = Path(jsonl_dir)  # type: ignore[arg-type]

        self._conn: Optional[aiosqlite.Connection] = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def init(self) -> None:
        """Open the database connection and create tables.  Must be called once."""
        self._conn = await aiosqlite.connect(self._db_path)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.executescript(_DDL)
        await self._conn.commit()

    async def close(self) -> None:
        if self._conn is not None:
            await self._conn.close()
            self._conn = None

    async def __aenter__(self) -> "TraceStore":
        await self.init()
        return self

    async def __aexit__(self, *_) -> None:
        await self.close()

    def _db(self) -> aiosqlite.Connection:
        if self._conn is None:
            raise RuntimeError("TraceStore.init() has not been called.")
        return self._conn

    # ------------------------------------------------------------------
    # Run management
    # ------------------------------------------------------------------

    async def create_run(
        self,
        run_id: str,
        campaign_name: str,
        config: dict | None = None,
    ) -> None:
        db = self._db()
        await db.execute(
            "INSERT OR IGNORE INTO runs "
            "(run_id, campaign_name, started_at, config_json) VALUES (?,?,?,?)",
            (
                run_id,
                campaign_name,
                datetime.now(tz=timezone.utc).isoformat(),
                json.dumps(config or {}),
            ),
        )
        await db.commit()

    async def complete_run(self, run_id: str) -> None:
        db = self._db()
        await db.execute(
            "UPDATE runs SET completed_at = ? WHERE run_id = ?",
            (datetime.now(tz=timezone.utc).isoformat(), run_id),
        )
        await db.commit()

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    async def save(
        self,
        run_id: str,
        attack_id: str,
        payload: AttackPayload,
        response: AgentResponse,
        verdict: JudgeVerdict,
    ) -> None:
        """Persist one AttackResult immediately (crash safety, NFR-012)."""
        result_id = str(uuid.uuid4())
        recorded_at = datetime.now(tz=timezone.utc).isoformat()

        db = self._db()
        await db.execute(
            "INSERT INTO attack_results "
            "(result_id, run_id, attack_id, success, confidence, "
            " payload_json, trace_json, verdict_json) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (
                result_id,
                run_id,
                attack_id,
                int(verdict.success),
                verdict.confidence,
                payload.model_dump_json(),
                response.model_dump_json(),
                verdict.model_dump_json(),
            ),
        )
        await db.commit()

        # JSONL side-car (DD-17) — best-effort, flushed immediately.
        if self._jsonl_dir is not None:
            self._jsonl_dir.mkdir(parents=True, exist_ok=True)
            record = {
                "run_id": run_id,
                "attack_id": attack_id,
                "success": verdict.success,
                "confidence": verdict.confidence,
                "payload": payload.model_dump(),
                "response": response.model_dump(),
                "verdict": verdict.model_dump(),
                "recorded_at": recorded_at,
            }
            jsonl_path = self._jsonl_dir / f"{run_id}.jsonl"
            with open(jsonl_path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(record) + "\n")
                fh.flush()

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    async def load(self, run_id: str) -> CampaignResult:
        """Reconstruct a CampaignResult from SQLite."""
        db = self._db()
        async with db.execute(
            "SELECT * FROM runs WHERE run_id = ?", (run_id,)
        ) as cur:
            run_row = await cur.fetchone()
        if run_row is None:
            raise KeyError(f"Run not found: {run_id!r}")

        async with db.execute(
            "SELECT * FROM attack_results WHERE run_id = ? ORDER BY rowid",
            (run_id,),
        ) as cur:
            result_rows = await cur.fetchall()

        results: list[AttackResult] = []
        for row in result_rows:
            payload = AttackPayload.model_validate_json(row["payload_json"])
            response = AgentResponse.model_validate_json(row["trace_json"])
            verdict = JudgeVerdict.model_validate_json(row["verdict_json"])
            results.append(AttackResult(payload=payload, response=response, verdict=verdict))

        completed_raw = run_row["completed_at"]
        completed_at = (
            datetime.fromisoformat(completed_raw)
            if completed_raw
            else datetime.now(tz=timezone.utc)
        )
        return CampaignResult(
            run_id=run_id,
            campaign_name=run_row["campaign_name"],
            results=results,
            started_at=datetime.fromisoformat(run_row["started_at"]),
            completed_at=completed_at,
        )

    # ------------------------------------------------------------------
    # Export helper (wired to agentrt trace export in Phase 7)
    # ------------------------------------------------------------------

    async def export(self, run_id: str, fmt: str, path: str | Path) -> Path:
        """Export a campaign result to a file.

        Args:
            run_id: The run to export.
            fmt:    'json' | 'jsonl'
            path:   Output directory.

        Returns:
            Path of the written file.
        """
        out_dir = Path(path)
        out_dir.mkdir(parents=True, exist_ok=True)

        if fmt == "json":
            result = await self.load(run_id)
            output_path = out_dir / f"{run_id}.json"
            output_path.write_text(result.model_dump_json(indent=2), encoding="utf-8")
            return output_path

        if fmt == "jsonl":
            if self._jsonl_dir is not None:
                src = self._jsonl_dir / f"{run_id}.jsonl"
                dst = out_dir / f"{run_id}.jsonl"
                if src.exists() and src != dst:
                    import shutil
                    shutil.copy(src, dst)
                    return dst
            # Fallback: reconstruct JSONL from SQLite.
            result = await self.load(run_id)
            output_path = out_dir / f"{run_id}.jsonl"
            with open(output_path, "w", encoding="utf-8") as fh:
                for ar in result.results:
                    fh.write(
                        json.dumps({
                            "run_id": run_id,
                            "attack_id": ar.payload.metadata.get("plugin_id", "unknown"),
                            "success": ar.verdict.success,
                            "confidence": ar.verdict.confidence,
                            "payload": ar.payload.model_dump(),
                            "response": ar.response.model_dump(),
                            "verdict": ar.verdict.model_dump(),
                        }) + "\n"
                    )
            return output_path

        raise ValueError(f"Unknown export format: {fmt!r}. Choose 'json' or 'jsonl'.")
