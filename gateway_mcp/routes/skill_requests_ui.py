"""Web page for owners to review and decide skill/agent proposals (заявки на навыки)."""

from __future__ import annotations

import base64
import json
from asyncio import to_thread as run_in_threadpool
from functools import wraps
from html import escape
from urllib.parse import quote

from starlette.responses import PlainTextResponse, RedirectResponse, Response

from gateway_mcp.config import public_url
from gateway_mcp.routes.admin_access import _guard, _page
from gateway_mcp.routes.admin_ui import fmt_time
from gateway_mcp.services.admin_roles import require_current_admin
from gateway_mcp.services import storage_skills
from gateway_mcp.services.approvals import create_approval, decide_approval, list_visible_approvals
from gateway_mcp.tools.skills import skill_summaries
from gateway_mcp.web import login_redirect, web_actor

DEPTS = ["IT", "Продажи", "Производство", "Руководство", "Другое"]
_DEPT_PACK = {
    "IT": "sibsensor-it",
    "Продажи": "sibsensor-sales",
    "Производство": "sibsensor-prod",
    "Руководство": "sibsensor-mgmt",
}


def _dept_pack(dept: str) -> str:
    return _DEPT_PACK.get(dept, "sibsensor-misc")


def _dept_options() -> str:
    return "".join(f"<option>{escape(d)}</option>" for d in DEPTS)


_MAX_ATTACH = 5 * 1024 * 1024  # 5 МБ на вложение


async def _read_attachment(form):
    """Достаёт приложенный файл из формы. Возвращает (attachment|None, текст_если_md|'', статус).

    Статус: '' — файл не выбран; 'ok:<имя>'; 'empty'; 'toolarge'; 'error'.
    """
    up = form.get("attachment")
    filename = getattr(up, "filename", "") or ""
    if not filename:
        return None, "", ""
    try:
        data = await up.read()
    except Exception:
        return None, "", "error"
    if not data:
        return None, "", "empty"
    if len(data) > _MAX_ATTACH:
        return None, "", "toolarge"
    att_text = ""
    if filename.lower().endswith((".md", ".markdown", ".txt")):
        att_text = data.decode("utf-8", errors="replace").strip()
    attachment = {
        "filename": filename,
        "size": len(data),
        "content_base64": base64.b64encode(data).decode("ascii"),
    }
    return attachment, att_text, "ok:" + filename


_FORM_CSS = """
<style>
.sr-form{display:flex;flex-direction:column;gap:14px;max-width:760px;background:#fff;border:1px solid #e3e6ef;border-radius:14px;padding:24px}
.sr-form label{display:flex;flex-direction:column;gap:6px;font-size:14px;color:#0d1b4c;font-weight:600}
.sr-form input,.sr-form select,.sr-form textarea{font:inherit;font-weight:400;padding:10px 12px;border:1px solid #d9dfea;border-radius:9px;background:#fbfcff}
.sr-form textarea{font-family:Consolas,monospace;font-size:13px;resize:vertical}
.sr-form button{align-self:flex-start;background:#2b6cff;color:#fff;border:none;border-radius:9px;padding:11px 24px;font-size:15px;font-weight:600;cursor:pointer}
.sr-form .back{font-size:13px;color:#5b6172}
.sr-ok{background:#e7f8ef;border:1px solid #bfe9d2;color:#0b5e42;border-radius:12px;padding:14px 18px;margin-bottom:16px;font-weight:600}
.btn{display:inline-block;background:#2b6cff;color:#fff;text-decoration:none;border-radius:9px;padding:10px 20px;font-weight:600;font-size:14px;margin-top:6px}
</style>
"""


def _att_banner(note: str) -> str:
    """Понятное сообщение о том, что стало с приложенным файлом."""
    note = (note or "").strip()
    if not note:
        return ""
    if note.startswith("ok:"):
        text, color = f"📎 Файл «{escape(note[3:])}» приложен к заявке.", "ok"
    elif note == "empty":
        text, color = "⚠️ Файл пустой (0 байт) — он не приложен. Проверь файл и приложи заново.", "warn"
    elif note == "toolarge":
        text, color = "⚠️ Файл больше 5 МБ — он не приложен.", "warn"
    else:
        text, color = "⚠️ Не удалось прочитать файл — он не приложен.", "warn"
    style = "" if color == "ok" else ' style="background:#fff5e0;border-color:#f0d79a;color:#8a5a00"'
    return f'<div class="sr-ok"{style}>{text}</div>'


def _new_landing() -> str:
    return (
        '<div class="sr-wrap">'
        '<article class="sr-card"><h3>➕ Новый навык</h3>'
        '<p class="sr-what">Одно умение — один файл SKILL.md. Уйдёт владельцам на одобрение.</p>'
        '<a class="btn" href="/skills/submit">Добавить навык</a></article>'
        '<article class="sr-card"><h3>🧩 Новый агент</h3>'
        '<p class="sr-what">Набор навыков под одну роль. Укажи имена уже добавленных навыков.</p>'
        '<a class="btn" href="/skills/submit-agent">Добавить агента</a></article>'
        "</div>"
    )


def _skill_form_html() -> str:
    return (
        '<form method="post" action="/skills/submit" enctype="multipart/form-data" class="sr-form">'
        "<label>Название навыка (напр. it-проверка-vpn)"
        '<input name="name" required maxlength="80"></label>'
        f"<label>Отдел<select name=\"department\">{_dept_options()}</select></label>"
        '<label>Что делает (кратко)<input name="summary" maxlength="200"></label>'
        "<label>Файл навыка или материалы (можно приложить .md, .docx, .zip — до 5 МБ)"
        '<input type="file" name="attachment"></label>'
        "<label>Либо вставь текст навыка (SKILL.md) сюда"
        '<textarea name="content" rows="14" placeholder="---&#10;name: it-...&#10;description: ...&#10;---&#10;# ..."></textarea></label>'
        "<button type=\"submit\">Отправить заявку</button>"
        '<a class="back" href="/skills/new">← назад</a>'
        "</form>"
    )


def _agent_form_html() -> str:
    return (
        '<form method="post" action="/skills/submit-agent" enctype="multipart/form-data" class="sr-form">'
        "<label>Имя агента (напр. agent-контроль-совещаний)"
        '<input name="slug" required maxlength="80"></label>'
        '<label>Название (для людей)<input name="title" maxlength="120"></label>'
        f"<label>Отдел<select name=\"department\">{_dept_options()}</select></label>"
        '<label>Что делает (кратко)<input name="description" maxlength="200"></label>'
        "<label>Файл или материалы (необязательно, до 5 МБ)"
        '<input type="file" name="attachment"></label>'
        "<label>Навыки набора — по одному в строке (имена уже добавленных навыков)"
        '<textarea name="skill_names" rows="8" required placeholder="it-навык-1&#10;it-навык-2"></textarea></label>'
        "<button type=\"submit\">Отправить заявку</button>"
        '<a class="back" href="/skills/new">← назад</a>'
        "</form>"
    )

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

    att = payload.get("attachment") if isinstance(payload.get("attachment"), dict) else None
    att_html = ""
    if att and att.get("filename"):
        kb = round((att.get("size") or 0) / 1024, 1)
        att_html = (
            f'<p class="sr-what">📎 Вложение: {escape(str(att.get("filename")))} ({kb} КБ) · '
            f'<a href="/admin/skill-requests/attachment?id={aid}">скачать</a></p>'
        )

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
        f"{att_html}"
        f'<div class="sr-meta">от {by} · {created}</div>'
        f"{form}"
        "</article>"
    )


_STATUS_RU = {
    "pending": ("⏳ На рассмотрении", "wait"),
    "need_info": ("❓ Нужны уточнения", "wait"),
    "approved": ("✅ Одобрено", "ok"),
    "rejected": ("❌ Отклонено", "no"),
    "cancelled": ("⏹ Отменено", "no"),
}

_ME_CSS = """
<style>
.me-wrap{display:flex;flex-direction:column;gap:20px;max-width:900px}
.me-hero{background:linear-gradient(135deg,#2b6cff,#1746b8);color:#fff;border-radius:16px;padding:22px 24px}
.me-hero h2{margin:0 0 4px;font-size:22px}
.me-hero p{margin:0;opacity:.92;font-size:15px}
.me-cta{display:inline-block;margin-top:14px;background:#fff;color:#1746b8;text-decoration:none;border-radius:10px;padding:11px 22px;font-weight:700;font-size:15px}
.me-sec{background:#fff;border:1px solid #e3e6ef;border-radius:14px;padding:18px 22px}
.me-sec h3{margin:0 0 12px;font-size:17px;color:#0d1b4c}
.me-list{list-style:none;margin:0;padding:0;display:flex;flex-direction:column;gap:10px}
.me-list li{display:flex;flex-wrap:wrap;align-items:center;gap:8px 12px;padding:10px 0;border-bottom:1px solid #f0f2f8}
.me-list li:last-child{border-bottom:none}
.me-k{font-size:11px;letter-spacing:.04em;text-transform:uppercase;color:#2b6cff;background:#eef3ff;border-radius:999px;padding:3px 10px}
.me-name{font-weight:600;color:#0d1b4c}
.me-desc{color:#53607a;font-size:14px;flex-basis:100%}
.me-date{color:#9099ad;font-size:12.5px;margin-left:auto}
.me-badge{font-size:12.5px;font-weight:700;border-radius:999px;padding:3px 11px}
.me-badge.wait{background:#fff5e0;color:#8a5a00}
.me-badge.ok{background:#e7f8ef;color:#0b5e42}
.me-badge.no{background:#fdeaea;color:#b11c1c}
.me-empty{color:#7a8296;font-size:14px;margin:0}
.me-links{display:flex;gap:10px;flex-wrap:wrap}
.me-links a{text-decoration:none;color:#1746b8;border:1px solid #d9e1f2;border-radius:9px;padding:9px 16px;font-size:14px;font-weight:600;background:#f7f9ff}
</style>
"""


def _me_requests(mine: list) -> str:
    if not mine:
        return '<p class="me-empty">Ты ещё не отправлял заявок. Нажми «Предложить навык» выше.</p>'
    items = []
    for a in mine:
        is_agent = str(a.get("approval_type") or "") in ("agent_proposal", "agent_publish")
        kind = "Агент" if is_agent else "Навык"
        name = escape(str(a.get("subject") or ""))
        label, cls = _STATUS_RU.get(str(a.get("status") or ""), (str(a.get("status") or ""), "wait"))
        date = escape(fmt_time(a.get("created_at")))
        items.append(
            f'<li><span class="me-k">{kind}</span>'
            f'<span class="me-name">{name}</span>'
            f'<span class="me-badge {cls}">{escape(label)}</span>'
            f'<span class="me-date">{date}</span></li>'
        )
    return f'<ul class="me-list">{"".join(items)}</ul>'


def _me_catalog(skills: list, agents: list) -> str:
    parts = []
    if agents:
        items = []
        for ag in agents:
            name = escape(str(ag.get("title") or ag.get("slug") or ""))
            desc = escape(str(ag.get("description") or ""))
            raw = ag.get("skills")
            count = len(raw) if isinstance(raw, list) else 0
            sub = f" · {count} навыков" if count else ""
            items.append(
                f'<li><span class="me-k">Агент</span><span class="me-name">{name}{sub}</span>'
                f'<span class="me-desc">{desc}</span></li>'
            )
        parts.append(f'<ul class="me-list">{"".join(items)}</ul>')
    if skills:
        items = []
        for sk in skills:
            name = escape(str(sk.get("title") or sk.get("name") or ""))
            dept = escape(str(sk.get("department") or ""))
            desc = escape(str(sk.get("description") or ""))
            tag = f'<span class="me-k">{dept}</span>' if dept else '<span class="me-k">Навык</span>'
            items.append(
                f'<li>{tag}<span class="me-name">{name}</span>'
                f'<span class="me-desc">{desc}</span></li>'
            )
        parts.append(f'<ul class="me-list">{"".join(items)}</ul>')
    if not parts:
        return '<p class="me-empty">Пока в компании нет общих навыков. Будь первым — предложи свой!</p>'
    return "".join(parts)


def _me_body(actor, mine: list, skills: list, agents: list) -> str:
    hero = (
        '<div class="me-hero">'
        f"<h2>Привет, {escape(actor.display)}! 👋</h2>"
        "<p>Ты подключён к «Сибсенсор AI». Здесь — твои заявки и навыки компании.</p>"
        '<a class="me-cta" href="/skills/new">➕ Предложить навык или агента</a>'
        "</div>"
    )
    requests = (
        '<section class="me-sec"><h3>📋 Мои заявки</h3>'
        + _me_requests(mine)
        + "</section>"
    )
    catalog = (
        '<section class="me-sec"><h3>🧩 Навыки и агенты компании</h3>'
        + _me_catalog(skills, agents)
        + "</section>"
    )
    links = (
        '<section class="me-sec"><h3>🔗 Ещё</h3>'
        '<div class="me-links">'
        '<a href="/notifications">🔔 Уведомления</a>'
        '<a href="/credentials">🔌 Мои подключения</a>'
        '<a href="/my/skills">📊 Моя статистика</a>'
        "</div></section>"
    )
    return '<div class="me-wrap">' + hero + requests + catalog + links + "</div>"


def _user_guard(handler):
    """Любой залогиненный сотрудник (вход через Яндекс), без права access:admin."""

    @wraps(handler)
    async def guarded(request):
        actor = web_actor(request)
        if actor is None:
            return login_redirect(request.url.path or "/me")
        try:
            response = await handler(request, actor)
        except Exception:  # noqa: BLE001 - не раскрываем внутренние ошибки
            response = _page(
                actor,
                "Что-то пошло не так",
                "skills-new",
                '<div class="sr-empty">Не удалось отправить заявку. Попробуй ещё раз позже.</div>',
                503,
            )
        response.headers["Cache-Control"] = "no-store"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; style-src 'self' 'unsafe-inline'; "
            "form-action 'self'; frame-ancestors 'none'; base-uri 'none'"
        )
        return response

    return guarded


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

    @mcp.custom_route("/admin/skill-requests/attachment", methods=["GET"], include_in_schema=False)
    @_guard
    async def skill_requests_attachment(request, actor):
        await run_in_threadpool(require_current_admin, actor)
        aid = str(request.query_params.get("id", "")).strip()
        res = await run_in_threadpool(
            lambda: list_visible_approvals(
                actor=actor,
                status="",
                approval_type="",
                created_by="",
                required_role="",
                assigned_to_me=False,
                limit=200,
            )
        )
        appr = next((a for a in res.get("approvals", []) if str(a.get("approval_id") or "") == aid), None)
        payload = appr.get("payload") if appr and isinstance(appr.get("payload"), dict) else {}
        att = payload.get("attachment") if isinstance(payload.get("attachment"), dict) else None
        if not att or not att.get("content_base64"):
            return PlainTextResponse("Вложение не найдено.", status_code=404)
        try:
            data = base64.b64decode(att["content_base64"])
        except Exception:
            return PlainTextResponse("Повреждённое вложение.", status_code=500)
        filename = str(att.get("filename") or "attachment")
        resp = Response(content=data, media_type="application/octet-stream")
        resp.headers["Content-Disposition"] = "attachment; filename*=UTF-8''" + quote(filename)
        return resp

    @mcp.custom_route("/me", methods=["GET"], include_in_schema=False)
    @_user_guard
    async def me_home(request, actor):
        res = await run_in_threadpool(
            lambda: list_visible_approvals(
                actor=actor,
                status="",
                approval_type="",
                created_by=actor.subject,
                required_role="",
                assigned_to_me=False,
                limit=50,
            )
        )
        mine = [a for a in res.get("approvals", []) if str(a.get("approval_type") or "") in SKILL_TYPES]
        try:
            skills = await run_in_threadpool(skill_summaries)
        except Exception:
            skills = []
        try:
            agents = await run_in_threadpool(storage_skills.list_agents)
        except Exception:
            agents = []
        return _page(actor, "Моя страница", "me-home", _ME_CSS + _me_body(actor, mine, skills, agents))

    @mcp.custom_route("/skills/new", methods=["GET"], include_in_schema=False)
    @_user_guard
    async def skills_new(request, actor):
        ok = request.query_params.get("ok")
        banner = '<div class="sr-ok">✅ Заявка отправлена — владельцы её рассмотрят.</div>' if ok else ""
        banner += _att_banner(request.query_params.get("att", "")) if ok else ""
        return _page(actor, "Добавить навык или агента", "skills-new", _FORM_CSS + banner + _new_landing())

    @mcp.custom_route("/skills/submit", methods=["GET"], include_in_schema=False)
    @_user_guard
    async def skill_form(request, actor):
        banner = ""
        if request.query_params.get("err"):
            banner = (
                '<div class="sr-ok" style="background:#fdeaea;border-color:#f3c0c0;color:#b11c1c">'
                "Нужно название и текст навыка: вставь SKILL.md текстом или приложи файл .md/.txt. "
                "Файлы .docx/.zip принимаются как материалы, но текст навыка всё равно нужен.</div>"
            )
            banner += _att_banner(request.query_params.get("att", ""))
        return _page(actor, "Новый навык", "skills-new", _FORM_CSS + banner + _skill_form_html())

    @mcp.custom_route("/skills/submit", methods=["POST"], include_in_schema=False)
    @_user_guard
    async def skill_form_post(request, actor):
        form = await request.form()
        name = str(form.get("name", "")).strip()
        dept = str(form.get("department", "")).strip()
        summary = str(form.get("summary", "")).strip()
        content = str(form.get("content", "")).strip()
        attachment, att_text, att_note = await _read_attachment(form)
        if not content and att_text:
            content = att_text
        if name and content:
            payload = {
                "skill_name": name,
                "department": dept,
                "summary": summary,
                "skill_pack": _dept_pack(dept),
                "skill_md": content,
            }
            if attachment:
                payload["attachment"] = attachment
            await run_in_threadpool(
                lambda: create_approval(
                    actor=actor,
                    approval_type="skill_publish",
                    subject=name,
                    required_role="admin",
                    required_scope="",
                    artifact_hash="",
                    artifact_version="",
                    payload_json=json.dumps(payload, ensure_ascii=False),
                    source_refs_json="{}",
                    metadata_json=json.dumps({"via": "web"}, ensure_ascii=False),
                    four_eyes=False,
                    expires_in_days=14,
                )
            )
            return RedirectResponse("/skills/new?ok=1&att=" + quote(att_note), status_code=303)
        return RedirectResponse("/skills/submit?err=1&att=" + quote(att_note), status_code=303)

    @mcp.custom_route("/skills/submit-agent", methods=["GET"], include_in_schema=False)
    @_user_guard
    async def agent_form(request, actor):
        return _page(actor, "Новый агент", "skills-new", _FORM_CSS + _agent_form_html())

    @mcp.custom_route("/skills/submit-agent", methods=["POST"], include_in_schema=False)
    @_user_guard
    async def agent_form_post(request, actor):
        form = await request.form()
        slug = str(form.get("slug", "")).strip()
        title = str(form.get("title", "")).strip()
        desc = str(form.get("description", "")).strip()
        dept = str(form.get("department", "")).strip()
        raw = str(form.get("skill_names", ""))
        names = [s.strip() for s in raw.replace(",", "\n").splitlines() if s.strip()]
        attachment, _, att_note = await _read_attachment(form)
        if slug and names:
            payload = {
                "agent": {"slug": slug, "title": title or slug, "description": desc, "department": dept},
                "skill_names": names,
            }
            if attachment:
                payload["attachment"] = attachment
            await run_in_threadpool(
                lambda: create_approval(
                    actor=actor,
                    approval_type="agent_publish",
                    subject=title or slug,
                    required_role="admin",
                    required_scope="",
                    artifact_hash="",
                    artifact_version="",
                    payload_json=json.dumps(payload, ensure_ascii=False),
                    source_refs_json="{}",
                    metadata_json=json.dumps({"via": "web"}, ensure_ascii=False),
                    four_eyes=False,
                    expires_in_days=14,
                )
            )
        return RedirectResponse("/skills/new?ok=1&att=" + quote(att_note), status_code=303)
