"""Postgres storage for company skills served by the gateway.

The catalog lives in the `company_skills` table so skills can be published and
updated at runtime (no image rebuild). Reads back dict rows.
"""

import json
from typing import Any

from gateway_mcp.services.storage_core import _connect, ensure_schema, postgres_enabled

_SUMMARY_COLS = "name, pack, department, title, description"
_FULL_COLS = "name, pack, department, title, description, content"

TELEMETRY_MARKER = "<!-- gateway-skill-telemetry:v1 -->"
TELEMETRY_BLOCK = TELEMETRY_MARKER + """
## Телеметрия

Считай содержательным запуском случай, когда этот skill выбран для выполнения задачи, а не только открыт как справка.

- Если GatewayMCP предоставляет инструменты телеметрии, в начале вызови `gateway_telemetry_skill_started`. Передай фактический `agent`, имя каталога как `skill_id`, известные `skill_pack`, `skill_version`, `project` и безопасный идентификатор клиента. Неизвестные значения оставь пустыми.
- Сохрани `correlation_id` из ответа. При успехе вызови `gateway_telemetry_skill_completed` с тем же `correlation_id`, длительностью, использованными MCP-маршрутами и недостающими scope.
- При ошибке после успешного события `started` вызови `gateway_telemetry_skill_failed` с тем же `correlation_id` и только классом ошибки в `error_class`.
- В `metadata_json` передавай только безопасные признаки: тип операции, итоговый статус и числовые счётчики. Не передавай промпты, документы, тексты сообщений и ответов, персональные, клиентские, кадровые или финансовые данные, токены, cookies, ключи, пароли и stack trace.
- Недоступность телеметрии не должна блокировать основную работу. Не повторяй неуспешную телеметрическую запись больше одного раза.
"""


def with_telemetry(content: str) -> str:
    """Добавляет блок телеметрии в конец навыка, если его там ещё нет.

    Без этого блока ассистент не отмечает запуски, и навык не виден в метриках.
    """
    text = content or ""
    if not text.strip() or TELEMETRY_MARKER in text:
        return text
    return text.rstrip() + "\n\n" + TELEMETRY_BLOCK


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
            (name, pack, department, title, description, with_telemetry(content), updated_by),
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


# --- Агенты компании (именованные наборы навыков) ---

def list_agents() -> list[dict[str, Any]]:
    ensure_schema()
    with _connect() as conn, conn.cursor() as cur:
        cur.execute("select slug, title, description, department, skills from company_agents order by slug")
        return [dict(r) for r in cur.fetchall()]


def get_agent(slug: str) -> dict[str, Any] | None:
    ensure_schema()
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(
            "select slug, title, description, department, skills, updated_by, updated_at "
            "from company_agents where lower(slug) = lower(%s)",
            (slug,),
        )
        row = cur.fetchone()
        return dict(row) if row else None


def upsert_agent(
    *,
    slug: str,
    title: str,
    description: str,
    department: str,
    skills: list[str],
    updated_by: str,
) -> dict[str, Any]:
    ensure_schema()
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            insert into company_agents
                (slug, title, description, department, skills, updated_by, updated_at)
            values (%s, %s, %s, %s, %s::jsonb, %s, now())
            on conflict (slug) do update set
                title = excluded.title,
                description = excluded.description,
                department = excluded.department,
                skills = excluded.skills,
                updated_by = excluded.updated_by,
                updated_at = now()
            returning slug, title, description, department, skills, updated_by, updated_at
            """,
            (slug, title, description, department, json.dumps(list(skills or []), ensure_ascii=False), updated_by),
        )
        return dict(cur.fetchone())


def delete_agent(slug: str) -> bool:
    ensure_schema()
    with _connect() as conn, conn.cursor() as cur:
        cur.execute("delete from company_agents where lower(slug) = lower(%s)", (slug,))
        return cur.rowcount > 0
