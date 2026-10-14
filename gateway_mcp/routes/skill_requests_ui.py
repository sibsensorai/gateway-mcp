"""Web page for owners to review and decide skill/agent proposals (заявки на навыки)."""

from __future__ import annotations

from asyncio import to_thread as run_in_threadpool
from html import escape

from starlette.responses import RedirectResponse

from gateway_mcp.routes.admin_access import _guard, _page
from gateway_mcp.routes.admin_ui import fmt_time
from gateway_mcp.services.admin_roles import require_current_admin
from gateway_mcp.services.approvals import decide_approval, list_visible_approvals

SKILL_TYPES = ("skill_proposal", "skill_publish", "agent_proposal", "agent_publish")

_CSS = """
<style>
.sr-wrap{display:flex;flex-direction:column;gap:18px;max-width:900px}
.sr-card{background:#fff;border:1px solid #e3e6ef;border-radius:14px;padding:20px 22px;box-shadow:0 1px 2px rgba(13,27,76,.04)}
.sr-head{display:flex;justify-content:space-between;align-items:center;gap:12px;margin-bottom:6px}
.sr-kind{font-size:12px;letter-spacing:.04em;text-transform:uppercase;color:#2b6cff;background:#eef3ff;border-radius:999px;padding:3px 10px}
.sr-dept{font-size:13px;color:#5b6172}
.sr-card h3{margin:2px 0 6px;font-size:20px;color:#0d1b4c}
.sr-what{margin:0 0 10px;color:#4a5568;font-size:15px}
.sr-card ul.skills{margin:6px 0 10px;padding-left:18px}
.sr-card ul.skills li{margin-bottom:6px;font-size:14px}
.sr-card details{margin:6px 0}
.sr-card summary{cursor:pointer;color:#2b6cff;font-size:13px}
.sr-card pre{background:#f5f7fb;border:1px solid #e3e6ef;border-radius:8px;padding:12px;overflow:auto;font-size:12.5px;max-height:360px;white-space:pre-wrap}
.sr-meta{font-size:12.5px;color:#8a93a6;margin:8px 0 12px}
.sr-actions{display:flex;gap:10px}
.sr-actions button{border:none;border-radius:9px;padding:9px 18px;font-size:14px;font-weight:600;cursor:pointer}
.sr-actions .approve{background:#1f9d6b;color:#fff}
.sr-actions .reject{background:#fff;color:#d64545;border:1px solid #f0c9c9}
.sr-empty{background:#fff;border:1px solid #e3e6ef;border-radius:14px;padding:28px;text-align:center;color:#5b6172}
</style>
"""


def _skill_block(skill: dict) -> str:
    name = escape(str(skill.get("skill_name") or skill.get("skill") or ""))
    desc = escape(str(skill.get("summary") or skill.get("description") or ""))
    files = skill.get("files") if isinstance(skill.get("files"), dict) else {}
    content = escape(str(skill.get("skill_md") or files.get("SKILL.md") or ""))
    details = f"<details><summary>открыть файл</summary><pre>{content}</pre></details>" if content else ""
    return f"<li><b>{name}</b> — {desc}{details}</li>"


def _card(appr: dict) -> str:
    atype = str(appr.get("approval_type") or "")
    payload = appr.get("payload") if isinstance(appr.get("payload"), dict) else {}
    aid = escape(str(appr.get("approval_id") or ""))
    is_agent = atype in ("agent_proposal", "agent_publish")

    if is_agent:
        agent = payload.get("agent") if isinstance(payload.get("agent"), dict) else {}
        name = escape(str(agent.get("title") or agent.get("slug") or appr.get("subject") or ""))
        what = escape(str(agent.get("description") or payload.get("summary") or ""))
        dept = escape(str(agent.get("department") or payload.get("department") or ""))
        kind = "Агент · набор навыков"
        skills = payload.get("skills") if isinstance(payload.get("skills"), list) else []
        items = "".join(_skill_block(s if isinstance(s, dict) else {}) for s in skills)
        extra = f'<p class="sr-what">Навыки ({len(skills)}):</p><ul class="skills">{items}</ul>'
    else:
        name = escape(str(payload.get("skill_name") or payload.get("skill") or appr.get("subject") or ""))
        what = escape(str(payload.get("summary") or payload.get("description") or ""))
        dept = escape(str(payload.get("department") or ""))
        kind = "Навык"
        files = payload.get("files") if isinstance(payload.get("files"), dict) else {}
        content = escape(str(payload.get("skill_md") or files.get("SKILL.md") or ""))
        extra = f"<details><summary>открыть полный файл</summary><pre>{content}</pre></details>" if content else ""

    by = escape(str(appr.get("created_by") or ""))
    created = escape(fmt_time(appr.get("created_at")))
    form = (
        '<form method="post" action="/admin/skill-requests/decide" class="sr-actions">'
        f'<input type="hidden" name="approval_id" value="{aid}">'
        '<button class="approve" name="decision" value="approved">✓ Одобрить</button>'
        '<button class="reject" name="decision" value="rejected">✕ Отклонить</button>'
        "</form>"
    )
    dept_html = f'<span class="sr-dept">{dept}</span>' if dept else "<span></span>"
    return (
        '<article class="sr-card">'
        f'<div class="sr-head"><span class="sr-kind">{kind}</span>{dept_html}</div>'
        f"<h3>{name}</h3>"
        f'<p class="sr-what">{what}</p>'
        f"{extra}"
        f'<div class="sr-meta">от {by} · {created}</div>'
        f"{form}"
        "</article>"
    )


def register_skill_requests_routes(mcp):
    @mcp.custom_route("/admin/skill-requests", methods=["GET"], include_in_schema=False)
    @_guard
    async def skill_requests_page(request, actor):
        await run_in_threadpool(require_current_admin, actor)
        res = await run_in_threadpool(
            lambda: list_visible_approvals(
                actor=actor,
                status="pending",
                approval_type="",
                created_by="",
                required_role="",
                assigned_to_me=False,
                limit=100,
            )
        )
        rows = [a for a in res.get("approvals", []) if str(a.get("approval_type") or "") in SKILL_TYPES]
        if rows:
            body = _CSS + '<div class="sr-wrap">' + "".join(_card(a) for a in rows) + "</div>"
        else:
            body = _CSS + '<div class="sr-empty">Заявок на навыки сейчас нет.</div>'
        return _page(actor, "Заявки на навыки", "skill-requests", body)

    @mcp.custom_route("/admin/skill-requests/decide", methods=["POST"], include_in_schema=False)
    @_guard
    async def skill_requests_decide(request, actor):
        await run_in_threadpool(require_current_admin, actor)
        form = await request.form()
        approval_id = str(form.get("approval_id", "")).strip()
        decision = str(form.get("decision", "")).strip()
        if approval_id and decision in ("approved", "rejected"):
            await run_in_threadpool(
                lambda: decide_approval(
                    actor=actor,
                    approval_id=approval_id,
                    decision=decision,
                    comment="",
                    decision_payload_json="{}",
                )
            )
        return RedirectResponse("/admin/skill-requests", status_code=303)
