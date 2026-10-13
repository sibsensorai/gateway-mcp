"""Company skills served straight from the gateway.

Lets any connected agent discover and load the company's shared skills from the
core itself — no plugin marketplace install. The catalog lives in a JSON file
(GATEWAY_COMPANY_SKILLS_FILE, default company-skills.json) with, per skill:
name, pack, department, title, description and the full SKILL.md `content`.
Both tools need the read-only `skills:read` scope (every employee has it).
"""

import json
import re

from mcp.types import ToolAnnotations

from gateway_mcp.config import read_json, resolve_configured_path
from gateway_mcp.tools.runtime import ToolRun


def _skills_file():
    return resolve_configured_path("GATEWAY_COMPANY_SKILLS_FILE", "company-skills.json")


def _catalog() -> list[dict]:
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


def _match(skills: list[dict], query: str) -> list[dict]:
    tokens = [t for t in re.split(r"\s+", query.casefold().strip()) if t]
    if not tokens:
        return list(skills)
    out = []
    for skill in skills:
        haystack = json.dumps(_summary(skill), ensure_ascii=False).casefold()
        if all(token in haystack for token in tokens):
            out.append(skill)
    return out


def skill_summaries() -> list[dict]:
    """Public: light catalog (no content) for bootstrap context and discovery."""
    return [_summary(s) for s in _catalog()]


SKILLS_HINT = (
    "Навыки компании доступны прямо из ядра. Если задача подходит под навык из списка — "
    "загрузи его инструкции через gateway_company_skill_get(name) и следуй им, прежде чем действовать."
)


def register_skill_tools(mcp):
    @mcp.tool(annotations=ToolAnnotations(title="Gateway Company Skills List", readOnlyHint=True))
    async def gateway_company_skills_list(query: str = "") -> str:
        """Навыки компании, доступные прямо из ядра. ВАЖНО: в начале рабочей задачи вызови это ПЕРВЫМ — проверь, есть ли подходящий утверждённый навык компании; если есть, загрузи его через gateway_company_skill_get и следуй его шагам, прежде чем отвечать. Необязательный query фильтрует по тексту."""
        tool = "gateway_company_skills_list"
        scope = "skills:read"
        run = ToolRun.start(tool=tool, system="gateway", scope=scope, arguments={"query": query})
        try:
            run.require_scope()
            skills = _match(_catalog(), query)
            run.finish()
            return json.dumps(
                {"ok": True, "count": len(skills), "skills": [_summary(s) for s in skills]},
                ensure_ascii=False,
                indent=2,
            )
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
            wanted = (name or "").strip().casefold()
            match = next((s for s in _catalog() if s.get("name", "").casefold() == wanted), None)
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
