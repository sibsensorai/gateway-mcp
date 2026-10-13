"""Company skills served straight from the gateway.

Lets any connected agent discover and load the company's shared skills from the
core itself — no plugin marketplace install.

The catalog lives in the `company_skills` Postgres table (published and updated
at runtime). On first use it is seeded from the baked JSON file
(GATEWAY_COMPANY_SKILLS_FILE, default company-skills.json). If the database is
unavailable, reads fall back to that JSON file.

Read tools need `skills:read` (every employee has it). Publishing needs
`skills:admin` (only admins, via the `*` wildcard).
"""

import json
import re

from mcp.types import ToolAnnotations

from gateway_mcp.config import read_json, resolve_configured_path
from gateway_mcp.services import storage_skills
from gateway_mcp.tools.runtime import ToolRun


def _skills_file():
    return resolve_configured_path("GATEWAY_COMPANY_SKILLS_FILE", "company-skills.json")


def _json_catalog() -> list[dict]:
    data = read_json(_skills_file(), {"skills": []})
    skills = data.get("skills", [])
    return skills if isinstance(skills, list) else []


def _summary(skill: dict) -> dict:
    return {
        "name": skill.get("name", ""),
        "pack": skill.get("pack", ""),
        "department": skill.get("department", ""),
        "title": skill.get("title", ""),
        "description": skill.get("description", ""),
    }


def _ensure_seeded() -> None:
    try:
        storage_skills.seed_if_empty(_json_catalog())
    except Exception:
        pass


def _db_summaries() -> list[dict] | None:
    if not storage_skills.postgres_enabled():
        return None
    try:
        _ensure_seeded()
        return storage_skills.list_skills()
    except Exception:
        return None


def _db_get(name: str) -> dict | None:
    if not storage_skills.postgres_enabled():
        return None
    try:
        _ensure_seeded()
        return storage_skills.get_skill(name)
    except Exception:
        return None


def skill_summaries() -> list[dict]:
    """Public light catalog (no content): database first, JSON fallback."""
    db = _db_summaries()
    if db is not None:
        return db
    return [_summary(s) for s in _json_catalog()]


SKILLS_HINT = (
    "Навыки компании доступны прямо из ядра. Если задача подходит под навык из списка — "
    "загрузи его инструкции через gateway_company_skill_get(name) и следуй им, прежде чем действовать."
)


def _match(summaries: list[dict], query: str) -> list[dict]:
    tokens = [t for t in re.split(r"\s+", query.casefold().strip()) if t]
    if not tokens:
        return list(summaries)
    out = []
    for s in summaries:
        haystack = json.dumps(s, ensure_ascii=False).casefold()
        if all(token in haystack for token in tokens):
            out.append(s)
    return out


def register_skill_tools(mcp):
    @mcp.tool(annotations=ToolAnnotations(title="Gateway Company Skills List", readOnlyHint=True))
    async def gateway_company_skills_list(query: str = "") -> str:
        """Навыки компании, доступные прямо из ядра. ВАЖНО: в начале рабочей задачи вызови это ПЕРВЫМ — проверь, есть ли подходящий утверждённый навык компании; если есть, загрузи его через gateway_company_skill_get и следуй его шагам, прежде чем отвечать. Необязательный query фильтрует по тексту."""
        tool = "gateway_company_skills_list"
        scope = "skills:read"
        run = ToolRun.start(tool=tool, system="gateway", scope=scope, arguments={"query": query})
        try:
            run.require_scope()
            skills = _match(skill_summaries(), query)
            run.finish()
            return json.dumps({"ok": True, "count": len(skills), "skills": skills}, ensure_ascii=False, indent=2)
        except PermissionError as exc:
            run.denied(exc)
            raise
        except Exception as exc:
            run.error(exc)
            raise

    @mcp.tool(annotations=ToolAnnotations(title="Gateway Company Skill Get", readOnlyHint=True))
    async def gateway_company_skill_get(name: str) -> str:
        """Загрузи полные инструкции (SKILL.md) навыка компании по имени и СЛЕДУЙ им для задачи. Используй вместе с gateway_company_skills_list, чтобы применять утверждённый в компании способ работы."""
        tool = "gateway_company_skill_get"
        scope = "skills:read"
        run = ToolRun.start(tool=tool, system="gateway", scope=scope, arguments={"name": name})
        try:
            run.require_scope()
            match = _db_get(name)
            if match is None:
                wanted = (name or "").strip().casefold()
                match = next((s for s in _json_catalog() if s.get("name", "").casefold() == wanted), None)
            if match is None:
                run.finish()
                return json.dumps({"ok": False, "error": "skill not found", "name": name}, ensure_ascii=False, indent=2)
            run.finish()
            return json.dumps(
                {
                    "ok": True,
                    "skill": {
                        "name": match.get("name", ""),
                        "pack": match.get("pack", ""),
                        "department": match.get("department", ""),
                        "title": match.get("title", ""),
                        "description": match.get("description", ""),
                        "content": match.get("content", ""),
                    },
                },
                ensure_ascii=False,
                indent=2,
            )
        except PermissionError as exc:
            run.denied(exc)
            raise
        except Exception as exc:
            run.error(exc)
            raise

    @mcp.tool(annotations=ToolAnnotations(title="Gateway Company Skill Publish", readOnlyHint=False))
    async def gateway_company_skill_put(
        name: str,
        content: str,
        pack: str = "",
        department: str = "",
        title: str = "",
        description: str = "",
    ) -> str:
        """Опубликовать или обновить навык компании прямо в ядре (для кураторов/админов). После вызова навык сразу доступен всем подключённым агентам — без магазина и пересборки. `content` — полный текст SKILL.md. Требует права skills:admin."""
        tool = "gateway_company_skill_put"
        scope = "skills:admin"
        run = ToolRun.start(tool=tool, system="gateway", scope=scope, arguments={"name": name, "pack": pack})
        try:
            actor = run.require_scope()
            if not storage_skills.postgres_enabled():
                run.finish()
                return json.dumps({"ok": False, "error": "database not available"}, ensure_ascii=False, indent=2)
            if not (name or "").strip() or not (content or "").strip():
                run.finish()
                return json.dumps({"ok": False, "error": "name and content are required"}, ensure_ascii=False, indent=2)
            who = getattr(actor, "email", "") or getattr(actor, "subject", "") or ""
            saved = storage_skills.upsert_skill(
                name=name.strip(),
                pack=pack,
                department=department,
                title=title or name.strip(),
                description=description,
                content=content,
                updated_by=who,
            )
            run.finish()
            return json.dumps({"ok": True, "saved": saved}, ensure_ascii=False, indent=2, default=str)
        except PermissionError as exc:
            run.denied(exc)
            raise
        except Exception as exc:
            run.error(exc)
            raise

    @mcp.tool(annotations=ToolAnnotations(title="Gateway Company Skill Delete", readOnlyHint=False))
    async def gateway_company_skill_delete(name: str) -> str:
        """Убрать навык компании из ядра по имени (для кураторов/админов). Требует права skills:admin."""
        tool = "gateway_company_skill_delete"
        scope = "skills:admin"
        run = ToolRun.start(tool=tool, system="gateway", scope=scope, arguments={"name": name})
        try:
            run.require_scope()
            if not storage_skills.postgres_enabled():
                run.finish()
                return json.dumps({"ok": False, "error": "database not available"}, ensure_ascii=False, indent=2)
            removed = storage_skills.delete_skill((name or "").strip())
            run.finish()
            return json.dumps({"ok": True, "removed": removed, "name": name}, ensure_ascii=False, indent=2)
        except PermissionError as exc:
            run.denied(exc)
            raise
        except Exception as exc:
            run.error(exc)
            raise
