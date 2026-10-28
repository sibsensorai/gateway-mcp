"""Админка: новые участники ядра — одобрить или отклонить вход."""

from __future__ import annotations

import secrets
from asyncio import to_thread as run_in_threadpool
from html import escape
from urllib.parse import parse_qs

from starlette.responses import RedirectResponse

from gateway_mcp.config import public_url
from gateway_mcp.routes.admin_access import CSRF_COOKIE, _guard, _page
from gateway_mcp.routes.admin_ui import fmt_time
from gateway_mcp.services import members
from gateway_mcp.services.approvals import decide_approval, get_approval_request
from gateway_mcp.services.observability import audit_event
from gateway_mcp.services.people import person

_CSS = """
<style>
.mb-wrap{display:grid;gap:14px;max-width:900px}
.mb-card{display:flex;align-items:center;justify-content:space-between;gap:16px;flex-wrap:wrap;background:#fff;border:1px solid #e3e6ef;border-radius:14px;padding:16px 20px}
.mb-who b{display:block;font-size:17px;color:#0d1b4c}
.mb-who span{font-size:13px;color:#7a8299}
.mb-act{display:flex;gap:8px;align-items:center;flex-wrap:wrap}
.mb-act input[type=text]{font:inherit;padding:8px 10px;border:1px solid #d9dfea;border-radius:8px;min-width:220px}
.mb-act button{border:none;border-radius:9px;padding:9px 16px;font-size:14px;font-weight:600;cursor:pointer}
.mb-ok{background:#1f9d6b;color:#fff}.mb-no{background:#fff;color:#d64545;border:1px solid #f0c9c9 !important}
.mb-badge{font-size:12px;border-radius:999px;padding:3px 10px}
.mb-badge.approved{background:#e7f8ef;color:#0b5e42}.mb-badge.rejected{background:#fdeaea;color:#b11c1c}
.mb-empty{background:#fff;border:1px solid #e3e6ef;border-radius:14px;padding:24px;text-align:center;color:#5b6172}
.mb-h{margin:22px 0 6px;font-size:16px;color:#0d1b4c}
</style>
"""


def _hidden(name: str, value: str) -> str:
    return f'<input type="hidden" name="{name}" value="{escape(value)}">'


def _who(row: dict) -> str:
    email = str(row.get("email") or row.get("login") or row.get("subject") or "")
    name = str(row.get("name") or "").strip()
    return escape(f"{name} ({email})" if name else email)


def _pending_card(row: dict, csrf: str) -> str:
    who = _who(row)
    return (
        '<div class="mb-card"><div class="mb-who">'
        f"<b>{who}</b><span>просит доступ · {escape(fmt_time(row.get('requested_at')))}</span></div>"
        '<form method="post" action="/admin/members/decide" class="mb-act">'
        + _hidden("csrf", csrf)
        + _hidden("member_key", str(row.get("member_key") or ""))
        + '<input type="text" name="note" maxlength="300" placeholder="Комментарий (необязательно)">'
        '<button class="mb-ok" name="decision" value="approved">✓ Пустить</button>'
        '<button class="mb-no" name="decision" value="rejected">✕ Отклонить</button>'
        "</form></div>"
    )


def _decided_card(row: dict, csrf: str) -> str:
    who = _who(row)
    status = str(row.get("status") or "")
    label = "допущен" if status == "approved" else "отклонён"
    flip = "rejected" if status == "approved" else "approved"
    flip_label = "Закрыть доступ" if status == "approved" else "Пустить"
    return (
        '<div class="mb-card"><div class="mb-who">'
        f"<b>{who}</b><span>{escape(fmt_time(row.get('decided_at')))} · решил: {escape(person(str(row.get('decided_by') or ''))['label'])}</span></div>"
        f'<div class="mb-act"><span class="mb-badge {status}">{label}</span>'
        '<form method="post" action="/admin/members/decide">'
        + _hidden("csrf", csrf)
        + _hidden("member_key", str(row.get("member_key") or ""))
        + f'<button class="{"mb-no" if flip == "rejected" else "mb-ok"}" name="decision" value="{flip}">{flip_label}</button>'
        "</form></div></div>"
    )


def register_member_routes(mcp):
    @mcp.custom_route("/admin/members", methods=["GET"], include_in_schema=False)
    @_guard
    async def members_page(request, actor):
        pending = await run_in_threadpool(lambda: members.list_members(status="pending", limit=100))
        decided = [
            r for r in await run_in_threadpool(lambda: members.list_members(limit=60)) if r.get("status") != "pending"
        ]
        csrf = request.cookies.get(CSRF_COOKIE) or secrets.token_urlsafe(32)
        body = _CSS + '<p class="lead muted">Новые сотрудники с почтой @sibsensor.com попадают в ядро только после одобрения. Решить может любой администратор ядра.</p>'
        body += '<div class="mb-wrap">'
        body += "".join(_pending_card(r, csrf) for r in pending) or '<div class="mb-empty">Новых заявок нет.</div>'
        if decided:
            body += '<h2 class="mb-h">Последние решения</h2>' + "".join(_decided_card(r, csrf) for r in decided[:30])
        body += "</div>"
        response = _page(actor, "Новые участники", "members", body)
        response.set_cookie(
            CSRF_COOKIE,
            csrf,
            httponly=True,
            secure=public_url().startswith("https://"),
            samesite="strict",
            path="/admin",
            max_age=3600,
        )
        return response

    @mcp.custom_route("/admin/members/decide", methods=["POST"], include_in_schema=False)
    @_guard
    async def members_decide(request, actor):
        raw = await request.body()
        if len(raw) > 8000:
            raise ValueError("form too large")
        form = {k: v[0] for k, v in parse_qs(raw.decode("utf-8"), keep_blank_values=True).items()}
        csrf = str(request.cookies.get(CSRF_COOKIE) or "")
        if not csrf or not secrets.compare_digest(csrf, form.get("csrf", "")):
            raise PermissionError("CSRF mismatch")
        decision = form.get("decision", "")
        key = form.get("member_key", "").strip().casefold()
        note = form.get("note", "").strip()[:300]
        if decision not in ("approved", "rejected") or not key:
            raise ValueError("invalid decision")

        def apply() -> None:
            row = members.get_member(key)
            if row is None:
                raise ValueError("member not found")
            approval_id = str(row.get("approval_id") or "")
            approval = get_approval_request(approval_id) if approval_id else None
            if approval and approval.get("status") in ("pending", "need_info"):
                # решение по открытой заявке: журнал заявки + перенос в таблицу допуска
                decide_approval(
                    actor=actor,
                    approval_id=approval_id,
                    decision=decision,
                    comment=note,
                    decision_payload_json="{}",
                )
            members.set_member_status(key, status=decision, decided_by=actor.subject, note=note)
            audit_event(
                event="member_access",
                actor=actor,
                system="access",
                decision="allow" if decision == "approved" else "deny",
                status="ok",
                arguments={"member": key, "decision": decision},
            )

        await run_in_threadpool(apply)
        return RedirectResponse("/admin/members", status_code=303)
