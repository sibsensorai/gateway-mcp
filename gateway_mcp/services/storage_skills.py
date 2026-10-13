"""Postgres storage for company skills served by the gateway.

The catalog lives in the `company_skills` table so skills can be published and
updated at runtime (no image rebuild). Reads back dict rows.
"""

from typing import Any

from gateway_mcp.services.storage_core import _connect, ensure_schema, postgres_enabled

_SUMMARY_COLS = "name, pack, department, title, description"
_FULL_COLS = "name, pack, department, title, description, content"


def count_skills() -> int:
    ensure_schema()
    with _connect() as conn, conn.cursor() as cur:
        cur.execute("select count(*) as n from company_skills")
        row = cur.fetchone() or {}
        return int(row.get("n", 0))


def list_skills() -> list[dict[str, Any]]:
    ensure_schema()
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(f"select {_SUMMARY_COLS} from company_skills order by pack, name")
        return [dict(r) for r in cur.fetchall()]


def get_skill(name: str) -> dict[str, Any] | None:
    ensure_schema()
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(
            f"select {_FULL_COLS} from company_skills where lower(name) = lower(%s)",
            (name,),
        )
        row = cur.fetchone()
        return dict(row) if row else None


def upsert_skill(
    *,
    name: str,
    pack: str,
    department: str,
    title: str,
    description: str,
    content: str,
    updated_by: str,
) -> dict[str, Any]:
    ensure_schema()
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            insert into company_skills
                (name, pack, department, title, description, content, updated_by, updated_at)
            values (%s, %s, %s, %s, %s, %s, %s, now())
            on conflict (name) do update set
                pack = excluded.pack,
                department = excluded.department,
                title = excluded.title,
                description = excluded.description,
                content = excluded.content,
                updated_by = excluded.updated_by,
                updated_at = now()
            returning name, pack, department, title, description, updated_by, updated_at
            """,
            (name, pack, department, title, description, content, updated_by),
        )
        return dict(cur.fetchone())


def delete_skill(name: str) -> bool:
    ensure_schema()
    with _connect() as conn, conn.cursor() as cur:
        cur.execute("delete from company_skills where lower(name) = lower(%s)", (name,))
        return cur.rowcount > 0


def seed_if_empty(skills: list[dict[str, Any]], updated_by: str = "seed") -> int:
    """Populate the table from a baked catalog once, if it is still empty."""
    if not skills or count_skills() > 0:
        return 0
    inserted = 0
    with _connect() as conn, conn.cursor() as cur:
        for s in skills:
            cur.execute(
                """
                insert into company_skills
                    (name, pack, department, title, description, content, updated_by)
                values (%s, %s, %s, %s, %s, %s, %s)
                on conflict (name) do nothing
                """,
                (
                    s.get("name", ""),
                    s.get("pack", ""),
                    s.get("department", ""),
                    s.get("title", ""),
                    s.get("description", ""),
                    s.get("content", ""),
                    updated_by,
                ),
            )
            inserted += 1
    return inserted
