"""Конвейер передачи навыка от сотрудника в ядро.

Один путь для веб-формы и для подачи из чата Claude:
1) автопроверка и автоисправление (имя, шапка SKILL.md, описание, размер,
   обновление существующего навыка, пароли/ключи, подозрительные «команды»,
   персональные данные);
2) заявка администраторам с готовым чек-листом;
3) после решения — ответ автору (при отказе с причиной) и объявление всем
   сотрудникам о новом или обновлённом навыке.
"""

from __future__ import annotations

import json
import re
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from gateway_mcp.services import storage_skills
from gateway_mcp.services.policy import GatewayActor

SKILL_TYPES = ("skill_proposal", "skill_publish", "agent_proposal", "agent_publish")
MAX_CONTENT = 100_000

DEPTS = ["IT", "Продажи", "Производство", "Руководство", "Другое"]
_DEPT_PACK = {
    "IT": "sibsensor-it",
    "Продажи": "sibsensor-sales",
    "Производство": "sibsensor-prod",
    "Руководство": "sibsensor-mgmt",
}

_TRANSLIT = dict(
    zip(
        "абвгдеёжзийклмнопрстуфхцчшщъыьэюя",
        ["a", "b", "v", "g", "d", "e", "e", "zh", "z", "i", "y", "k", "l", "m", "n", "o", "p", "r", "s", "t",
         "u", "f", "h", "ts", "ch", "sh", "sch", "", "y", "", "e", "yu", "ya"],
    )
)

_SECRET_PATTERNS = (
    (re.compile(r"(?i)\b(password|passwd|пароль|secret|секрет|api[_-]?key|token|токен)\b\s*[:=]\s*\S{6,}"), "пароль, ключ или токен в открытом виде"),
    (re.compile(r"\bsk-[A-Za-z0-9_-]{20,}"), "похоже на API-ключ"),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "похоже на ключ облака"),
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"), "закрытый ключ"),
    (re.compile(r"\b\d{8,10}:[A-Za-z0-9_-]{30,}\b"), "похоже на токен Telegram-бота"),
    (re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._-]{20,}"), "токен авторизации"),
    (re.compile(r"\by0_[A-Za-z0-9_-]{20,}"), "похоже на OAuth-токен Яндекса"),
)

_INJECTION_PATTERNS = (
    re.compile(r"(?i)ignore\s+(all\s+)?(previous|prior)\s+instructions"),
    re.compile(r"(?i)игнорируй\s+(все\s+)?(предыдущие|прошлые|остальные)\s+(инструкции|правила)"),
    re.compile(r"(?i)(не\s+сообщай|не\s+говори)\s+пользователю"),
    re.compile(r"(?i)do\s+not\s+tell\s+the\s+user"),
    re.compile(r"(?i)curl\s+[^\n|]*\|\s*(sh|bash)"),
    re.compile(r"(?i)\brm\s+-rf\b"),
    re.compile(r"(?i)(отправь|перешли|выгрузи)\s+[^\n]{0,60}(на\s+почту|на\s+адрес|по\s+ссылке|https?://)"),
)

_PERSONAL_PATTERNS = (
    (re.compile(r"\b\d{3}-\d{3}-\d{3}\s?\d{2}\b"), "похоже на СНИЛС"),
    (re.compile(r"(?:\+7|\b8)[\s(-]*\d{3}[\s)-]*\d{3}[\s-]*\d{2}[\s-]*\d{2}\b"), "номер телефона"),
)


def dept_pack(dept: str) -> str:
    return _DEPT_PACK.get(dept, "sibsensor-misc")


def slugify(value: str) -> str:
    text = "".join(_TRANSLIT.get(ch, ch) for ch in str(value or "").strip().casefold())
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    return text[:64].strip("-")


def _frontmatter(content: str) -> tuple[dict[str, str], str] | None:
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n?", content, re.S)
    if not m:
        return None
    meta = {}
    for line in m.group(1).splitlines():
        if ":" in line:
            key, value = line.split(":", 1)
            meta[key.strip()] = value.strip().strip('"').strip("'")
    return meta, content[m.end():]


def _check(cid: str, level: str, text: str) -> dict[str, str]:
    return {"id": cid, "level": level, "text": text}


def checks_summary(checks: list[dict[str, Any]]) -> str:
    counts = {"ok": 0, "fixed": 0, "warn": 0, "fail": 0}
    for c in checks:
        counts[str(c.get("level"))] = counts.get(str(c.get("level")), 0) + 1
    parts = [f"✅ {counts['ok'] + counts['fixed']}", f"⚠️ {counts['warn']}", f"❌ {counts['fail']}"]
    first = next((c for c in checks if c.get("level") in ("fail", "warn")), None)
    tail = f" — {first['text']}" if first else ""
    return " · ".join(parts) + tail


def prepare_skill(*, name: str, title: str, summary: str, content: str) -> dict[str, Any]:
    """Проверяет навык и исправляет то, что можно исправить автоматически."""
    checks: list[dict[str, str]] = []
    content = (content or "").replace("\r\n", "\n").strip()
    title = (title or "").strip()
    summary = (summary or "").strip()

    parsed = _frontmatter(content)
    meta = parsed[0] if parsed else {}
    raw_name = name or meta.get("name") or title
    slug = slugify(raw_name)
    if not slug:
        checks.append(_check("name", "fail", "Не задано название навыка"))
    elif slug != (raw_name or "").strip():
        checks.append(_check("name", "fixed", f"Имя приведено к виду «{slug}»"))
    else:
        checks.append(_check("name", "ok", f"Имя навыка: {slug}"))
    title = title or meta.get("title") or raw_name or slug

    description = summary or meta.get("description", "")
    if parsed is None:
        desc = description or title
        content = f"---\nname: {slug}\ndescription: {json.dumps(desc, ensure_ascii=False)}\n---\n\n{content}"
        checks.append(_check("frontmatter", "fixed", "Добавлена шапка SKILL.md (name, description)"))
    else:
        body = parsed[1]
        changed = meta.get("name") != slug or (not meta.get("description") and description)
        if changed:
            meta["name"] = slug
            if not meta.get("description") and description:
                meta["description"] = description
            lines = [f"{k}: {json.dumps(v, ensure_ascii=False) if k == 'description' else v}" for k, v in meta.items()]
            content = "---\n" + "\n".join(lines) + "\n---\n\n" + body.lstrip()
            checks.append(_check("frontmatter", "fixed", "Шапка SKILL.md исправлена"))
        else:
            checks.append(_check("frontmatter", "ok", "Шапка SKILL.md в порядке"))
    if description:
        checks.append(_check("description", "ok", "Есть описание, когда применять навык"))
    else:
        checks.append(_check("description", "warn", "Нет описания: ассистенту будет сложнее понять, когда применять навык"))

    body_len = len(_frontmatter(content)[1].strip()) if _frontmatter(content) else len(content)
    if len(content) > MAX_CONTENT:
        checks.append(_check("size", "fail", "Навык больше 100 КБ — разделите его на части"))
    elif body_len < 200:
        checks.append(_check("size", "warn", "Текст навыка очень короткий — проверьте, что в нём есть шаги"))
    else:
        checks.append(_check("size", "ok", "Объём текста нормальный"))

    for pattern, label in _SECRET_PATTERNS:
        m = pattern.search(content)
        if m:
            line_no = content[: m.start()].count("\n") + 1
            checks.append(_check("secrets", "fail", f"Строка {line_no}: {label} — уберите перед отправкой"))
            break
    else:
        checks.append(_check("secrets", "ok", "Паролей, ключей и токенов не найдено"))

    hits = [p for p in _INJECTION_PATTERNS if p.search(content)]
    if hits:
        checks.append(_check("injection", "warn", "Есть подозрительные «команды» (обход правил, отправка данных, опасные команды) — проверьте вручную"))
    else:
        checks.append(_check("injection", "ok", "Подозрительных команд не найдено"))

    found = [label for pattern, label in _PERSONAL_PATTERNS if pattern.search(content)]
    if found:
        checks.append(_check("personal", "warn", "Возможно, есть персональные данные: " + ", ".join(found)))
    else:
        checks.append(_check("personal", "ok", "Персональных данных не найдено"))

    is_update = False
    diff = {}
    existing = None
    if slug and storage_skills.postgres_enabled():
        try:
            existing = storage_skills.get_skill(slug)
        except Exception:
            existing = None
    if existing:
        is_update = True
        old = (existing.get("content") or "").splitlines()
        new = content.splitlines()
        added = len([line for line in new if line not in set(old)])
        removed = len([line for line in old if line not in set(new)])
        diff = {"added": added, "removed": removed}
        checks.append(_check("update", "ok", f"Обновит существующий навык «{existing.get('title') or slug}»: +{added} / −{removed} строк"))
    else:
        checks.append(_check("update", "ok", "Новый навык в ядре"))

    return {
        "name": slug,
        "title": title,
        "description": description,
        "content": content,
        "checks": checks,
        "blocked": any(c["level"] == "fail" for c in checks),
        "is_update": is_update,
        "diff": diff,
    }


def submit_skill(
    *,
    actor: GatewayActor,
    name: str,
    title: str,
    department: str,
    summary: str,
    content: str,
    attachment: dict[str, Any] | None = None,
    via: str = "web",
) -> dict[str, Any]:
    """Проверяет навык и создаёт заявку администраторам. Заблокированное не отправляет."""
    prepared = prepare_skill(name=name, title=title, summary=summary, content=content)
    if prepared["blocked"]:
        return {"ok": False, "blocked": True, **prepared}
    from gateway_mcp.services.approvals import create_approval

    payload = {
        "skill_name": prepared["name"],
        "title": prepared["title"],
        "department": department,
        "summary": prepared["description"],
        "skill_pack": dept_pack(department),
        "skill_md": prepared["content"],
        "checks": prepared["checks"],
        "is_update": prepared["is_update"],
        "diff": prepared["diff"],
    }
    if attachment:
        payload["attachment"] = attachment
    result = create_approval(
        actor=actor,
        approval_type="skill_publish",
        subject=prepared["name"],
        required_role="admin",
        required_scope="access:admin",
        artifact_hash="",
        artifact_version="",
        payload_json=json.dumps(payload, ensure_ascii=False),
        source_refs_json="{}",
        metadata_json=json.dumps({"via": via}, ensure_ascii=False),
        four_eyes=False,
        expires_in_days=14,
    )
    approval = result.get("approval") or {}
    return {"ok": True, "blocked": False, "approval_id": approval.get("approval_id", ""), **prepared}


# --- после решения ---

def _notify(*, event_type: str, title: str, body: str, action_url: str, recipients: list[dict[str, str]], key: str) -> None:
    from gateway_mcp.services import storage_notifications

    storage_notifications.insert_notification(
        notification_id=f"notification-{uuid.uuid4()}",
        event_type=event_type,
        title=title[:180],
        body=body[:1200],
        action_url=action_url,
        project_id="",
        priority="normal",
        created_by="system:skills",
        recipients=recipients,
        artifact_refs=[],
        metadata={},
        idempotency_key=key[:180],
        expires_at=datetime.now(UTC) + timedelta(days=30),
    )


def _telegram(text: str) -> None:
    try:
        from gateway_mcp.backends.notifications import _configured_skill_update_chat_id, _send_via_bot_api

        _send_via_bot_api(_configured_skill_update_chat_id(), text)
    except Exception:
        pass


def on_approval_decided(approval: dict[str, Any], comment: str = "") -> None:
    """Ответ автору навыка и объявление всем сотрудникам после решения администратора."""
    atype = str(approval.get("approval_type") or "")
    if atype not in SKILL_TYPES:
        return
    status = str(approval.get("status") or "")
    payload = approval.get("payload") if isinstance(approval.get("payload"), dict) else {}
    is_agent = atype.startswith("agent")
    if is_agent:
        meta = payload.get("agent") if isinstance(payload.get("agent"), dict) else {}
        name = str(meta.get("title") or meta.get("slug") or approval.get("subject") or "")
        kind = "Агент"
    else:
        name = str(payload.get("title") or payload.get("skill_name") or approval.get("subject") or "")
        kind = "Навык"
    author = str(approval.get("created_by") or "").casefold()
    aid = str(approval.get("approval_id") or "")
    reason = (comment or "").strip()

    if status == "approved":
        if author:
            _notify(
                event_type="skill.approved",
                title=f"✅ {kind} «{name}» одобрен и опубликован",
                body="Он уже доступен всем подключённым сотрудникам. Начните новый чат, чтобы ассистент его увидел."
                + (f"\nКомментарий: {reason}" if reason else ""),
                action_url="/me",
                recipients=[{"type": "user", "key": author}],
                key=f"{aid}:approved:author",
            )
        updated = bool(payload.get("is_update"))
        what = str(payload.get("summary") or "")
        _notify(
            event_type="skill.published",
            title=f"🧩 {'Обновлён' if updated else 'Новый'} {kind.lower()} в ядре: {name}",
            body=(what or "Попросите ассистента: «какие навыки есть у компании?»"),
            action_url="/me",
            recipients=[{"type": "group", "key": "employees"}],
            key=f"{aid}:published:all",
        )
        _telegram(f"✅ Опубликован {kind.lower()}: {name}\nОдобрил: {approval.get('decided_by') or ''}")
    elif status == "rejected" and author:
        _notify(
            event_type="skill.rejected",
            title=f"❌ {kind} «{name}» не одобрен",
            body=f"Причина: {reason or 'не указана'}\nИсправьте и отправьте снова.",
            action_url="/skills/submit",
            recipients=[{"type": "user", "key": author}],
            key=f"{aid}:rejected:author",
        )
    elif status == "need_info" and author:
        _notify(
            event_type="skill.need_info",
            title=f"❓ По заявке «{name}» нужны уточнения",
            body=reason or "Администратор просит уточнить заявку.",
            action_url="/me",
            recipients=[{"type": "user", "key": author}],
            key=f"{aid}:need_info:author",
        )
