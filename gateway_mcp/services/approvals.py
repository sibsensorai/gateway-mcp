import hashlib
import json
import secrets
from datetime import UTC, datetime
from typing import Any

from gateway_mcp.services.policy import GatewayActor, has_scope
from gateway_mcp.services.storage import (
    append_approval_event,
    consume_approval_request,
    get_approval_request,
    insert_approval_request,
    list_approval_events,
    list_approval_requests,
    update_approval_decision,
)

OPEN_STATUSES = {"pending", "need_info"}
DECISIONS = {"approved", "rejected", "need_info"}


def _notify_telegram_new_request(approval: dict) -> None:
    """Best-effort Telegram ping to owners when a new skill/agent request is created."""
    atype = str((approval or {}).get("approval_type") or "")
    if atype not in ("skill_proposal", "skill_publish", "agent_proposal", "agent_publish"):
        return
    try:
        from gateway_mcp.backends.notifications import _configured_skill_update_chat_id, _send_via_bot_api
        from gateway_mcp.config import public_url

        chat_id = _configured_skill_update_chat_id()
        payload = approval.get("payload") if isinstance(approval.get("payload"), dict) else {}
        if atype.startswith("agent"):
            meta = payload.get("agent") if isinstance(payload.get("agent"), dict) else {}
            name = str(meta.get("title") or meta.get("slug") or approval.get("subject") or "")
            kind = "Агент (набор навыков)"
            what = str(meta.get("description") or payload.get("summary") or "")
        else:
            name = str(payload.get("skill_name") or payload.get("skill") or approval.get("subject") or "")
            kind = "Навык"
            what = str(payload.get("summary") or "")
        link = public_url().rstrip("/") + "/admin/skill-requests"
        text = f"🆕 Новая заявка на одобрение\n{kind}: {name}\n{what}\nОткрыть: {link}"
        _send_via_bot_api(chat_id, text)
    except Exception:
        return  # Telegram опционален — не ломаем создание заявки
    try:
        import base64

        from gateway_mcp.backends.notifications import _send_document_via_bot_api

        att = payload.get("attachment") if isinstance(payload.get("attachment"), dict) else None
        if att and att.get("content_base64"):
            _send_document_via_bot_api(
                chat_id,
                str(att.get("filename") or "attachment"),
                base64.b64decode(att["content_base64"]),
                caption=f"Вложение к заявке: {name}",
            )
        elif not atype.startswith("agent") and str(payload.get("skill_md") or "").strip():
            safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in name) or "skill"
            _send_document_via_bot_api(
                chat_id,
                f"{safe}.md",
                str(payload.get("skill_md")).encode("utf-8"),
                caption=f"Текст навыка: {name}",
            )
    except Exception:
        pass  # файл в чат — необязательное дополнение


def create_approval(
    *,
    actor: GatewayActor,
    approval_type: str,
    subject: str,
    required_role: str,
    required_scope: str,
    artifact_hash: str,
    artifact_version: str,
    payload_json: str,
    source_refs_json: str,
    metadata_json: str,
    four_eyes: bool,
    expires_in_days: int,
) -> dict[str, Any]:
    payload = _parse_json_object(payload_json, "payload_json")
    source_refs = _parse_json_object(source_refs_json, "source_refs_json")
    metadata = _parse_json_object(metadata_json, "metadata_json")
    approval_type = _normalize_token(approval_type, "approval_type")
    subject = str(subject or "").strip()
    if not subject:
        raise ValueError("subject is required")
    if not required_role and not required_scope:
        raise ValueError("required_role or required_scope is required")
    if expires_in_days < 0 or expires_in_days > 365:
        raise ValueError("expires_in_days must be between 0 and 365")

    artifact_hash = str(artifact_hash or "").strip()
    if not artifact_hash:
        artifact_hash = compute_artifact_hash(
            approval_type=approval_type,
            subject=subject,
            artifact_version=artifact_version,
            payload=payload,
            source_refs=source_refs,
        )
    approval_id = new_approval_id(approval_type)
    approval = insert_approval_request(
        approval_id=approval_id,
        approval_type=approval_type,
        subject=subject,
        created_by=actor.subject,
        required_role=str(required_role or "").strip(),
        required_scope=str(required_scope or "").strip(),
        artifact_hash=artifact_hash,
        artifact_version=str(artifact_version or "").strip(),
        payload=payload,
        source_refs=source_refs,
        metadata=metadata,
        four_eyes=bool(four_eyes),
        expires_in_days=expires_in_days or None,
    )
    _notify_telegram_new_request(approval)
    return {"approval": approval, "events": list_approval_events(approval_id)}


def get_approval(
    *, actor: GatewayActor, approval_id: str, include_events: bool = True
) -> dict[str, Any]:
    approval = get_approval_request(_normalize_id(approval_id))
    if not approval:
        raise ValueError("approval not found")
    if not can_read_approval(actor, approval):
        raise PermissionError("approval is not visible to current actor")
    events = (
        list_approval_events(str(approval["approval_id"])) if include_events else []
    )
    return {"approval": approval, "events": events}


def list_visible_approvals(
    *,
    actor: GatewayActor,
    status: str,
    approval_type: str,
    created_by: str,
    required_role: str,
    assigned_to_me: bool,
    limit: int,
) -> dict[str, Any]:
    rows = list_approval_requests(
        status=str(status or "").strip(),
        approval_type=str(approval_type or "").strip(),
        created_by=str(created_by or "").strip(),
        required_role=str(required_role or "").strip(),
        limit=max(1, min(int(limit or 50), 500)),
    )
    visible = []
    for row in rows:
        if not can_read_approval(actor, row):
            continue
        if assigned_to_me and not can_decide_approval(actor, row):
            continue
        visible.append(row)
        if len(visible) >= max(1, min(int(limit or 50), 100)):
            break
    return {"count": len(visible), "approvals": visible}


def _extract_skill_from_payload(payload: dict) -> dict | None:
    """Pull a publishable skill out of an approval payload (handles several shapes)."""
    import re

    if not isinstance(payload, dict):
        return None
    files = payload.get("files") if isinstance(payload.get("files"), dict) else {}
    name = str(payload.get("skill_name") or payload.get("skill") or "").strip()
    content = str(payload.get("skill_md") or files.get("SKILL.md") or "").strip()
    if not name or not content:
        return None
    description = str(payload.get("summary") or payload.get("description") or "").strip()
    if not description:
        m = re.search(r'^description:\s*"?(.*?)"?\s*$', content, re.M)
        if m:
            description = m.group(1).strip()
    return {
        "name": name,
        "pack": str(payload.get("skill_pack") or payload.get("pack") or ""),
        "department": str(payload.get("department") or ""),
        "title": str(payload.get("title") or name),
        "description": description,
        "content": content,
    }


def _autopublish_on_approval(approval: dict) -> None:
    """When a skill/agent approval is approved, publish it straight to the core catalog."""
    approval = approval or {}
    if str(approval.get("status") or "") != "approved":
        return
    atype = str(approval.get("approval_type") or "")
    payload = approval.get("payload") or {}
    if not isinstance(payload, dict):
        return
    from gateway_mcp.services import storage_skills

    if not storage_skills.postgres_enabled():
        return
    who = str(approval.get("decided_by") or "approval")
    if atype in ("skill_proposal", "skill_publish"):
        skill = _extract_skill_from_payload(payload)
        if not skill:
            return
        storage_skills.upsert_skill(
            name=skill["name"], pack=skill["pack"], department=skill["department"],
            title=skill["title"], description=skill["description"], content=skill["content"],
            updated_by=who,
        )
    elif atype in ("agent_proposal", "agent_publish"):
        agent_meta = payload.get("agent") if isinstance(payload.get("agent"), dict) else {}
        slug = str(
            agent_meta.get("slug") or agent_meta.get("name") or payload.get("agent_slug") or payload.get("slug") or ""
        ).strip()
        skills_in = payload.get("skills") if isinstance(payload.get("skills"), list) else []
        ref_names = payload.get("skill_names") if isinstance(payload.get("skill_names"), list) else []
        if not slug or (not skills_in and not ref_names):
            return
        names: list[str] = []
        for item in skills_in:
            skill = _extract_skill_from_payload(item if isinstance(item, dict) else {})
            if not skill:
                continue
            storage_skills.upsert_skill(
                name=skill["name"], pack=skill["pack"], department=skill["department"],
                title=skill["title"], description=skill["description"], content=skill["content"],
                updated_by=who,
            )
            names.append(skill["name"])
        for ref in ref_names:
            ref = str(ref or "").strip()
            if ref and ref not in names:
                names.append(ref)
        storage_skills.upsert_agent(
            slug=slug, title=str(agent_meta.get("title") or slug),
            description=str(agent_meta.get("description") or payload.get("summary") or ""),
            department=str(agent_meta.get("department") or payload.get("department") or ""),
            skills=names, updated_by=who,
        )


def decide_approval(
    *,
    actor: GatewayActor,
    approval_id: str,
    decision: str,
    comment: str,
    decision_payload_json: str,
) -> dict[str, Any]:
    approval = get_approval_request(_normalize_id(approval_id))
    if not approval:
        raise ValueError("approval not found")
    if not can_decide_approval(actor, approval):
        raise PermissionError("current actor cannot decide this approval")
    if str(approval.get("status") or "") not in OPEN_STATUSES:
        raise ValueError(f"approval is not open: {approval.get('status')}")
    if _is_expired(approval):
        raise ValueError("approval is expired")
    if (
        approval.get("four_eyes")
        and str(approval.get("created_by") or "") == actor.subject
    ):
        raise PermissionError("four-eyes approval cannot be decided by its creator")

    normalized_decision = str(decision or "").strip().casefold()
    if normalized_decision not in DECISIONS:
        raise ValueError(f"decision must be one of: {', '.join(sorted(DECISIONS))}")
    payload = _parse_json_object(decision_payload_json, "decision_payload_json")
    updated = update_approval_decision(
        approval_id=str(approval["approval_id"]),
        status=normalized_decision,
        decided_by=actor.subject,
        actor_groups=list(actor.groups),
        comment=str(comment or ""),
        decision_payload=payload,
    )
    if not updated:
        raise ValueError("approval was already decided, changed, or expired")
    try:
        _autopublish_on_approval(updated)
    except Exception:
        pass  # публикация не должна ломать само решение по заявке
    return {
        "approval": updated,
        "events": list_approval_events(str(approval["approval_id"])),
    }


def comment_approval(
    *,
    actor: GatewayActor,
    approval_id: str,
    comment: str,
    decision_payload_json: str = "{}",
) -> dict[str, Any]:
    approval = get_approval_request(_normalize_id(approval_id))
    if not approval:
        raise ValueError("approval not found")
    if not can_read_approval(actor, approval):
        raise PermissionError("approval is not visible to current actor")
    if not str(comment or "").strip():
        raise ValueError("comment is required")
    event = append_approval_event(
        approval_id=str(approval["approval_id"]),
        event_type="commented",
        actor_subject=actor.subject,
        actor_groups=list(actor.groups),
        comment=str(comment).strip(),
        decision_payload=_parse_json_object(
            decision_payload_json, "decision_payload_json"
        ),
    )
    return {
        "approval": approval,
        "event": event,
        "events": list_approval_events(str(approval["approval_id"])),
    }


def validate_and_consume_approval(
    *,
    actor: GatewayActor,
    approval_id: str,
    tool_name: str,
    arguments: dict[str, Any],
    idempotency_key: str,
    expected_type: str = "",
) -> dict[str, Any]:
    approval = get_approval_request(_normalize_id(approval_id))
    if not approval:
        raise PermissionError("approval was not found")
    if str(approval.get("status") or "") != "approved":
        raise PermissionError("approval is not approved")
    if _is_expired(approval):
        raise PermissionError("approval is expired")
    expected = str(expected_type or "").strip().casefold()
    if expected and str(approval.get("approval_type") or "").casefold() != expected:
        raise PermissionError("approval type does not match the protected operation")
    executor = str(dict(approval.get("metadata") or {}).get("executor_subject") or "")
    creator = str(approval.get("created_by") or "")
    if not has_scope(actor, "approvals:admin") and actor.subject not in {
        executor,
        creator,
    }:
        raise PermissionError("approval is not bound to the current executor")

    payload = approval.get("payload")
    if not isinstance(payload, dict):
        raise PermissionError("approval payload is invalid")
    approved_tool = str(payload.get("tool_name") or "").strip()
    if approved_tool and approved_tool != tool_name:
        raise PermissionError("approval is bound to another tool")
    expected_arguments = payload.get("arguments")
    if expected_arguments is None:
        expected_arguments = {
            key: value for key, value in payload.items() if key != "tool_name"
        }
    if not isinstance(expected_arguments, dict) or not expected_arguments:
        raise PermissionError("approval must bind at least one invocation argument")
    invocation = {
        key: value for key, value in arguments.items() if key != "approval_ref"
    }
    if not _is_subset(expected_arguments, invocation):
        raise PermissionError("approval payload does not match this invocation")

    invocation_hash = hashlib.sha256(
        json.dumps(
            {"tool_name": tool_name, "arguments": invocation},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    consumption_key = hashlib.sha256(
        f"{approval_id}\0{idempotency_key}\0{invocation_hash}".encode()
    ).hexdigest()
    consumed = consume_approval_request(
        approval_id=str(approval["approval_id"]),
        actor_subject=actor.subject,
        action=tool_name,
        consumption_key=consumption_key,
        invocation_hash=invocation_hash,
    )
    if not consumed:
        raise PermissionError("approval was already consumed by another invocation")
    return consumed


def can_read_approval(actor: GatewayActor, approval: dict[str, Any]) -> bool:
    if has_scope(actor, "approvals:admin"):
        return True
    if str(approval.get("created_by") or "") == actor.subject:
        return True
    return can_decide_approval(actor, approval)


def can_decide_approval(actor: GatewayActor, approval: dict[str, Any]) -> bool:
    if has_scope(actor, "approvals:admin"):
        return True
    required_scope = str(approval.get("required_scope") or "").strip()
    if required_scope and has_scope(actor, required_scope):
        return True
    required_role = str(approval.get("required_role") or "").strip()
    return bool(required_role and required_role in set(actor.groups))


def compute_artifact_hash(
    *,
    approval_type: str,
    subject: str,
    artifact_version: str,
    payload: dict[str, Any],
    source_refs: dict[str, Any],
) -> str:
    material = {
        "approval_type": approval_type,
        "subject": subject,
        "artifact_version": artifact_version,
        "payload": payload,
        "source_refs": source_refs,
    }
    raw = json.dumps(
        material,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def new_approval_id(approval_type: str) -> str:
    prefix = approval_type.replace("_", "-")[:24].strip("-") or "approval"
    suffix = secrets.token_urlsafe(8).replace("_", "").replace("-", "").lower()
    return f"apr-{prefix}-{suffix}"


def _is_expired(approval: dict[str, Any]) -> bool:
    raw = approval.get("expires_at")
    if not raw:
        return False
    if isinstance(raw, datetime):
        value = raw
    else:
        try:
            value = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        except ValueError:
            return True
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value <= datetime.now(UTC)


def _parse_json_object(raw: str, field_name: str) -> dict[str, Any]:
    try:
        value = json.loads(raw or "{}")
    except json.JSONDecodeError as exc:
        raise ValueError(f"{field_name} must be valid JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise TypeError(f"{field_name} must be a JSON object")
    return value


def _normalize_token(value: str, field_name: str) -> str:
    clean = str(value or "").strip().casefold().replace("-", "_")
    if not clean:
        raise ValueError(f"{field_name} is required")
    allowed = set("abcdefghijklmnopqrstuvwxyz0123456789_:.")
    if any(char not in allowed for char in clean):
        raise ValueError(f"{field_name} contains unsupported characters")
    return clean


def _normalize_id(value: str) -> str:
    clean = str(value or "").strip()
    if not clean:
        raise ValueError("approval_id is required")
    return clean


def _is_subset(expected: Any, actual: Any) -> bool:
    if isinstance(expected, dict):
        return isinstance(actual, dict) and all(
            key in actual and _is_subset(value, actual[key])
            for key, value in expected.items()
        )
    if isinstance(expected, list):
        return isinstance(actual, list) and expected == actual
    return expected == actual
