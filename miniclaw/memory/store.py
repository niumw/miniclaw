"""记忆存储 — SQLite 持久化，DIKW 分层"""

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Memory:
    """单条记忆"""
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    content: str = ""
    summary: str = ""
    memory_type: str = "knowledge"       # knowledge / event / skill / preference / lesson
    dikw_level: str = "information"       # data / information / knowledge / wisdom
    importance: float = 0.5
    status: str = "unverified"            # unverified / verified / needs_review
    verify_count: int = 0
    apply_count: int = 0
    fail_count: int = 0
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    last_accessed: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    access_count: int = 0
    tags: list[str] = field(default_factory=list)
    entities: list[str] = field(default_factory=list)
    superseded_by: Optional[str] = None
    retrieval_suppressed: int = 0        # 0=正常, 1=主动抑制(软遗忘)


SCHEMA = """
CREATE TABLE IF NOT EXISTS memories (
    id TEXT PRIMARY KEY,
    content TEXT NOT NULL,
    summary TEXT NOT NULL,
    memory_type TEXT NOT NULL DEFAULT 'knowledge',
    dikw_level TEXT NOT NULL DEFAULT 'information',
    importance REAL DEFAULT 0.5,
    status TEXT NOT NULL DEFAULT 'unverified',
    verify_count INTEGER DEFAULT 0,
    apply_count INTEGER DEFAULT 0,
    fail_count INTEGER DEFAULT 0,
    created_at TEXT NOT NULL,
    last_accessed TEXT NOT NULL,
    access_count INTEGER DEFAULT 0,
    tags TEXT DEFAULT '[]',
    entities TEXT DEFAULT '[]',
    superseded_by TEXT,
    retrieval_suppressed INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS memory_relations (
    from_id TEXT NOT NULL,
    to_id TEXT NOT NULL,
    relation_type TEXT NOT NULL,
    strength REAL DEFAULT 0.5,
    auto_generated INTEGER DEFAULT 1,
    PRIMARY KEY (from_id, to_id, relation_type)
);

CREATE TABLE IF NOT EXISTS rules (
    id TEXT PRIMARY KEY,
    pattern TEXT NOT NULL,
    action TEXT NOT NULL,
    response TEXT,
    source_memory_id TEXT,
    trigger_count INTEGER DEFAULT 0,
    success_count INTEGER DEFAULT 0,
    created_at TEXT NOT NULL,
    status TEXT DEFAULT 'active'
);

CREATE INDEX IF NOT EXISTS idx_memories_dikw ON memories(dikw_level, status);
CREATE INDEX IF NOT EXISTS idx_memories_type ON memories(memory_type);
CREATE INDEX IF NOT EXISTS idx_memories_importance ON memories(importance DESC);
CREATE INDEX IF NOT EXISTS idx_memories_last_accessed ON memories(last_accessed);
CREATE INDEX IF NOT EXISTS idx_memories_suppressed ON memories(retrieval_suppressed);
CREATE INDEX IF NOT EXISTS idx_relations_from ON memory_relations(from_id);
CREATE INDEX IF NOT EXISTS idx_relations_to ON memory_relations(to_id);
CREATE INDEX IF NOT EXISTS idx_rules_pattern ON rules(pattern);
"""


class MemoryStore:
    """SQLite 记忆存储"""

    def __init__(self, db_path: str = "data/miniclaw.db"):
        self.db_path = db_path
        self._conn: Optional[sqlite3.Connection] = None

    def _connect(self) -> sqlite3.Connection:
        if self._conn is None:
            import os
            os.makedirs(os.path.dirname(self.db_path) or ".", exist_ok=True)
            self._conn = sqlite3.connect(self.db_path)
            self._conn.row_factory = sqlite3.Row
            # 确保 SQLite 字符串处理兼容 UTF-8
            self._conn.execute("PRAGMA encoding = 'UTF-8'")
            self._conn.executescript(SCHEMA)
        return self._conn

    def save(self, memory: Memory) -> str:
        conn = self._connect()
        conn.execute(
            """INSERT OR REPLACE INTO memories
               (id, content, summary, memory_type, dikw_level, importance,
                status, verify_count, apply_count, fail_count,
                created_at, last_accessed, access_count, tags, entities,
                superseded_by, retrieval_suppressed)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                memory.id, memory.content, memory.summary,
                memory.memory_type, memory.dikw_level, memory.importance,
                memory.status, memory.verify_count, memory.apply_count, memory.fail_count,
                memory.created_at, memory.last_accessed, memory.access_count,
                json.dumps(memory.tags, ensure_ascii=False),
                json.dumps(memory.entities, ensure_ascii=False),
                memory.superseded_by, memory.retrieval_suppressed,
            ),
        )
        conn.commit()
        return memory.id

    def get(self, memory_id: str) -> Optional[Memory]:
        conn = self._connect()
        row = conn.execute("SELECT * FROM memories WHERE id = ?", (memory_id,)).fetchone()
        return self._row_to_memory(row) if row else None

    def search(
        self,
        query: str = "",
        tags: list[str] | None = None,
        memory_type: str | None = None,
        dikw_level: str | None = None,
        limit: int = 10,
        include_suppressed: bool = False,
    ) -> list[Memory]:
        conn = self._connect()
        conditions = []
        params: list = []

        if query:
            conditions.append("(content LIKE ? OR summary LIKE ? OR entities LIKE ?)")
            like = f"%{query}%"
            params.extend([like, like, like])

        if tags:
            tag_conds = ["tags LIKE ?" for _ in tags]
            params.extend(f'%"{t}"%' for t in tags)
            conditions.append(f"({' OR '.join(tag_conds)})")

        if memory_type:
            conditions.append("memory_type = ?")
            params.append(memory_type)

        if dikw_level:
            conditions.append("dikw_level = ?")
            params.append(dikw_level)

        conditions.append("superseded_by IS NULL")

        if not include_suppressed:
            conditions.append("retrieval_suppressed = 0")

        where = " AND ".join(conditions)
        params.append(limit)

        rows = conn.execute(
            f"""SELECT * FROM memories WHERE {where}
                ORDER BY
                    CASE dikw_level
                        WHEN 'wisdom' THEN 4
                        WHEN 'knowledge' THEN 3
                        WHEN 'information' THEN 2
                        WHEN 'data' THEN 1
                        ELSE 2
                    END DESC,
                    importance DESC, last_accessed DESC LIMIT ?""",
            params,
        ).fetchall()

        return [self._row_to_memory(row) for row in rows]

    def update(self, memory_id: str, **kwargs):
        """更新记忆的部分字段"""
        conn = self._connect()
        sets = []
        vals = []
        for k, v in kwargs.items():
            if k in ("tags", "entities"):
                v = json.dumps(v, ensure_ascii=False)
            sets.append(f"{k} = ?")
            vals.append(v)
        vals.append(memory_id)
        conn.execute(f"UPDATE memories SET {', '.join(sets)} WHERE id = ?", vals)
        conn.commit()

    def touch(self, memory_id: str):
        conn = self._connect()
        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            "UPDATE memories SET last_accessed = ?, access_count = access_count + 1 WHERE id = ?",
            (now, memory_id),
        )
        conn.commit()

    def supersede(self, old_id: str, new_id: str):
        conn = self._connect()
        conn.execute("UPDATE memories SET superseded_by = ? WHERE id = ?", (new_id, old_id))
        conn.commit()

    def count(self, active_only: bool = True) -> int:
        conn = self._connect()
        if active_only:
            row = conn.execute("SELECT COUNT(*) FROM memories WHERE superseded_by IS NULL AND retrieval_suppressed = 0").fetchone()
        else:
            row = conn.execute("SELECT COUNT(*) FROM memories").fetchone()
        return row[0]

    def list_all(self, limit: int = 50) -> list[Memory]:
        conn = self._connect()
        rows = conn.execute(
            """SELECT * FROM memories WHERE superseded_by IS NULL
               ORDER BY importance DESC, created_at DESC LIMIT ?""",
            (limit,),
        ).fetchall()
        return [self._row_to_memory(row) for row in rows]

    # ── 关联关系 ──

    def add_relation(self, from_id: str, to_id: str, relation_type: str, strength: float = 0.5, auto: bool = True):
        conn = self._connect()
        conn.execute(
            """INSERT OR REPLACE INTO memory_relations (from_id, to_id, relation_type, strength, auto_generated)
               VALUES (?, ?, ?, ?, ?)""",
            (from_id, to_id, relation_type, strength, 1 if auto else 0),
        )
        conn.commit()

    def get_relations(self, memory_id: str, relation_type: str | None = None) -> list[dict]:
        conn = self._connect()
        if relation_type:
            rows = conn.execute(
                "SELECT * FROM memory_relations WHERE from_id = ? AND relation_type = ?",
                (memory_id, relation_type),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM memory_relations WHERE from_id = ?",
                (memory_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    def get_related_memories(self, memory_id: str, relation_type: str | None = None) -> list[Memory]:
        """获取关联的记忆对象"""
        relations = self.get_relations(memory_id, relation_type)
        results = []
        for rel in relations:
            mem = self.get(rel["to_id"])
            if mem and mem.superseded_by is None:
                results.append(mem)
        return results

    # ── 规则 ──

    def save_rule(self, rule_id: str, pattern: str, action: str, response: str, source_memory_id: str | None = None):
        conn = self._connect()
        conn.execute(
            """INSERT OR REPLACE INTO rules (id, pattern, action, response, source_memory_id, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (rule_id, pattern, action, response, source_memory_id, datetime.now(timezone.utc).isoformat()),
        )
        conn.commit()

    def match_rule(self, text: str) -> list[dict]:
        """匹配反射规则"""
        conn = self._connect()
        rows = conn.execute("SELECT * FROM rules WHERE status = 'active'").fetchall()
        matched = []
        for row in rows:
            pattern = row["pattern"]
            # 关键词匹配：每个关键词必须是独立词（边界检查）
            keywords = [k.strip() for k in pattern.split(",")]
            if any(self._keyword_match(k, text) for k in keywords):
                matched.append(dict(row))
        return matched

    @staticmethod
    def _keyword_match(keyword: str, text: str) -> bool:
        """关键词匹配：中文用包含，英文用词边界"""
        import re
        kw = keyword.strip()
        if not kw:
            return False
        # 中文关键词：直接包含匹配
        if any('\u4e00' <= c <= '\u9fff' for c in kw):
            return kw in text
        # 英文关键词：词边界匹配
        try:
            return bool(re.search(r'\b' + re.escape(kw) + r'\b', text, re.IGNORECASE))
        except re.error:
            return kw in text

    def _row_to_memory(self, row: sqlite3.Row) -> Memory:
        return Memory(
            id=row["id"],
            content=row["content"],
            summary=row["summary"],
            memory_type=row["memory_type"],
            dikw_level=row["dikw_level"],
            importance=row["importance"],
            status=row["status"],
            verify_count=row["verify_count"],
            apply_count=row["apply_count"],
            fail_count=row["fail_count"],
            created_at=row["created_at"],
            last_accessed=row["last_accessed"],
            access_count=row["access_count"],
            tags=json.loads(row["tags"]),
            entities=json.loads(row["entities"]),
            superseded_by=row["superseded_by"],
            retrieval_suppressed=row["retrieval_suppressed"],
        )
