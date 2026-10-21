"""Welcome-страница ядра «Сибсенсор AI» (корень сайта).

Показывает все функции ядра одной страницей: для вошедшего сотрудника — с его именем
и рабочими ссылками, для администратора — ещё и блок управления. Без входа — экран
входа рабочей почтой. Параллакс и анимации — в отдельном /static/hub.js (CSP без inline-скриптов).
"""

from __future__ import annotations

from asyncio import to_thread as run_in_threadpool
from html import escape

from starlette.responses import HTMLResponse, Response

from gateway_mcp.config import public_url
from gateway_mcp.services import storage_skills
from gateway_mcp.services.policy import has_scope
from gateway_mcp.tools.skills import skill_summaries
from gateway_mcp.web import web_actor

_CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data:; connect-src 'self'; form-action 'self'; "
    "frame-ancestors 'none'; base-uri 'none'"
)

# (иконка, заголовок, описание, ссылка)
_USER_TILES = (
    ("cabinet", "Мой кабинет", "Мои заявки, их статусы и все навыки компании на одной странице", "/me"),
    ("plus", "Добавить навык", "Форма за пару минут. Можно приложить файл — он сразу уйдёт в IT", "/skills/new"),
    ("agent", "Предложить агента", "Отдельная форма для агента: роль, задачи, какие навыки он использует", "/skills/submit-agent"),
    ("chart", "Мои навыки", "Какими навыками я пользуюсь, избранное и личная статистика", "/my/skills"),
    ("bell", "Уведомления", "Сообщения ядра: решения по заявкам и важные события", "/notifications"),
    ("plug", "Мои подключения", "Яндекс Диск и другие сервисы, к которым ассистент ходит от моего имени", "/credentials"),
)

_ADMIN_TILES = (
    ("gauge", "Обзор ядра", "/admin"),
    ("inbox", "Заявки на навыки", "/admin/skill-requests"),
    ("key", "Заявки на доступ", "/admin/access-requests"),
    ("users", "Доступ пользователей", "/admin/users"),
    ("people", "Люди и AI", "/admin/people"),
    ("list", "Журнал событий", "/admin/audit"),
    ("pulse", "Состояние шлюза", "/admin/metrics"),
    ("link", "Интеграции", "/admin/integrations"),
)

_CAPS = (
    ("Навыки компании", "Ассистент работает по правилам Сибсенсора: регламенты, IT-диагностика и всё, что добавят отделы"),
    ("Общие знания", "Документы и справочники компании, по которым ассистент отвечает со ссылками"),
    ("Сервисы компании", "Яндекс Диск, уведомления в Telegram и другие подключения — через одну точку с правами"),
    ("Журнал и контроль", "Каждое действие через ядро записывается, публикует новое только человек"),
)

_ICONS = {
    "cabinet": '<path d="M4 5h16v14H4z"/><path d="M4 9h16M9 9v10"/>',
    "plus": '<circle cx="12" cy="12" r="8"/><path d="M12 8v8M8 12h8"/>',
    "agent": '<rect x="5" y="8" width="14" height="11" rx="3"/><path d="M12 4v4M9 13h.01M15 13h.01"/>',
    "chart": '<path d="M5 19V9M12 19V5M19 19v-7"/>',
    "bell": '<path d="M6 16V11a6 6 0 0 1 12 0v5l2 2H4z"/><path d="M10 20h4"/>',
    "plug": '<path d="M9 3v5M15 3v5M7 8h10v4a5 5 0 0 1-10 0z"/><path d="M12 17v4"/>',
    "gauge": '<path d="M4 16a8 8 0 1 1 16 0"/><path d="M12 16l4-5"/>',
    "inbox": '<path d="M4 13l3-8h10l3 8v6H4z"/><path d="M4 13h5l1 2h4l1-2h5"/>',
    "key": '<circle cx="8" cy="15" r="4"/><path d="M11 12l8-8M16 7l2 2"/>',
    "users": '<circle cx="9" cy="9" r="3"/><path d="M3 19a6 6 0 0 1 12 0"/><path d="M16 6a3 3 0 0 1 0 6M18 19a6 6 0 0 0-2-4.5"/>',
    "people": '<circle cx="12" cy="8" r="3"/><path d="M6 20a6 6 0 0 1 12 0"/>',
    "list": '<path d="M9 6h11M9 12h11M9 18h11M4 6h.01M4 12h.01M4 18h.01"/>',
    "pulse": '<path d="M3 12h4l2-6 4 12 2-6h6"/>',
    "link": '<path d="M10 14a4 4 0 0 0 6 0l3-3a4 4 0 0 0-6-6l-1 1"/><path d="M14 10a4 4 0 0 0-6 0l-3 3a4 4 0 0 0 6 6l1-1"/>',
    "copy": '<rect x="8" y="8" width="12" height="12" rx="2"/><path d="M16 8V5a1 1 0 0 0-1-1H5a1 1 0 0 0-1 1v10a1 1 0 0 0 1 1h3"/>',
}


def _icon(name: str) -> str:
    return (
        '<svg class="ico" viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" '
        f'stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">{_ICONS[name]}</svg>'
    )


_CSS = """
:root{
  --bg:#0c0e11;--bg2:#12151a;--steel:#9aa7b4;--ink:#eef0ec;--soft:#a9b0b6;--mute:#6f7780;
  --line:rgba(205,215,225,.12);--glass:rgba(22,26,32,.62);--acc:#d6cf96;--acc2:#8fb3c9;
  --font:"Segoe UI Variable Display","Segoe UI",Inter,system-ui,-apple-system,Roboto,Arial,sans-serif;
  --mono:ui-monospace,SFMono-Regular,Consolas,Menlo,monospace;
}
*{box-sizing:border-box}
html{scroll-behavior:smooth}
body{margin:0;background:var(--bg);color:var(--ink);font-family:var(--font);-webkit-font-smoothing:antialiased;overflow-x:clip}
a{color:inherit}
a:focus-visible,button:focus-visible{outline:2px solid var(--acc);outline-offset:3px;border-radius:8px}
.scene{position:fixed;inset:0;z-index:0;pointer-events:none;overflow:hidden}
.layer{position:absolute;inset:-12%;will-change:transform}
.l-grid{background:
  linear-gradient(var(--line) 1px,transparent 1px) 0 0/64px 64px,
  linear-gradient(90deg,var(--line) 1px,transparent 1px) 0 0/64px 64px;
  -webkit-mask:radial-gradient(ellipse at 50% 35%,#000 0,transparent 70%);mask:radial-gradient(ellipse at 50% 35%,#000 0,transparent 70%);opacity:.55}
.l-glow{background:
  radial-gradient(38% 30% at 72% 22%,rgba(214,207,150,.20),transparent 70%),
  radial-gradient(34% 28% at 18% 70%,rgba(143,179,201,.16),transparent 70%)}
.l-rings svg{position:absolute;right:-6%;top:4%;width:min(78vw,980px);height:auto;opacity:.5}
.l-shards span{position:absolute;border-radius:50%;filter:blur(1px);
  background:radial-gradient(circle at 30% 30%,#f4f6f2,#9aa7b4 38%,#3a434d 70%,#15191e);box-shadow:0 20px 60px rgba(0,0,0,.6)}
.l-shards span:nth-child(1){width:120px;height:120px;left:8%;top:16%;opacity:.55}
.l-shards span:nth-child(2){width:46px;height:46px;left:62%;top:62%;opacity:.7}
.l-shards span:nth-child(3){width:220px;height:220px;left:80%;top:72%;opacity:.25;filter:blur(6px)}
.l-shards span:nth-child(4){width:22px;height:22px;left:36%;top:28%;opacity:.8}
.page{position:relative;z-index:1}
.top{position:sticky;top:0;z-index:5;display:flex;align-items:center;justify-content:space-between;gap:16px;
  padding:14px clamp(16px,4vw,48px);background:linear-gradient(var(--bg),rgba(12,14,17,.6));backdrop-filter:blur(10px);border-bottom:1px solid var(--line)}
.brand{display:flex;align-items:center;gap:12px;text-decoration:none;font-weight:700;letter-spacing:.14em;font-size:13px;text-transform:uppercase}
.brand b{display:grid;place-items:center;width:34px;height:34px;border-radius:10px;background:linear-gradient(135deg,#f1f2ee,#8d99a5 55%,#2b3239);color:#0c0e11;letter-spacing:0;font-size:15px}
.who{display:flex;align-items:center;gap:12px;font-size:14px;color:var(--soft)}
.live{display:inline-flex;align-items:center;gap:8px;white-space:nowrap;padding:6px 12px;border:1px solid var(--line);border-radius:999px;font-size:12px;letter-spacing:.06em;text-transform:uppercase;color:var(--soft)}
.live i{width:8px;height:8px;border-radius:50%;background:#7fd19b;box-shadow:0 0 0 0 rgba(127,209,155,.6);animation:ping 2.4s infinite}
@keyframes ping{0%{box-shadow:0 0 0 0 rgba(127,209,155,.55)}70%{box-shadow:0 0 0 10px rgba(127,209,155,0)}100%{box-shadow:0 0 0 0 rgba(127,209,155,0)}}
.out{color:var(--mute);text-decoration:none;font-size:13px}.out:hover{color:var(--ink)}
.wrap{max-width:1180px;margin:0 auto;padding:0 clamp(16px,4vw,48px)}
.hero{min-height:calc(100vh - 64px);display:flex;flex-direction:column;justify-content:center;padding:72px 0 96px}
.eyebrow{display:inline-flex;align-items:center;gap:10px;color:var(--acc);font-size:13px;font-weight:600;letter-spacing:.22em;text-transform:uppercase}
.eyebrow:before{content:"";width:36px;height:1px;background:var(--acc)}
h1{margin:22px 0 0;font-size:clamp(52px,9vw,132px);line-height:.92;font-weight:800;letter-spacing:-.035em;
  background:linear-gradient(180deg,#ffffff 0%,#d9dee2 38%,#8996a3 72%,#59636d 100%);-webkit-background-clip:text;background-clip:text;color:transparent}
h1 em{font-style:normal;background:linear-gradient(120deg,var(--acc),#f3eec9 45%,var(--acc2));-webkit-background-clip:text;background-clip:text;color:transparent}
.lead{max-width:680px;margin:28px 0 0;font-size:clamp(18px,2vw,22px);line-height:1.5;color:var(--soft)}
.lead strong{color:var(--ink);font-weight:600}
.cta{display:flex;flex-wrap:wrap;gap:12px;margin-top:40px}
.btn{display:inline-flex;align-items:center;gap:10px;min-height:52px;padding:0 24px;border-radius:14px;font-weight:600;font-size:16px;text-decoration:none;
  transition:transform .25s cubic-bezier(.16,1,.3,1),background .2s,border-color .2s}
.btn:hover{transform:translateY(-2px)}
.btn.main{background:linear-gradient(135deg,#f3eec9,var(--acc));color:#15181c;box-shadow:0 10px 40px rgba(214,207,150,.25)}
.btn.ghost{border:1px solid var(--line);background:rgba(255,255,255,.03);color:var(--ink)}
.btn.ghost:hover{border-color:rgba(214,207,150,.5)}
.stats{display:flex;flex-wrap:wrap;gap:12px 40px;margin-top:64px;padding-top:28px;border-top:1px solid var(--line);max-width:760px}
.stat b{display:block;font-size:34px;font-weight:700;letter-spacing:-.02em}
.stat span{color:var(--mute);font-size:14px}
.sec{padding:96px 0}
.sec-h{display:flex;align-items:end;justify-content:space-between;gap:24px;flex-wrap:wrap;margin-bottom:40px}
.sec-h h2{margin:0;font-size:clamp(32px,4.4vw,56px);line-height:1;font-weight:750;letter-spacing:-.025em}
.sec-h p{margin:0;max-width:420px;color:var(--soft);line-height:1.5}
.tiles{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:16px}
.tile{position:relative;display:flex;flex-direction:column;gap:14px;min-height:210px;padding:28px;border-radius:20px;text-decoration:none;
  background:var(--glass);border:1px solid var(--line);backdrop-filter:blur(14px);overflow:hidden;
  transition:transform .35s cubic-bezier(.16,1,.3,1),border-color .25s;transform-style:preserve-3d}
.tile:before{content:"";position:absolute;inset:0;background:radial-gradient(420px 220px at var(--mx,50%) var(--my,0%),rgba(214,207,150,.14),transparent 60%);opacity:0;transition:opacity .3s}
.tile:hover{border-color:rgba(214,207,150,.45)}
.tile:hover:before{opacity:1}
.tile .ico{width:34px;height:34px;color:var(--acc)}
.tile h3{margin:auto 0 0;font-size:22px;font-weight:650;letter-spacing:-.01em}
.tile p{margin:0;color:var(--soft);font-size:15px;line-height:1.5}
.tile .go{position:absolute;right:24px;top:26px;color:var(--mute);font-size:20px;transition:transform .3s,color .3s}
.tile:hover .go{transform:translate(4px,-4px);color:var(--acc)}
.caps{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:1px;background:var(--line);border:1px solid var(--line);border-radius:20px;overflow:hidden}
.cap{padding:32px 26px;background:var(--bg2)}
.cap small{display:block;color:var(--acc);font-family:var(--mono);font-size:12px;letter-spacing:.1em}
.cap h3{margin:18px 0 10px;font-size:20px;font-weight:650}
.cap p{margin:0;color:var(--soft);font-size:15px;line-height:1.5}
.connect{display:grid;grid-template-columns:1.1fr .9fr;gap:24px;align-items:stretch}
.panel{padding:36px;border-radius:24px;border:1px solid var(--line);background:var(--glass);backdrop-filter:blur(14px)}
.url{display:flex;flex-wrap:wrap;align-items:center;justify-content:space-between;gap:12px;margin-top:22px;padding:16px 18px;border-radius:14px;background:#07080a;border:1px solid var(--line);font-family:var(--mono);font-size:16px}
.url code{white-space:nowrap;overflow-x:auto;max-width:100%;color:var(--ink)}
.copy{display:inline-flex;align-items:center;gap:8px;border:1px solid var(--line);background:rgba(255,255,255,.04);color:var(--ink);padding:8px 14px;border-radius:10px;font:inherit;font-family:var(--font);font-size:14px;cursor:pointer}
.copy .ico{width:16px;height:16px}
.copy:hover{border-color:var(--acc)}
.steps{margin:0;padding:0;list-style:none;display:grid;gap:18px;counter-reset:s}
.steps li{display:grid;grid-template-columns:40px 1fr;gap:14px;align-items:start;color:var(--soft);line-height:1.5}
.steps li:before{counter-increment:s;content:counter(s,decimal-leading-zero);font-family:var(--mono);color:var(--acc);font-size:14px;padding-top:2px}
.steps b{color:var(--ink);font-weight:600}
.admin .tiles{grid-template-columns:repeat(4,minmax(0,1fr))}
.admin .tile{min-height:120px;padding:22px}
.admin .tile h3{font-size:18px}
.badge{display:inline-flex;padding:6px 12px;border-radius:999px;background:rgba(143,179,201,.12);color:var(--acc2);font-size:12px;letter-spacing:.08em;text-transform:uppercase}
.foot{padding:48px 0 64px;border-top:1px solid var(--line);color:var(--mute);font-size:14px;display:flex;justify-content:space-between;gap:16px;flex-wrap:wrap}
.foot a{color:var(--soft);text-decoration:none}
.js .rv{opacity:0;transform:translateY(28px);transition:opacity .9s cubic-bezier(.16,1,.3,1),transform .9s cubic-bezier(.16,1,.3,1)}
.js .rv.in{opacity:1;transform:none}
@media (max-width:980px){.tiles,.admin .tiles{grid-template-columns:repeat(2,minmax(0,1fr))}.caps{grid-template-columns:repeat(2,minmax(0,1fr))}.connect{grid-template-columns:1fr}}
@media (max-width:620px){.tiles,.admin .tiles,.caps{grid-template-columns:1fr}.who .name,.live span{display:none}.live{padding:8px}.brand{font-size:12px}.hero{padding:48px 0 64px}.panel{padding:24px}.sec{padding:64px 0}}
@media (prefers-reduced-motion:reduce){*{animation:none!important;transition:none!important}.js .rv{opacity:1;transform:none}.layer{transform:none!important}}
"""

_RINGS = (
    '<svg viewBox="0 0 600 600" aria-hidden="true"><defs>'
    '<linearGradient id="g" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#e9ece6"/>'
    '<stop offset=".5" stop-color="#8d99a5"/><stop offset="1" stop-color="#2a3138"/></linearGradient></defs>'
    '<g fill="none" stroke="url(#g)">'
    '<circle cx="300" cy="300" r="290" stroke-width=".6" stroke-dasharray="2 10"/>'
    '<circle cx="300" cy="300" r="230" stroke-width="1"/>'
    '<circle cx="300" cy="300" r="170" stroke-width=".6" stroke-dasharray="40 14"/>'
    '<circle cx="300" cy="300" r="110" stroke-width="1.4"/>'
    '<circle cx="300" cy="300" r="50" stroke-width=".8"/>'
    '<path d="M300 0v600M0 300h600" stroke-width=".4" stroke-dasharray="3 9"/>'
    "</g></svg>"
)


def _scene() -> str:
    return (
        '<div class="scene" aria-hidden="true">'
        '<div class="layer l-glow" data-depth="0.15"></div>'
        '<div class="layer l-grid" data-depth="0.3"></div>'
        f'<div class="layer l-rings" data-depth="0.6">{_RINGS}</div>'
        '<div class="layer l-shards" data-depth="1.1"><span></span><span></span><span></span><span></span></div>'
        "</div>"
    )


def _tiles(items) -> str:
    return "".join(
        f'<a class="tile rv" href="{href}">{_icon(icon)}<span class="go">↗</span>'
        f"<h3>{escape(title)}</h3><p>{escape(desc)}</p></a>"
        for icon, title, desc, href in items
    )


def _admin_tiles() -> str:
    return "".join(
        f'<a class="tile rv" href="{href}">{_icon(icon)}<span class="go">↗</span><h3>{escape(title)}</h3></a>'
        for icon, title, href in _ADMIN_TILES
    )


def _connect_block(mcp_url: str) -> str:
    return (
        '<section class="sec" id="connect"><div class="wrap">'
        '<div class="sec-h rv"><h2>Подключить ассистента</h2>'
        "<p>Пять минут — и ваш Claude работает с навыками и знаниями компании.</p></div>"
        '<div class="connect">'
        '<div class="panel rv"><span class="badge">Адрес ядра</span>'
        f'<div class="url"><code id="mcp-url">{escape(mcp_url)}</code>'
        f'<button class="copy" type="button" data-copy="#mcp-url">{_icon("copy")}<span>Копировать</span></button></div>'
        '<p style="color:var(--mute);margin:18px 0 0;line-height:1.5">Права администратора не нужны: '
        "доступ открывается сам для рабочей почты @sibsensor.com.</p></div>"
        '<div class="panel rv"><ol class="steps">'
        "<li><span>Установите <b>приложение Claude</b> с claude.ai/download</span></li>"
        "<li><span><b>Настройки → Коннекторы → Добавить</b>, вставьте адрес ядра</span></li>"
        "<li><span>Нажмите <b>«Войти через Яндекс»</b> и войдите рабочей почтой</span></li>"
        "<li><span>Спросите ассистента: <b>«Какие навыки есть у компании?»</b></span></li>"
        "</ol></div></div></div></section>"
    )


def _caps_block() -> str:
    cells = "".join(
        f'<div class="cap rv"><small>{i:02d}</small><h3>{escape(t)}</h3><p>{escape(d)}</p></div>'
        for i, (t, d) in enumerate(_CAPS, 1)
    )
    return (
        '<section class="sec" id="core"><div class="wrap">'
        '<div class="sec-h rv"><h2>Что даёт ядро</h2>'
        "<p>Один общий мозг компании на нашем сервере — для ассистента каждого сотрудника.</p></div>"
        f'<div class="caps">{cells}</div></div></section>'
    )


def _page_html(*, actor, skills: int, agents: int, mcp_url: str) -> str:
    if actor is None:
        who = '<a class="out" href="/auth/yandex/login?next=/">Войти</a>'
        hero_lead = (
            "Корпоративное AI-ядро компании. Навыки, агенты и знания Сибсенсора — "
            "в одном месте, на нашем сервере. <strong>Вход — рабочей почтой.</strong>"
        )
        cta = (
            '<a class="btn main" href="/auth/yandex/login?next=/">Войти рабочей почтой</a>'
            '<a class="btn ghost" href="#connect">Как подключить ассистента</a>'
        )
        work = ""
        admin = ""
    else:
        name = escape(actor.display)
        is_admin = has_scope(actor, "access:admin")
        who = (
            f'<span class="name">{name}</span>'
            '<a class="out" href="/auth/logout">Выйти</a>'
        )
        hero_lead = (
            "Здесь навыки, агенты и знания компании, к которым подключён ваш ассистент. "
            f"Вы вошли как <strong>{name}</strong>."
        )
        cta = (
            '<a class="btn main" href="/me">Мой кабинет</a>'
            '<a class="btn ghost" href="/skills/new">Добавить навык</a>'
        )
        work = (
            '<section class="sec" id="work"><div class="wrap">'
            '<div class="sec-h rv"><h2>Ваше рабочее место</h2>'
            "<p>Всё, что можно сделать в ядре, — в один клик.</p></div>"
            f'<div class="tiles">{_tiles(_USER_TILES)}</div></div></section>'
        )
        admin = (
            '<section class="sec admin" id="admin"><div class="wrap">'
            '<div class="sec-h rv"><h2>Управление ядром</h2>'
            "<p>Видно только администраторам.</p></div>"
            f'<div class="tiles">{_admin_tiles()}</div></div></section>'
            if is_admin
            else ""
        )
    stats = (
        (f'<div class="stat"><b>{skills}</b><span>навыков в ядре</span></div>' if skills else "")
        + (f'<div class="stat"><b>{agents}</b><span>агентов</span></div>' if agents else "")
        + '<div class="stat"><b>1</b><span>вход — рабочая почта</span></div>'
        '<div class="stat"><b>24/7</b><span>на сервере компании</span></div>'
    )
    return f"""<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="dark">
<title>Сибсенсор AI · ядро</title>
<style>{_CSS}</style>
<script src="/static/hub.js" defer></script>
</head>
<body>
{_scene()}
<div class="page">
<header class="top">
<a class="brand" href="/"><b>С</b>Сибсенсор&nbsp;AI</a>
<div class="who"><span class="live" title="Ядро онлайн"><i></i><span>ядро онлайн</span></span>{who}</div>
</header>
<main>
<section class="hero"><div class="wrap">
<span class="eyebrow rv">Вы на ядре</span>
<h1 class="rv">Сибсенсор<br><em>AI-ядро</em></h1>
<p class="lead rv">{hero_lead}</p>
<div class="cta rv">{cta}</div>
<div class="stats rv">{stats}</div>
</div></section>
{work}
{_caps_block()}
{_connect_block(mcp_url)}
{admin}
</main>
<div class="wrap"><footer class="foot"><span>Сибсенсор AI · корпоративное ядро на сервере компании</span>
<a href="/healthz">Проверка работы ядра</a></footer></div>
</div>
</body>
</html>"""


_JS = r"""
(function(){
  document.documentElement.classList.add('js');
  var reduce = window.matchMedia && matchMedia('(prefers-reduced-motion: reduce)').matches;
  function ready(fn){ if(document.readyState!=='loading') fn(); else document.addEventListener('DOMContentLoaded', fn); }
  ready(function(){
    // появление блоков при прокрутке
    var items = document.querySelectorAll('.rv');
    if('IntersectionObserver' in window && !reduce){
      var io = new IntersectionObserver(function(es){
        es.forEach(function(e){ if(e.isIntersecting){ e.target.classList.add('in'); io.unobserve(e.target); } });
      }, {threshold: 0.12});
      items.forEach(function(el, i){ el.style.transitionDelay = (i % 6) * 60 + 'ms'; io.observe(el); });
      // страховка: текст не должен остаться невидимым, если анимация не сработала
      setTimeout(function(){ items.forEach(function(el){ el.classList.add('in'); }); }, 3000);
    } else { items.forEach(function(el){ el.classList.add('in'); }); }

    // копирование адреса ядра
    document.querySelectorAll('[data-copy]').forEach(function(b){
      b.addEventListener('click', function(){
        var src = document.querySelector(b.getAttribute('data-copy'));
        if(!src || !navigator.clipboard) return;
        navigator.clipboard.writeText(src.textContent.trim()).then(function(){
          var s = b.querySelector('span'); var t = s.textContent; s.textContent = 'Скопировано';
          setTimeout(function(){ s.textContent = t; }, 1600);
        });
      });
    });

    if(reduce) return;
    // параллакс: слои сдвигаются от прокрутки и движения мыши
    var layers = Array.prototype.slice.call(document.querySelectorAll('.layer'));
    var mx = 0, my = 0, tx = 0, ty = 0, sy = window.scrollY;
    var fine = window.matchMedia && matchMedia('(pointer: fine)').matches;
    if(fine){
      window.addEventListener('pointermove', function(e){
        mx = (e.clientX / innerWidth - 0.5); my = (e.clientY / innerHeight - 0.5);
      }, {passive: true});
    }
    window.addEventListener('scroll', function(){ sy = window.scrollY; }, {passive: true});
    (function loop(){
      tx += (mx - tx) * 0.06; ty += (my - ty) * 0.06;
      layers.forEach(function(l){
        var d = parseFloat(l.getAttribute('data-depth')) || 0;
        l.style.transform = 'translate3d(' + (-tx * 40 * d) + 'px,' + (-ty * 40 * d - sy * 0.12 * d) + 'px,0)';
      });
      requestAnimationFrame(loop);
    })();

    // лёгкий 3D-наклон карточек и подсветка под курсором
    if(fine){
      document.querySelectorAll('.tile').forEach(function(t){
        t.addEventListener('pointermove', function(e){
          var r = t.getBoundingClientRect();
          var x = (e.clientX - r.left) / r.width, y = (e.clientY - r.top) / r.height;
          t.style.setProperty('--mx', (x * 100) + '%'); t.style.setProperty('--my', (y * 100) + '%');
          t.style.transform = 'perspective(900px) rotateX(' + ((0.5 - y) * 6) + 'deg) rotateY(' + ((x - 0.5) * 8) + 'deg) translateY(-3px)';
        });
        t.addEventListener('pointerleave', function(){ t.style.transform = ''; });
      });
    }
  });
})();
"""


def _secure(response: Response, *, private: bool) -> Response:
    response.headers["Cache-Control"] = "no-store" if private else "public, max-age=300"
    response.headers["Referrer-Policy"] = "same-origin"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Content-Security-Policy"] = _CSP
    return response


def register_hub_routes(mcp):
    @mcp.custom_route("/", methods=["GET"], include_in_schema=False)
    async def hub_home(request):
        actor = web_actor(request)
        skills = agents = 0
        if actor is not None:
            try:
                skills = len(await run_in_threadpool(skill_summaries))
            except Exception:  # noqa: BLE001 - страница не должна падать из-за счётчика
                skills = 0
            try:
                agents = len(await run_in_threadpool(storage_skills.list_agents))
            except Exception:  # noqa: BLE001
                agents = 0
        html = _page_html(actor=actor, skills=skills, agents=agents, mcp_url=public_url() + "/mcp")
        return _secure(HTMLResponse(html), private=True)

    @mcp.custom_route("/static/hub.js", methods=["GET"], include_in_schema=False)
    async def hub_js(request):
        return _secure(Response(_JS, media_type="application/javascript"), private=False)
