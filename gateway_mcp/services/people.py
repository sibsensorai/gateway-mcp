"""Имена людей для админских экранов: «ФИО (почта)» вместо технического yandex:…

ФИО берётся из входа через Яндекс (поле real_name). Для тех, кто входил до того,
как ядро начало его сохранять, имя один раз запрашивается у Яндекса по сохранённому
входу и запоминается. Если имя недоступно, показывается рабочая почта.
"""

from __future__ import annotations

import json
import time
from typing import Any

from gateway_mcp.services.storage_core import _connect, ensure_schema, postgres_enabled

_CACHE: dict[str, tuple[float, dict[str, str]]] = {}
_MISS_TTL = 600.0


def name_from_yandex_info(info: dict[str, Any]) -> str:
    """ФИО из ответа Яндекса: real_name, иначе «Фамилия Имя», иначе отображаемое имя."""
    if not isinstance(info, dict):
        return ""
    full = " ".join(str(info.get(k) or "").strip() for k in ("last_name", "first_name")).strip()
    return str(info.get("real_name") or full or info.get("display_name") or "").strip()


def _row(subject: str) -> dict[str, Any] | None:
    ensure_schema()
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            select actor_subject, email, login, metadata from user_oauth_tokens
            where provider = 'yandex' and (actor_subject = %s or lower(email) = %s)
            order by updated_at desc limit 1
            """,
            (subject, subject.casefold()),
        )
        row = cur.fetchone()
        return dict(row) if row else None


def _backfill_name(actor_subject: str) -> str:
    """Один раз спрашивает ФИО у Яндекса по сохранённому входу и запоминает его."""
    try:
        import httpx

        from gateway_mcp.services.auth import YANDEX_USERINFO_URL
        from gateway_mcp.services.storage_credentials import get_user_oauth_token

        token = get_user_oauth_token("yandex", actor_subject)
        if not token or not token.get("access_token"):
            return ""
        response = httpx.get(
            YANDEX_USERINFO_URL,
            params={"format": "json"},
            headers={"Authorization": f"OAuth {token['access_token']}"},
            timeout=4,
        )
        response.raise_for_status()
        name = name_from_yandex_info(response.json())
        if name:
            with _connect() as conn, conn.cursor() as cur:
                cur.execute(
                    "update user_oauth_tokens set metadata = metadata || %s::jsonb "
                    "where provider = 'yandex' and actor_subject = %s",
                    (json.dumps({"real_name": name}, ensure_ascii=False), actor_subject),
                )
                conn.commit()
        return name
    except Exception:  # noqa: BLE001 - имя — украшение, не должно ломать экран
        return ""


def person(subject: str) -> dict[str, str]:
    """{'name', 'email', 'label'} для yandex:… или почты; label = «ФИО (почта)»."""
    subject = str(subject or "").strip()
    key = subject.casefold()
    cached = _CACHE.get(key)
    if cached and (cached[1].get("name") or time.time() - cached[0] < _MISS_TTL):
        return cached[1]
    name = ""
    email = subject if "@" in subject else ""
    if subject and postgres_enabled():
        try:
            row = _row(subject)
        except Exception:  # noqa: BLE001
            row = None
        if row:
            email = str(row.get("email") or email)
            meta = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
            name = str(meta.get("real_name") or "").strip() or _backfill_name(str(row.get("actor_subject") or ""))
    label = f"{name} ({email})" if name and email else (name or email or subject)
    result = {"name": name, "email": email, "label": label}
    _CACHE[key] = (time.time(), result)
    return result
