from __future__ import annotations

import json
import os
import re
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from primus.errors import IntegrityError, LifecycleError
from primus.jsonutil import atomic_json, bytes_hash, canonical_bytes, read_json, utc_now, write_immutable
from primus.models import ALLOWED_TRANSITIONS, RoundStatus


SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS champions(
    domain TEXT NOT NULL,
    champion_id TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('active','legacy','superseded','bootstrap')),
    structure_sha256 TEXT NOT NULL,
    artifact_sha256 TEXT NOT NULL,
    structure_object TEXT NOT NULL,
    artifact_object TEXT NOT NULL,
    certification_receipt_sha256 TEXT,
    source_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    artifact_scope TEXT NOT NULL DEFAULT 'domain_lineage',
    artifact_lineage_id TEXT,
    PRIMARY KEY(domain, champion_id)
);
CREATE UNIQUE INDEX IF NOT EXISTS one_active_champion_per_domain
    ON champions(domain) WHERE status='active';
CREATE TABLE IF NOT EXISTS rounds(
    domain TEXT NOT NULL,
    round_index INTEGER NOT NULL,
    run_id TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL,
    incumbent_id TEXT NOT NULL,
    incumbent_structure_sha256 TEXT NOT NULL,
    proposal_sha256 TEXT,
    candidate_structure_sha256 TEXT,
    public_receipt_sha256 TEXT,
    attribution_receipt_sha256 TEXT,
    hidden_receipt_sha256 TEXT,
    decision_sha256 TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY(domain, round_index)
);
CREATE TABLE IF NOT EXISTS receipts(
    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
    receipt_sha256 TEXT NOT NULL UNIQUE,
    previous_sha256 TEXT,
    domain TEXT NOT NULL,
    run_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    object_path TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS feedback(
    feedback_sha256 TEXT PRIMARY KEY,
    domain TEXT NOT NULL,
    source_receipt_sha256 TEXT NOT NULL,
    public_only INTEGER NOT NULL CHECK(public_only=1),
    object_path TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS taskset_consumption(
    taskset_sha256 TEXT NOT NULL,
    domain TEXT NOT NULL,
    split TEXT NOT NULL,
    run_id TEXT NOT NULL,
    consumed_at TEXT NOT NULL,
    PRIMARY KEY(taskset_sha256, domain, split, run_id)
);
CREATE TABLE IF NOT EXISTS hidden_consumption(
    semantic_selection_sha256 TEXT NOT NULL,
    domain TEXT NOT NULL,
    split TEXT NOT NULL CHECK(split='certification'),
    run_id TEXT NOT NULL,
    taskset_selection_sha256 TEXT NOT NULL,
    consumed_at TEXT NOT NULL,
    PRIMARY KEY(domain, split, semantic_selection_sha256)
);
CREATE TABLE IF NOT EXISTS artifact_versions(
    domain TEXT NOT NULL,
    lineage_id TEXT NOT NULL,
    artifact_id TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('active','superseded','reference')),
    task_fingerprint TEXT,
    artifact_sha256 TEXT NOT NULL,
    artifact_object TEXT NOT NULL,
    source_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY(domain, lineage_id, artifact_id)
);
CREATE UNIQUE INDEX IF NOT EXISTS one_active_artifact_per_lineage
    ON artifact_versions(domain,lineage_id) WHERE status='active';
CREATE TABLE IF NOT EXISTS experiment_lessons(
    lesson_sha256 TEXT PRIMARY KEY,
    domain TEXT NOT NULL,
    run_id TEXT NOT NULL,
    public_only INTEGER NOT NULL CHECK(public_only=1),
    operation TEXT NOT NULL,
    outcome TEXT NOT NULL,
    object_path TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(domain,run_id)
);
"""


class PrimusStore:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.database = self.root / "state" / "primus.db"
        self.objects = self.root / "objects" / "sha256"
        self.receipts = self.root / "receipts" / "sha256"
        self.pointers = self.root / "registry" / "domains"

    def initialize(self) -> None:
        for path in (self.database.parent, self.objects, self.receipts, self.pointers):
            path.mkdir(parents=True, exist_ok=True)
        with self.connect() as connection:
            connection.executescript(SCHEMA)
            columns = {row[1] for row in connection.execute("PRAGMA table_info(rounds)")}
            if "attribution_receipt_sha256" not in columns:
                connection.execute("ALTER TABLE rounds ADD COLUMN attribution_receipt_sha256 TEXT")
            champion_columns = {row[1] for row in connection.execute("PRAGMA table_info(champions)")}
            if "artifact_scope" not in champion_columns:
                connection.execute("ALTER TABLE champions ADD COLUMN artifact_scope TEXT NOT NULL DEFAULT 'domain_lineage'")
            if "artifact_lineage_id" not in champion_columns:
                connection.execute("ALTER TABLE champions ADD COLUMN artifact_lineage_id TEXT")
            connection.execute(
                """INSERT OR IGNORE INTO hidden_consumption(
                    semantic_selection_sha256,domain,split,run_id,taskset_selection_sha256,consumed_at
                ) SELECT taskset_sha256,domain,split,run_id,taskset_sha256,consumed_at
                  FROM taskset_consumption WHERE split='certification'"""
            )
            connection.execute("INSERT OR REPLACE INTO meta(key,value) VALUES('schema_version','5')")
            connection.commit()

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database, timeout=30)
        connection.row_factory = sqlite3.Row
        return connection

    @staticmethod
    def _validate_domain(domain: str) -> None:
        if re.fullmatch(r"[a-z][a-z0-9_]*", domain) is None:
            raise LifecycleError(f"invalid domain: {domain}")

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        connection = self.connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def put_object(self, data: bytes, *, suffix: str = "bin") -> tuple[str, str]:
        digest = bytes_hash(data)
        relative = f"objects/sha256/{digest[:2]}/{digest}.{suffix}"
        path = self.root / relative
        write_immutable(path, data)
        return digest, relative.replace("\\", "/")

    def put_json_object(self, value: Any) -> tuple[str, str]:
        return self.put_object(canonical_bytes(value), suffix="json")

    def import_champion(
        self,
        *,
        domain: str,
        champion_id: str,
        structure: dict[str, Any],
        artifact: bytes,
        active: bool,
        source: dict[str, Any],
        certification_receipt_sha256: str | None = None,
        artifact_scope: str = "domain_lineage",
        artifact_lineage_id: str | None = "default",
    ) -> dict[str, Any]:
        self._validate_domain(domain)
        if artifact_scope not in {"domain_lineage", "task_local"}:
            raise LifecycleError(f"invalid artifact scope: {artifact_scope}")
        if artifact_scope == "task_local":
            artifact_lineage_id = None
        structure_digest, structure_object = self.put_json_object(structure)
        artifact_digest, artifact_object = self.put_object(artifact, suffix="artifact")
        status = "active" if active else "legacy"
        with self.transaction() as connection:
            if active:
                existing = connection.execute(
                    "SELECT champion_id FROM champions WHERE domain=? AND status='active'",
                    (domain,),
                ).fetchone()
                if existing is not None and existing["champion_id"] != champion_id:
                    raise LifecycleError(f"domain already has an active champion: {domain}/{existing['champion_id']}")
            connection.execute(
                """INSERT INTO champions(
                    domain,champion_id,status,structure_sha256,artifact_sha256,
                    structure_object,artifact_object,certification_receipt_sha256,source_json,created_at,
                    artifact_scope,artifact_lineage_id
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(domain,champion_id) DO UPDATE SET
                    status=excluded.status,
                    structure_sha256=excluded.structure_sha256,
                    artifact_sha256=excluded.artifact_sha256,
                    structure_object=excluded.structure_object,
                    artifact_object=excluded.artifact_object,
                    certification_receipt_sha256=excluded.certification_receipt_sha256,
                    source_json=excluded.source_json,
                    artifact_scope=excluded.artifact_scope,
                    artifact_lineage_id=excluded.artifact_lineage_id
                """,
                (
                    domain,
                    champion_id,
                    status,
                    structure_digest,
                    artifact_digest,
                    structure_object,
                    artifact_object,
                    certification_receipt_sha256,
                    json.dumps(source, ensure_ascii=False, sort_keys=True),
                    utc_now(),
                    artifact_scope,
                    artifact_lineage_id,
                ),
            )
            if artifact_scope == "domain_lineage" and artifact_lineage_id is not None:
                if active:
                    connection.execute(
                        "UPDATE artifact_versions SET status='superseded' WHERE domain=? AND lineage_id=? AND status='active' AND artifact_id<>?",
                        (domain, artifact_lineage_id, champion_id),
                    )
                connection.execute(
                    """INSERT INTO artifact_versions(
                        domain,lineage_id,artifact_id,status,task_fingerprint,artifact_sha256,
                        artifact_object,source_json,created_at
                    ) VALUES(?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(domain,lineage_id,artifact_id) DO UPDATE SET
                        status=excluded.status,
                        artifact_sha256=excluded.artifact_sha256,
                        artifact_object=excluded.artifact_object,
                        source_json=excluded.source_json""",
                    (
                        domain,
                        artifact_lineage_id,
                        champion_id,
                        "active" if active else "reference",
                        None,
                        artifact_digest,
                        artifact_object,
                        json.dumps(source, ensure_ascii=False, sort_keys=True),
                        utc_now(),
                    ),
                )
        record = self.champion(domain, champion_id)
        if active:
            self._write_pointer(record)
        return record

    def champion(self, domain: str, champion_id: str | None = None) -> dict[str, Any]:
        query = "SELECT * FROM champions WHERE domain=? AND status='active'"
        params: tuple[Any, ...] = (domain,)
        if champion_id is not None:
            query = "SELECT * FROM champions WHERE domain=? AND champion_id=?"
            params = (domain, champion_id)
        with self.connect() as connection:
            row = connection.execute(query, params).fetchone()
        if row is None:
            raise LifecycleError(f"champion not found: {domain}/{champion_id or 'active'}")
        value = dict(row)
        value["source"] = json.loads(value.pop("source_json"))
        return value

    def list_champions(self, domain: str | None = None) -> list[dict[str, Any]]:
        query = "SELECT * FROM champions"
        params: tuple[Any, ...] = ()
        if domain:
            query += " WHERE domain=?"
            params = (domain,)
        query += " ORDER BY domain, created_at, champion_id"
        with self.connect() as connection:
            return [dict(row) for row in connection.execute(query, params)]

    def artifact_versions(self, domain: str, lineage_id: str | None = None) -> list[dict[str, Any]]:
        query = "SELECT * FROM artifact_versions WHERE domain=?"
        params: tuple[Any, ...] = (domain,)
        if lineage_id is not None:
            query += " AND lineage_id=?"
            params = (domain, lineage_id)
        query += " ORDER BY created_at, artifact_id"
        with self.connect() as connection:
            rows = [dict(row) for row in connection.execute(query, params)]
        for row in rows:
            row["source"] = json.loads(row.pop("source_json"))
        return rows

    def reconcile_active_artifact_scope(self, domain: str, artifact_scope: str) -> dict[str, Any]:
        """Upgrade a pre-v5 active champion to the configured artifact semantics."""
        if artifact_scope not in {"domain_lineage", "task_local"}:
            raise LifecycleError(f"invalid artifact scope: {artifact_scope}")
        champion = self.champion(domain)
        lineage_id = "default" if artifact_scope == "domain_lineage" else None
        if (
            champion.get("artifact_scope") == artifact_scope
            and champion.get("artifact_lineage_id") == lineage_id
        ):
            return champion
        with self.transaction() as connection:
            connection.execute(
                "UPDATE champions SET artifact_scope=?,artifact_lineage_id=? WHERE domain=? AND status='active'",
                (artifact_scope, lineage_id, domain),
            )
            if artifact_scope == "domain_lineage":
                active = connection.execute(
                    "SELECT artifact_id FROM artifact_versions WHERE domain=? AND lineage_id=? AND status='active'",
                    (domain, lineage_id),
                ).fetchone()
                if active is None:
                    connection.execute(
                        """INSERT OR IGNORE INTO artifact_versions(
                            domain,lineage_id,artifact_id,status,task_fingerprint,artifact_sha256,
                            artifact_object,source_json,created_at
                        ) VALUES(?,?,?,?,?,?,?,?,?)""",
                        (
                            domain,
                            lineage_id,
                            champion["champion_id"],
                            "active",
                            None,
                            champion["artifact_sha256"],
                            champion["artifact_object"],
                            json.dumps({"kind": "v5-scope-reconciliation"}, sort_keys=True),
                            utc_now(),
                        ),
                    )
        reconciled = self.champion(domain)
        self._write_pointer(reconciled)
        return reconciled

    def add_experiment_lesson(self, *, domain: str, run_id: str, payload: dict[str, Any]) -> str:
        if payload.get("public_only") is not True:
            raise LifecycleError("experiment lessons must be public-only")
        digest, relative = self.put_json_object(payload)
        with self.transaction() as connection:
            existing = connection.execute(
                "SELECT lesson_sha256 FROM experiment_lessons WHERE domain=? AND run_id=?",
                (domain, run_id),
            ).fetchone()
            if existing is not None and existing["lesson_sha256"] != digest:
                raise IntegrityError(f"experiment lesson changed: {domain}/{run_id}")
            connection.execute(
                """INSERT OR IGNORE INTO experiment_lessons(
                    lesson_sha256,domain,run_id,public_only,operation,outcome,object_path,created_at
                ) VALUES(?,?,?,?,?,?,?,?)""",
                (
                    digest,
                    domain,
                    run_id,
                    1,
                    str(payload.get("operation", payload.get("exploration_operation", "unknown"))),
                    str(payload.get("outcome", "unknown")),
                    relative,
                    utc_now(),
                ),
            )
        return digest

    def experiment_lessons(self, domain: str, *, limit: int = 100) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = list(connection.execute(
                "SELECT object_path FROM experiment_lessons WHERE domain=? ORDER BY created_at DESC LIMIT ?",
                (domain, int(limit)),
            ))
        return [read_json(self.root / row["object_path"]) for row in reversed(rows)]

    def object_bytes(self, relative: str, expected_sha256: str) -> bytes:
        path = (self.root / relative).resolve()
        data = path.read_bytes()
        if bytes_hash(data) != expected_sha256:
            raise IntegrityError(f"object digest mismatch: {relative}")
        return data

    def create_round(self, domain: str) -> dict[str, Any]:
        incumbent = self.champion(domain)
        with self.transaction() as connection:
            current = connection.execute(
                "SELECT COALESCE(MAX(round_index),0) AS value FROM rounds WHERE domain=?",
                (domain,),
            ).fetchone()["value"]
            index = int(current) + 1
            run_id = f"{domain}-r{index:04d}"
            now = utc_now()
            connection.execute(
                """INSERT INTO rounds(
                    domain,round_index,run_id,status,incumbent_id,incumbent_structure_sha256,created_at,updated_at
                ) VALUES(?,?,?,?,?,?,?,?)""",
                (
                    domain,
                    index,
                    run_id,
                    RoundStatus.CREATED.value,
                    incumbent["champion_id"],
                    incumbent["structure_sha256"],
                    now,
                    now,
                ),
            )
        return self.round(run_id)

    def round(self, run_id: str) -> dict[str, Any]:
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM rounds WHERE run_id=?", (run_id,)).fetchone()
        if row is None:
            raise LifecycleError(f"round not found: {run_id}")
        return dict(row)

    def latest_round(self, domain: str, *, unfinished_only: bool = False) -> dict[str, Any] | None:
        query = "SELECT * FROM rounds WHERE domain=?"
        params: list[Any] = [domain]
        if unfinished_only:
            terminal = tuple(item.value for item in (RoundStatus.PROMOTED, RoundStatus.REJECTED, RoundStatus.FALSIFIED, RoundStatus.UNRESOLVED))
            query += f" AND status NOT IN ({','.join('?' for _ in terminal)})"
            params.extend(terminal)
        query += " ORDER BY round_index DESC LIMIT 1"
        with self.connect() as connection:
            row = connection.execute(query, tuple(params)).fetchone()
        return dict(row) if row else None

    def transition(self, run_id: str, target: RoundStatus, **updates: Any) -> dict[str, Any]:
        allowed_columns = {
            "proposal_sha256",
            "candidate_structure_sha256",
            "public_receipt_sha256",
            "attribution_receipt_sha256",
            "hidden_receipt_sha256",
            "decision_sha256",
        }
        if set(updates) - allowed_columns:
            raise LifecycleError(f"invalid round update columns: {sorted(set(updates)-allowed_columns)}")
        with self.transaction() as connection:
            row = connection.execute("SELECT * FROM rounds WHERE run_id=?", (run_id,)).fetchone()
            if row is None:
                raise LifecycleError(f"round not found: {run_id}")
            current = RoundStatus(row["status"])
            if target != current and target not in ALLOWED_TRANSITIONS.get(current, set()):
                raise LifecycleError(f"invalid transition: {current.value} -> {target.value}")
            assignments = ["status=?", "updated_at=?"]
            values: list[Any] = [target.value, utc_now()]
            for key, value in updates.items():
                assignments.append(f"{key}=?")
                values.append(value)
            values.append(run_id)
            connection.execute(f"UPDATE rounds SET {','.join(assignments)} WHERE run_id=?", tuple(values))
        return self.round(run_id)

    def append_receipt(self, *, domain: str, run_id: str, kind: str, payload: dict[str, Any]) -> str:
        with self.transaction() as connection:
            previous = connection.execute("SELECT receipt_sha256 FROM receipts ORDER BY sequence DESC LIMIT 1").fetchone()
            previous_digest = previous["receipt_sha256"] if previous else None
            envelope = {
                "schema_version": 1,
                "domain": domain,
                "run_id": run_id,
                "kind": kind,
                "previous_receipt_sha256": previous_digest,
                "created_at": utc_now(),
                "payload": payload,
            }
            digest = bytes_hash(canonical_bytes(envelope))
            relative = f"receipts/sha256/{digest[:2]}/{digest}.json"
            write_immutable(self.root / relative, canonical_bytes(envelope))
            connection.execute(
                "INSERT INTO receipts(receipt_sha256,previous_sha256,domain,run_id,kind,object_path,created_at) VALUES(?,?,?,?,?,?,?)",
                (digest, previous_digest, domain, run_id, kind, relative, envelope["created_at"]),
            )
        return digest

    def add_public_feedback(self, *, domain: str, source_receipt_sha256: str, payload: dict[str, Any]) -> str:
        if payload.get("public_only") is not True:
            raise LifecycleError("only public feedback may enter the architect memory")
        digest, relative = self.put_json_object(payload)
        with self.transaction() as connection:
            connection.execute(
                """INSERT OR IGNORE INTO feedback(
                    feedback_sha256,domain,source_receipt_sha256,public_only,object_path,created_at
                ) VALUES(?,?,?,?,?,?)""",
                (digest, domain, source_receipt_sha256, 1, relative, utc_now()),
            )
        return digest

    def receipts_for_run(self, run_id: str) -> list[dict[str, Any]]:
        with self.connect() as connection:
            return [dict(row) for row in connection.execute(
                "SELECT * FROM receipts WHERE run_id=? ORDER BY sequence", (run_id,)
            )]

    def consume_hidden_selection(
        self,
        *,
        semantic_selection_sha256: str,
        taskset_selection_sha256: str,
        domain: str,
        run_id: str,
    ) -> None:
        with self.transaction() as connection:
            prior = connection.execute(
                """SELECT run_id FROM hidden_consumption
                   WHERE semantic_selection_sha256=? AND domain=? AND split='certification'""",
                (semantic_selection_sha256, domain),
            ).fetchone()
            if prior and prior["run_id"] != run_id:
                raise LifecycleError("semantically identical certification evidence has already been consumed")
            connection.execute(
                """INSERT OR IGNORE INTO hidden_consumption(
                    semantic_selection_sha256,domain,split,run_id,taskset_selection_sha256,consumed_at
                ) VALUES(?,?,'certification',?,?,?)""",
                (semantic_selection_sha256, domain, run_id, taskset_selection_sha256, utc_now()),
            )

    def hidden_selection_owner(self, *, domain: str, semantic_selection_sha256: str) -> str | None:
        with self.connect() as connection:
            row = connection.execute(
                """SELECT run_id FROM hidden_consumption
                   WHERE domain=? AND split='certification' AND semantic_selection_sha256=?""",
                (domain, semantic_selection_sha256),
            ).fetchone()
        return str(row["run_id"]) if row is not None else None

    def consume_taskset(self, *, taskset_sha256: str, domain: str, split: str, run_id: str) -> None:
        """Compatibility wrapper; new callers must pass semantic identities explicitly."""
        if split == "certification":
            self.consume_hidden_selection(
                semantic_selection_sha256=taskset_sha256,
                taskset_selection_sha256=taskset_sha256,
                domain=domain,
                run_id=run_id,
            )
        with self.transaction() as connection:
            connection.execute(
                "INSERT OR IGNORE INTO taskset_consumption VALUES(?,?,?,?,?)",
                (taskset_sha256, domain, split, run_id, utc_now()),
            )

    def promote(
        self,
        *,
        run_id: str,
        new_champion_id: str,
        structure: dict[str, Any],
        artifact: bytes | None,
        certification_receipt_sha256: str,
        decision_sha256: str,
        artifact_scope: str = "domain_lineage",
        artifact_lineage_id: str = "default",
        deployment_source: str = "public-selection",
    ) -> dict[str, Any]:
        round_record = self.round(run_id)
        if RoundStatus(round_record["status"]) != RoundStatus.CERTIFIED:
            raise LifecycleError("only a certified round can promote")
        domain = round_record["domain"]
        incumbent = self.champion(domain)
        if incumbent["structure_sha256"] != round_record["incumbent_structure_sha256"]:
            raise LifecycleError("champion changed since the round started")
        if artifact_scope not in {"domain_lineage", "task_local"}:
            raise LifecycleError(f"invalid artifact scope: {artifact_scope}")
        structure_digest, structure_object = self.put_json_object(structure)
        if artifact_scope == "task_local":
            artifact_digest = str(incumbent["artifact_sha256"])
            artifact_object = str(incumbent["artifact_object"])
            champion_lineage_id: str | None = None
        else:
            if artifact is None:
                raise LifecycleError("domain-lineage promotion requires a public-selected artifact")
            artifact_digest, artifact_object = self.put_object(artifact, suffix="artifact")
            champion_lineage_id = artifact_lineage_id
        with self.transaction() as connection:
            connection.execute(
                "UPDATE champions SET status='superseded' WHERE domain=? AND status='active'",
                (domain,),
            )
            source = {
                "run_id": run_id,
                "decision_sha256": decision_sha256,
                "artifact_scope": artifact_scope,
                "deployment_source": deployment_source,
            }
            connection.execute(
                """INSERT INTO champions(
                    domain,champion_id,status,structure_sha256,artifact_sha256,
                    structure_object,artifact_object,certification_receipt_sha256,source_json,created_at,
                    artifact_scope,artifact_lineage_id
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    domain,
                    new_champion_id,
                    "active",
                    structure_digest,
                    artifact_digest,
                    structure_object,
                    artifact_object,
                    certification_receipt_sha256,
                    json.dumps(source, sort_keys=True),
                    utc_now(),
                    artifact_scope,
                    champion_lineage_id,
                ),
            )
            if artifact_scope == "domain_lineage":
                connection.execute(
                    "UPDATE artifact_versions SET status='superseded' WHERE domain=? AND lineage_id=? AND status='active'",
                    (domain, artifact_lineage_id),
                )
                connection.execute(
                    """INSERT INTO artifact_versions(
                        domain,lineage_id,artifact_id,status,task_fingerprint,artifact_sha256,
                        artifact_object,source_json,created_at
                    ) VALUES(?,?,?,?,?,?,?,?,?)""",
                    (
                        domain,
                        artifact_lineage_id,
                        new_champion_id,
                        "active",
                        None,
                        artifact_digest,
                        artifact_object,
                        json.dumps(source, sort_keys=True),
                        utc_now(),
                    ),
                )
            connection.execute(
                "UPDATE rounds SET status=?,decision_sha256=?,updated_at=? WHERE run_id=?",
                (RoundStatus.PROMOTED.value, decision_sha256, utc_now(), run_id),
            )
        record = self.champion(domain)
        self._write_pointer(record)
        return record

    def _write_pointer(self, record: dict[str, Any]) -> None:
        pointer = {
            "schema_version": 1,
            "domain": record["domain"],
            "champion_id": record["champion_id"],
            "structure_sha256": record["structure_sha256"],
            "artifact_sha256": record["artifact_sha256"],
            "certification_receipt_sha256": record["certification_receipt_sha256"],
            "artifact_scope": record.get("artifact_scope", "domain_lineage"),
            "artifact_lineage_id": record.get("artifact_lineage_id"),
            "updated_at": utc_now(),
        }
        atomic_json(self.pointers / record["domain"] / "active.json", pointer)

    def audit(self) -> list[str]:
        checks: list[str] = []
        with self.connect() as connection:
            domains = [row["domain"] for row in connection.execute(
                "SELECT DISTINCT domain FROM champions ORDER BY domain"
            )]
            for domain in domains:
                count = connection.execute(
                    "SELECT COUNT(*) AS value FROM champions WHERE domain=? AND status='active'",
                    (domain,),
                ).fetchone()["value"]
                if count > 1:
                    raise IntegrityError(f"multiple active champions: {domain}")
            receipts = list(connection.execute("SELECT * FROM receipts ORDER BY sequence"))
        previous = None
        for row in receipts:
            if row["previous_sha256"] != previous:
                raise IntegrityError("receipt chain is broken")
            path = self.root / row["object_path"]
            if bytes_hash(path.read_bytes()) != row["receipt_sha256"]:
                raise IntegrityError(f"receipt object mismatch: {row['receipt_sha256']}")
            previous = row["receipt_sha256"]
        checks.append(f"receipt-chain:{len(receipts)}")
        for row in self.list_champions():
            self.object_bytes(row["structure_object"], row["structure_sha256"])
            self.object_bytes(row["artifact_object"], row["artifact_sha256"])
        checks.append("champion-objects")
        with self.connect() as connection:
            artifact_rows = list(connection.execute(
                "SELECT artifact_object,artifact_sha256 FROM artifact_versions"
            ))
        for row in artifact_rows:
            self.object_bytes(row["artifact_object"], row["artifact_sha256"])
        checks.append(f"artifact-lineages:{len(artifact_rows)}")
        return checks
