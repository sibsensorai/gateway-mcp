"""Допуск новых участников к ядру.

Человек с почтой компании при первом входе не получает доступ сразу: ядро создаёт
заявку (approval_type ``member_access``), администраторам приходит уведомление, а
человек видит страницу «заявка отправлена». Одобрить может любой с ``access:admin``.
Кто входил в ядро до включения этой функции, допущен автоматически.
"""

from __future__ import annotations

import json
from typing import Any

from gateway_mcp.services.policy import (
    GatewayActor,
    has_scope,
    is_listed_user,
    member_approval_enabled,
)
from gateway_mcp.services.storage_core import _connect, ensure_schema, postgres_enabled

APPROVAL_TYPE = "member_access"
APPROVER_SCOPE = "access:admin"
STATUSES = {"pending", "approved", "rejected"}


class MemberPendingError(PermissionError):
    """Заявка на вход создана или ещё ждёт решения."""


class MemberRejectedError(PermissionError):
    """Администратор отклонил доступ."""


def member_key(actor: GatewayActor) -> str:
    return str(actor.email or actor.subject or "").strip().casefold()


# --- хранилище ---

def get_member(key: str) -> dict[str, Any] | None:
    ensure_schema()
    with _connect() as conn, conn.cursor() as cur:
        cur.execute("select * from member_access where member_key = %s", (key,))
        row = cur.fetchone()
        return dict(row) if row else None


def _insert_member(actor: GatewayActor, *, status: str, note: str = "", decided_by: str = "") -> dict[str, Any] | None:
    """Вставляет запись, если её ещё нет. Возвращает запись или None при гонке."""
    ensure_schema()
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            insert into member_access (member_key, subject, email, login, status, note, decided_by, decided_at)
            values (%s, %s, %s, %s, %s, %s, %s, case when %s = 'pending' then null else now() end)
            on conflict (member_key) do nothing
            returning *
            """,
            (member_key(actor), actor.subject, actor.email, actor.login, status, note, decided_by, status),
        )
        row = cur.fetchone()
        conn.commit()
        return dict(row) if row else None


def set_member_status(key: str, *, status: str, decided_by: str, note: str = "") -> dict[str, Any] | None:
    if status not in STATUSES:
        raise ValueError("unknown member status")
    ensure_schema()
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            update member_access
            set status = %s, decided_by = %s, decided_at = now(),
                note = case when %s <> '' then %s else note end
            where member_key = %s
            returning *
            """,
            (status, decided_by, note, note, key),
        )
        row = cur.fetchone()
        conn.commit()
        return dict(row) if row else None


def _attach_approval(key: str, approval_id: str) -> None:
    with _connect() as conn, conn.cursor() as cur:
        cur.execute("update member_access set approval_id = %s where member_key = %s", (approval_id, key))
        conn.commit()


def _known_yandex_user(subject: str) -> bool:
    """Человек уже входил в ядро раньше (есть сохранённый вход через Яндекс)."""
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(
            "select 1 from user_oauth_tokens where provider = 'yandex' and actor_subject = %s limit 1",
            (subject,),
        )
        return cur.fetchone() is not None


def list_members(*, status: str = "", limit: int = 100) -> list[dict[str, Any]]:
    ensure_schema()
    with _connect() as conn, conn.cursor() as cur:
        if status:
            cur.execute(
                "select * from member_access where status = %s order by requested_at desc limit %s",
                (status, limit),
            )
        else:
            cur.execute("select * from member_access order by requested_at desc limit %s", (limit,))
        return [dict(r) for r in cur.fetchall()]


def pending_count() -> int:
    if not postgres_enabled() or not member_approval_enabled():
        return 0
    ensure_schema()
    with _connect() as conn, conn.cursor() as cur:
        cur.execute("select count(*) as n from member_access where status = 'pending'")
        row = cur.fetchone() or {}
        return int(row.get("n", 0))


# --- решения ---

def _exempt(actor: GatewayActor, user_info: dict[str, Any] | None) -> bool:
    if not member_approval_enabled() or not postgres_enabled():
        return True
    if user_info is not None and is_listed_user(user_info):
        return True
    return has_scope(actor, APPROVER_SCOPE)


def check_member_on_login(actor: GatewayActor, user_info: dict[str, Any] | None = None) -> str:
    """Решает, пускать ли человека при входе. Возвращает 'approved' или бросает исключение.

    Новый человек получает запись 'pending' и заявку для администраторов.
    """
    if _exempt(actor, user_info):
        return "approved"
    key = member_key(actor)
    if not key:
        raise MemberRejectedError("member key is empty")
    row = get_member(key)
    if row is None:
        if _known_yandex_user(actor.subject):
            _insert_member(actor, status="approved", note="входил до включения одобрения", decided_by="system")
            return "approved"
        row = _insert_member(actor, status="pending")
        if row is not None:
            _open_request(actor, key)
        else:
            row = get_member(key)
    status = str((row or {}).get("status") or "pending")
    if status == "approved":
        return "approved"
    if status == "rejected":
        raise MemberRejectedError("member access was rejected by an administrator")
    raise MemberPendingError("member access is waiting for administrator approval")


def check_member_on_refresh(actor: GatewayActor) -> None:
    """При продлении входа: отозванный администратором доступ больше не продлевается."""
    if _exempt(actor, None):
        return
    row = get_member(member_key(actor))
    if row and row.get("status") == "rejected":
        raise MemberRejectedError("member access was rejected by an administrator")
    if row and row.get("status") == "pending":
        raise MemberPendingError("member access is waiting for administrator approval")


def _open_request(actor: GatewayActor, key: str) -> None:
    from gateway_mcp.services.approvals import create_approval

    payload = {
        "member_key": key,
        "email": actor.email,
        "login": actor.login,
        "subject": actor.subject,
        "summary": f"Новый участник просит доступ к ядру: {actor.email or actor.login or actor.subject}",
    }
    result = create_approval(
        actor=actor,
        approval_type=APPROVAL_TYPE,
        subject=actor.email or actor.subject,
        required_role="",
        required_scope=APPROVER_SCOPE,
        artifact_hash="",
        artifact_version="",
        payload_json=json.dumps(payload, ensure_ascii=False),
        source_refs_json="{}",
        metadata_json=json.dumps({"via": "login"}, ensure_ascii=False),
        four_eyes=False,
        expires_in_days=30,
    )
    approval_id = str((result.get("approval") or {}).get("approval_id") or "")
    if approval_id:
        _attach_approval(key, approval_id)


def on_approval_decided(approval: dict[str, Any]) -> None:
    """Вызывается после решения по заявке: переносит его в таблицу допуска."""
    if str(approval.get("approval_type") or "") != APPROVAL_TYPE:
        return
    status = str(approval.get("status") or "")
    if status not in ("approved", "rejected"):
        return
    payload = approval.get("payload") if isinstance(approval.get("payload"), dict) else {}
    key = str(payload.get("member_key") or payload.get("email") or "").strip().casefold()
    if key:
        set_member_status(key, status=status, decided_by=str(approval.get("decided_by") or ""))
