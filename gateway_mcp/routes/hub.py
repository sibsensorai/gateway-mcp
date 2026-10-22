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
    ("book", "Навыки компании", "Ассистент работает по правилам Сибсенсора: регламенты, IT-диагностика и всё, что добавят отделы"),
    ("search", "Общие знания", "Документы и справочники компании, по которым ассистент отвечает со ссылками"),
    ("link", "Сервисы компании", "Яндекс Диск, уведомления в Telegram и другие подключения — через одну точку с правами"),
    ("shield", "Журнал и контроль", "Каждое действие через ядро записывается, публикует новое только человек"),
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
    "book": '<path d="M5 4h10a4 4 0 0 1 4 4v12H9a4 4 0 0 1-4-4z"/><path d="M5 16a4 4 0 0 1 4-4h10"/>',
    "search": '<circle cx="11" cy="11" r="6"/><path d="M20 20l-4.5-4.5"/>',
    "shield": '<path d="M12 3l7 3v6c0 4.5-3 7.5-7 9-4-1.5-7-4.5-7-9V6z"/><path d="M9 12l2 2 4-4"/>',
    "check": '<path d="M5 12l5 5 9-10"/>',
    "arrow": '<path d="M5 12h14M13 6l6 6-6 6"/>',
}


def _icon(name: str, cls: str = "ico") -> str:
    return (
        f'<svg class="{cls}" viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" '
        f'stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">{_ICONS[name]}</svg>'
    )


_CSS = """
:root{
  --bg:#f5f8fd;--paper:#ffffff;--tint:#eef4ff;--chip:#e8f1ff;
  --ink:#0c1a33;--soft:#46566e;--mute:#7a89a0;--line:#e2e9f4;--line2:#c9d9f1;
  --blue:#1d6ef0;--blue-d:#1559c7;--sky:#14a7e6;--ok:#13a06a;
  --sh:0 1px 2px rgba(16,40,90,.05),0 10px 28px rgba(16,40,90,.07);
  --sh-lg:0 2px 6px rgba(16,40,90,.05),0 28px 64px rgba(22,70,160,.16);
  --font:"Segoe UI Variable Display","Segoe UI",Inter,system-ui,-apple-system,Roboto,Arial,sans-serif;
  --mono:ui-monospace,SFMono-Regular,Consolas,Menlo,monospace;
}
*{box-sizing:border-box}
html{scroll-behavior:smooth}
body{margin:0;background:var(--bg);color:var(--ink);font-family:var(--font);-webkit-font-smoothing:antialiased;overflow-x:clip}
a{color:inherit}
a:focus-visible,button:focus-visible{outline:2px solid var(--blue);outline-offset:3px;border-radius:10px}

/* фон: мягкие голубые пятна и точечная сетка, двигаются медленно */
.bg{position:fixed;inset:0;z-index:0;pointer-events:none;overflow:hidden}
.blob{position:absolute;border-radius:50%;filter:blur(60px);will-change:transform}
.blob.b1{width:620px;height:620px;right:-160px;top:-180px;background:radial-gradient(circle,#cfe2ff 0,#cfe2ff00 70%)}
.blob.b2{width:520px;height:520px;left:-200px;top:38%;background:radial-gradient(circle,#d4f1fd 0,#d4f1fd00 70%)}
.blob.b3{width:460px;height:460px;right:12%;bottom:-220px;background:radial-gradient(circle,#e3e4ff 0,#e3e4ff00 70%)}
.dots{position:absolute;inset:-10%;background:radial-gradient(#c3d4ee 1.1px,transparent 1.6px) 0 0/24px 24px;
  -webkit-mask:radial-gradient(ellipse 70% 55% at 70% 20%,#000 0,transparent 75%);mask:radial-gradient(ellipse 70% 55% at 70% 20%,#000 0,transparent 75%);opacity:.8}

.page{position:relative;z-index:1}
.top{position:sticky;top:0;z-index:20;display:flex;align-items:center;justify-content:space-between;gap:16px;
  padding:14px clamp(16px,4vw,48px);background:rgba(255,255,255,.78);backdrop-filter:blur(14px) saturate(1.4);border-bottom:1px solid var(--line)}
.brand{display:flex;align-items:center;gap:12px;text-decoration:none;font-weight:700;font-size:16px;letter-spacing:-.01em}
.brand b{display:grid;place-items:center;width:36px;height:36px;border-radius:11px;color:#fff;font-size:16px;
  background:linear-gradient(135deg,var(--sky),var(--blue));box-shadow:0 6px 16px rgba(29,110,240,.35)}
.brand small{display:block;color:var(--mute);font-weight:500;font-size:12px;letter-spacing:0}
.who{display:flex;align-items:center;gap:14px;font-size:14px;color:var(--soft)}
.live{display:inline-flex;align-items:center;gap:8px;white-space:nowrap;padding:6px 12px;border-radius:999px;background:#e9f8f1;color:#0f7a51;font-size:13px;font-weight:600}
.live i{width:8px;height:8px;border-radius:50%;background:var(--ok);box-shadow:0 0 0 0 rgba(19,160,106,.5);animation:ping 2.4s infinite}
@keyframes ping{0%{box-shadow:0 0 0 0 rgba(19,160,106,.45)}70%{box-shadow:0 0 0 9px rgba(19,160,106,0)}100%{box-shadow:0 0 0 0 rgba(19,160,106,0)}}
.out{color:var(--mute);text-decoration:none;font-size:14px}.out:hover{color:var(--blue)}

.wrap{max-width:1200px;margin:0 auto;padding:0 clamp(16px,4vw,48px)}

/* первый экран */
.hero{padding:72px 0 88px}
.hero .wrap{display:grid;grid-template-columns:1.02fr .98fr;gap:56px;align-items:center;min-height:calc(100vh - 230px)}
.pill{display:inline-flex;align-items:center;gap:8px;padding:7px 14px;border-radius:999px;background:var(--chip);color:var(--blue-d);font-size:13px;font-weight:650}
.pill i{width:7px;height:7px;border-radius:50%;background:var(--blue)}
h1{margin:22px 0 0;font-size:clamp(46px,6.6vw,88px);line-height:.98;font-weight:800;letter-spacing:-.04em;color:var(--ink)}
h1 em{font-style:normal;background:linear-gradient(100deg,var(--blue) 10%,var(--sky) 90%);-webkit-background-clip:text;background-clip:text;color:transparent}
.lead{max-width:560px;margin:24px 0 0;font-size:clamp(17px,1.6vw,20px);line-height:1.55;color:var(--soft)}
.lead strong{color:var(--ink);font-weight:650}
.cta{display:flex;flex-wrap:wrap;gap:12px;margin-top:34px}
.btn{display:inline-flex;align-items:center;gap:10px;min-height:52px;padding:0 24px;border-radius:14px;font-weight:650;font-size:16px;text-decoration:none;
  transition:transform .25s cubic-bezier(.16,1,.3,1),box-shadow .25s,background .2s,border-color .2s}
.btn .ico{width:18px;height:18px}
.btn:hover{transform:translateY(-2px)}
.btn.main{background:var(--blue);color:#fff;box-shadow:0 10px 26px rgba(29,110,240,.32)}
.btn.main:hover{background:var(--blue-d);box-shadow:0 14px 32px rgba(29,110,240,.4)}
.btn.ghost{background:var(--paper);color:var(--ink);border:1px solid var(--line2);box-shadow:var(--sh)}
.btn.ghost:hover{border-color:var(--blue)}
.stats{display:flex;flex-wrap:wrap;margin-top:44px;border-top:1px solid var(--line);padding-top:24px;gap:0}
.stat{padding:0 28px;border-left:1px solid var(--line)}
.stat:first-child{padding-left:0;border-left:0}
.stat b{display:block;font-size:30px;font-weight:750;letter-spacing:-.02em;color:var(--ink)}
.stat span{color:var(--mute);font-size:14px}

/* визуал справа: карточка ядра и плавающие плашки */
.visual{position:relative;height:540px}
.core{position:absolute;left:50%;top:50%;width:min(440px,92%);margin-left:calc(min(440px,92%) / -2);margin-top:-210px;
  background:var(--paper);border:1px solid var(--line);border-radius:26px;box-shadow:var(--sh-lg);padding:18px}
.core-h{display:flex;align-items:center;justify-content:space-between;padding:2px 4px 14px}
.core-h .dots3{display:flex;gap:6px}
.core-h .dots3 span{width:10px;height:10px;border-radius:50%;background:#dbe5f3}
.core-h .t{font-size:13px;font-weight:650;color:var(--soft)}
.core-h .t i{display:inline-block;width:7px;height:7px;border-radius:50%;background:var(--ok);margin-right:6px;vertical-align:1px}
.net{border-radius:18px;background:linear-gradient(180deg,#f3f8ff,#eaf2ff);border:1px solid var(--line);padding:8px}
.net svg{display:block;width:100%;height:auto}
.net .pulse{stroke-width:2;stroke-dasharray:10 260;animation:flow 4.2s linear infinite}
.net .pulse.p2{animation-duration:5.6s}
.net .pulse.p3{animation-delay:-2s}
@keyframes flow{to{stroke-dashoffset:-270}}
.core-f{display:flex;gap:8px;padding:14px 4px 2px;flex-wrap:wrap}
.core-f span{font-family:var(--mono);font-size:12px;padding:5px 10px;border-radius:8px;background:var(--tint);color:var(--blue-d)}
.fchip{position:absolute;will-change:transform}
.fchip .card{display:flex;align-items:center;gap:12px;padding:12px 16px 12px 12px;border-radius:16px;background:rgba(255,255,255,.92);
  border:1px solid var(--line);box-shadow:var(--sh-lg);backdrop-filter:blur(8px);animation:bob 6s ease-in-out infinite;white-space:nowrap}
.fchip:nth-child(3) .card{animation-delay:-1.5s}.fchip:nth-child(4) .card{animation-delay:-3s}.fchip:nth-child(5) .card{animation-delay:-4.5s}
@keyframes bob{50%{transform:translateY(-8px)}}
.fchip .ic{display:grid;place-items:center;width:38px;height:38px;border-radius:11px;background:var(--chip);color:var(--blue)}
.fchip .ic .ico{width:20px;height:20px}
.fchip small{display:block;color:var(--mute);font-size:12px}
.fchip strong{display:block;font-size:15px;font-weight:700;color:var(--ink)}
.fchip code{font-family:var(--mono);font-size:13px;color:var(--blue-d)}
.fchip .okc{color:var(--ok);font-weight:700}
.f1{left:-4%;top:6%}.f2{right:-6%;top:20%}.f3{left:0;bottom:6%}.f4{right:-2%;bottom:14%}

/* секции */
.sec{padding:96px 0}
.sec.alt{background:var(--paper);border-top:1px solid var(--line);border-bottom:1px solid var(--line)}
.sec-h{display:grid;grid-template-columns:1fr auto;align-items:end;gap:24px;margin-bottom:40px}
.label{display:block;color:var(--blue);font-size:13px;font-weight:700;letter-spacing:.14em;text-transform:uppercase;margin-bottom:12px}
.sec-h h2{margin:0;font-size:clamp(30px,3.8vw,46px);line-height:1.05;font-weight:780;letter-spacing:-.03em}
.sec-h p{margin:0;max-width:400px;color:var(--soft);line-height:1.55}

.tiles{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:18px}
.tile{position:relative;display:flex;flex-direction:column;gap:12px;min-height:220px;padding:26px;border-radius:20px;text-decoration:none;
  background:var(--paper);border:1px solid var(--line);box-shadow:var(--sh);overflow:hidden;
  transition:transform .35s cubic-bezier(.16,1,.3,1),box-shadow .3s,border-color .25s}
.tile:before{content:"";position:absolute;inset:0;background:radial-gradient(360px 200px at var(--mx,50%) var(--my,0%),rgba(29,110,240,.07),transparent 60%);opacity:0;transition:opacity .3s}
.tile:hover{border-color:var(--line2);box-shadow:var(--sh-lg)}
.tile:hover:before{opacity:1}
.tile .ic{display:grid;place-items:center;width:46px;height:46px;border-radius:13px;background:var(--chip);color:var(--blue);transition:background .25s,color .25s}
.tile:hover .ic{background:var(--blue);color:#fff}
.tile .ic .ico{width:22px;height:22px}
.tile h3{margin:6px 0 0;font-size:20px;font-weight:700;letter-spacing:-.01em}
.tile p{margin:0;color:var(--soft);font-size:15px;line-height:1.5}
.tile .go{display:inline-flex;align-items:center;gap:6px;margin-top:auto;color:var(--blue);font-size:14px;font-weight:650}
.tile .go .ico{width:16px;height:16px;transition:transform .3s}
.tile:hover .go .ico{transform:translateX(4px)}

.caps{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:18px}
.cap{padding:28px 24px;border-radius:20px;background:linear-gradient(180deg,#f7faff,#fff);border:1px solid var(--line)}
.cap .ic{display:grid;place-items:center;width:44px;height:44px;border-radius:12px;color:#fff;background:linear-gradient(135deg,var(--sky),var(--blue));box-shadow:0 8px 18px rgba(29,110,240,.25)}
.cap .ic .ico{width:22px;height:22px}
.cap h3{margin:18px 0 8px;font-size:18px;font-weight:700}
.cap p{margin:0;color:var(--soft);font-size:15px;line-height:1.5}

.connect{display:grid;grid-template-columns:1.05fr .95fr;gap:20px}
.panel{padding:32px;border-radius:22px;background:var(--paper);border:1px solid var(--line);box-shadow:var(--sh)}
.panel h3{margin:0 0 6px;font-size:20px}
.panel .muted{margin:0;color:var(--mute);line-height:1.5}
.url{display:flex;flex-wrap:wrap;align-items:center;justify-content:space-between;gap:12px;margin:20px 0 16px;padding:14px 14px 14px 18px;border-radius:14px;background:var(--tint);border:1px solid var(--line2)}
.url code{font-family:var(--mono);font-size:16px;white-space:nowrap;overflow-x:auto;max-width:100%;color:var(--ink)}
.copy{display:inline-flex;align-items:center;gap:8px;border:0;background:var(--blue);color:#fff;padding:10px 16px;border-radius:10px;font:inherit;font-size:14px;font-weight:650;cursor:pointer}
.copy:hover{background:var(--blue-d)}
.copy .ico{width:16px;height:16px}
.steps{margin:0;padding:0;list-style:none;display:grid;gap:18px;counter-reset:s}
.steps li{display:grid;grid-template-columns:36px 1fr;gap:14px;align-items:start;color:var(--soft);line-height:1.5}
.steps li:before{counter-increment:s;content:counter(s);display:grid;place-items:center;width:32px;height:32px;border-radius:50%;background:var(--chip);color:var(--blue);font-weight:700;font-size:14px}
.steps b{color:var(--ink);font-weight:650}

.admin-box{padding:36px;border-radius:26px;background:linear-gradient(135deg,#0f2a5c,#1d4fa8);color:#fff;box-shadow:var(--sh-lg)}
.admin-box .sec-h p{color:#c7d8f7}
.admin-box .label{color:#8fd3ff}
.admin-tiles{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px}
.atile{display:flex;align-items:center;gap:12px;padding:16px 18px;border-radius:14px;text-decoration:none;color:#fff;
  background:rgba(255,255,255,.08);border:1px solid rgba(255,255,255,.14);transition:background .2s,transform .25s}
.atile:hover{background:rgba(255,255,255,.16);transform:translateY(-2px)}
.atile .ico{width:20px;height:20px;color:#8fd3ff;flex:none}
.atile span{font-size:15px;font-weight:600}

.foot{padding:40px 0 56px;color:var(--mute);font-size:14px;display:flex;justify-content:space-between;gap:16px;flex-wrap:wrap}
.foot a{color:var(--soft);text-decoration:none}.foot a:hover{color:var(--blue)}

.js .rv{opacity:0;transform:translateY(24px);transition:opacity .8s cubic-bezier(.16,1,.3,1),transform .8s cubic-bezier(.16,1,.3,1)}
.js .rv.in{opacity:1;transform:none}

@media (max-width:1040px){
  .hero .wrap{grid-template-columns:1fr;min-height:0}
  .visual{height:480px;max-width:620px;margin:0 auto;width:100%}
  .tiles{grid-template-columns:repeat(2,minmax(0,1fr))}.caps{grid-template-columns:repeat(2,minmax(0,1fr))}
  .connect{grid-template-columns:1fr}.admin-tiles{grid-template-columns:repeat(2,minmax(0,1fr))}
}
@media (max-width:640px){
  .hero{padding:40px 0 56px}.sec{padding:64px 0}
  .tiles,.caps,.admin-tiles{grid-template-columns:1fr}
  .sec-h{grid-template-columns:1fr}
  .who .name,.live span{display:none}.live{padding:8px}
  .visual{height:400px}.f3,.f4{display:none}.f1{left:0;top:2%}.f2{right:0;top:auto;bottom:4%}
  .stats{display:grid;grid-template-columns:1fr 1fr;gap:18px}.stat,.stat:first-child{padding:0;border:0}.stat b{font-size:24px}
  .panel,.admin-box{padding:22px}
}
@media (prefers-reduced-motion:reduce){*{animation:none!important;transition:none!important}.js .rv{opacity:1;transform:none}[data-depth]{transform:none!important}}
"""


def _net_svg() -> str:
    """Нейросеть в карточке ядра: слои узлов, связи и бегущие по части связей импульсы."""
    cols = [(40, [70, 160, 250, 340]), (160, [40, 125, 210, 295, 380]), (280, [70, 160, 250, 340]), (390, [150, 260])]
    lines, pulses, nodes = [], [], []
    for (x1, ys1), (x2, ys2) in zip(cols, cols[1:]):
        for i, y1 in enumerate(ys1):
            for j, y2 in enumerate(ys2):
                lines.append(f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}"/>')
                if (i + 2 * j) % 5 == 0:
                    kind = ("p2" if (i + j) % 2 else "") + (" p3" if j % 3 == 0 else "")
                    color = "#14a7e6" if (i + j) % 2 else "#1d6ef0"
                    pulses.append(
                        f'<line class="pulse {kind}" stroke="{color}" x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}"/>'
                    )
    for n, (x, ys) in enumerate(cols):
        for k, y in enumerate(ys):
            if (n + k) % 3 == 0:
                nodes.append(f'<circle cx="{x}" cy="{y}" r="9" fill="#1d6ef0" stroke="#fff" stroke-width="3"/>')
            else:
                nodes.append(f'<circle cx="{x}" cy="{y}" r="7" fill="#fff" stroke="#8fb4ee" stroke-width="2"/>')
    return (
        '<svg viewBox="0 0 430 420" aria-hidden="true">'
        f'<g stroke="rgba(29,110,240,.16)" stroke-width="1.2">{"".join(lines)}</g>'
        f'<g fill="none" stroke-linecap="round">{"".join(pulses)}</g>'
        f'<g>{"".join(nodes)}</g></svg>'
    )


def _plural(n: int, one: str, few: str, many: str) -> str:
    if n % 10 == 1 and n % 100 != 11:
        return one
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return few
    return many


def _visual(*, skills: int, logged_in: bool) -> str:
    if logged_in and skills:
        first = f"<small>в каталоге ядра</small><strong>{skills} {_plural(skills, 'навык', 'навыка', 'навыков')}</strong>"
    else:
        first = "<small>для всех отделов</small><strong>Навыки компании</strong>"
    return (
        '<div class="visual rv" aria-hidden="true">'
        '<div class="core" data-depth="0.25">'
        '<div class="core-h"><div class="dots3"><span></span><span></span><span></span></div>'
        '<span class="t"><i></i>Сибсенсор AI · ядро</span></div>'
        f'<div class="net">{_net_svg()}</div>'
        '<div class="core-f"><span>MCP</span><span>OAuth</span><span>audit log</span><span>skills</span></div>'
        "</div>"
        f'<div class="fchip f1" data-depth="1.1"><div class="card"><span class="ic">{_icon("book")}</span><span>{first}</span></div></div>'
        f'<div class="fchip f2" data-depth="0.8"><div class="card"><span class="ic">{_icon("key")}</span>'
        "<span><small>вход</small><strong>@sibsensor.com</strong></span></div></div>"
        f'<div class="fchip f3" data-depth="1.4"><div class="card"><span class="ic">{_icon("bell")}</span>'
        "<span><small>уведомления</small><strong>Telegram</strong></span></div></div>"
        '<div class="fchip f4" data-depth="0.6"><div class="card"><code>agent.run()</code><span class="okc">✓</span></div></div>'
        "</div>"
    )


def _background() -> str:
    return (
        '<div class="bg" aria-hidden="true">'
        '<div class="dots" data-depth="0.15"></div>'
        '<div class="blob b1" data-depth="0.35"></div>'
        '<div class="blob b2" data-depth="0.5"></div>'
        '<div class="blob b3" data-depth="0.3"></div>'
        "</div>"
    )


def _sec_head(label: str, title: str, text: str) -> str:
    return (
        f'<div class="sec-h rv"><div><span class="label">{escape(label)}</span><h2>{escape(title)}</h2></div>'
        f"<p>{escape(text)}</p></div>"
    )


def _tiles(items) -> str:
    return "".join(
        f'<a class="tile rv" href="{href}"><span class="ic">{_icon(icon)}</span>'
        f"<h3>{escape(title)}</h3><p>{escape(desc)}</p>"
        f'<span class="go">Открыть {_icon("arrow")}</span></a>'
        for icon, title, desc, href in items
    )


def _admin_block() -> str:
    tiles = "".join(
        f'<a class="atile" href="{href}">{_icon(icon)}<span>{escape(title)}</span></a>'
        for icon, title, href in _ADMIN_TILES
    )
    return (
        '<section class="sec" id="admin"><div class="wrap"><div class="admin-box rv">'
        + _sec_head("Только для администраторов", "Управление ядром", "Доступы, заявки, журнал и состояние шлюза.")
        + f'<div class="admin-tiles">{tiles}</div></div></div></section>'
    )


def _connect_block(mcp_url: str) -> str:
    return (
        '<section class="sec" id="connect"><div class="wrap">'
        + _sec_head("За пять минут", "Подключить ассистента", "Ваш Claude начнёт работать с навыками и знаниями компании.")
        + '<div class="connect">'
        '<div class="panel rv"><h3>Адрес ядра</h3>'
        '<p class="muted">Вставьте его в приложении Claude: Настройки → Коннекторы → Добавить.</p>'
        f'<div class="url"><code id="mcp-url">{escape(mcp_url)}</code>'
        f'<button class="copy" type="button" data-copy="#mcp-url">{_icon("copy")}<span>Копировать</span></button></div>'
        '<p class="muted">Права администратора не нужны: доступ открывается сам для рабочей почты @sibsensor.com.</p></div>'
        '<div class="panel rv"><ol class="steps">'
        "<li><span>Установите <b>приложение Claude</b> с claude.ai/download</span></li>"
        "<li><span><b>Настройки → Коннекторы → Добавить</b>, вставьте адрес ядра</span></li>"
        "<li><span>Нажмите <b>«Войти через Яндекс»</b> и войдите рабочей почтой</span></li>"
        "<li><span>Спросите ассистента: <b>«Какие навыки есть у компании?»</b></span></li>"
        "</ol></div></div></div></section>"
    )


def _caps_block() -> str:
    cells = "".join(
        f'<div class="cap rv"><span class="ic">{_icon(icon)}</span><h3>{escape(t)}</h3><p>{escape(d)}</p></div>'
        for icon, t, d in _CAPS
    )
    return (
        '<section class="sec alt" id="core"><div class="wrap">'
        + _sec_head("Что внутри", "Что даёт ядро", "Один общий мозг компании на нашем сервере — для ассистента каждого сотрудника.")
        + f'<div class="caps">{cells}</div></div></section>'
    )


def _page_html(*, actor, skills: int, agents: int, mcp_url: str) -> str:
    if actor is None:
        who = '<a class="btn ghost" style="min-height:40px;padding:0 16px;font-size:14px" href="/auth/yandex/login?next=/">Войти</a>'
        hero_lead = (
            "Корпоративное AI-ядро компании. Навыки, агенты и знания Сибсенсора — "
            "в одном месте, на нашем сервере. <strong>Вход — рабочей почтой.</strong>"
        )
        cta = (
            f'<a class="btn main" href="/auth/yandex/login?next=/">Войти рабочей почтой {_icon("arrow")}</a>'
            '<a class="btn ghost" href="#connect">Как подключить ассистента</a>'
        )
        work = ""
        admin = ""
    else:
        name = escape(actor.display)
        is_admin = has_scope(actor, "access:admin")
        who = f'<span class="name">{name}</span><a class="out" href="/auth/logout">Выйти</a>'
        hero_lead = (
            "Здесь навыки, агенты и знания компании, к которым подключён ваш ассистент. "
            f"Вы вошли как <strong>{name}</strong>."
        )
        cta = (
            f'<a class="btn main" href="/me">Мой кабинет {_icon("arrow")}</a>'
            '<a class="btn ghost" href="/skills/new">Добавить навык</a>'
        )
        work = (
            '<section class="sec" id="work"><div class="wrap">'
            + _sec_head("Рабочее место", "Всё, что можно сделать в ядре", "Каждая карточка — рабочая ссылка, в один клик.")
            + f'<div class="tiles">{_tiles(_USER_TILES)}</div></div></section>'
        )
        admin = _admin_block() if is_admin else ""
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
<meta name="color-scheme" content="light">
<title>Сибсенсор AI · ядро</title>
<style>{_CSS}</style>
<script src="/static/hub.js" defer></script>
</head>
<body>
{_background()}
<div class="page">
<header class="top">
<a class="brand" href="/"><b>С</b><span>Сибсенсор AI<small>корпоративное ядро</small></span></a>
<div class="who"><span class="live" title="Ядро онлайн"><i></i><span>Ядро онлайн</span></span>{who}</div>
</header>
<main>
<section class="hero"><div class="wrap">
<div>
<span class="pill rv"><i></i>Вы на ядре</span>
<h1 class="rv">Сибсенсор<br><em>AI-ядро</em></h1>
<p class="lead rv">{hero_lead}</p>
<div class="cta rv">{cta}</div>
<div class="stats rv">{stats}</div>
</div>
{_visual(skills=skills, logged_in=actor is not None)}
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
    // параллакс: фон и плашки вокруг карточки ядра сдвигаются на разную глубину
    var layers = Array.prototype.slice.call(document.querySelectorAll('[data-depth]'));
    var mx = 0, my = 0, tx = 0, ty = 0, sy = window.scrollY;
    var fine = window.matchMedia && matchMedia('(pointer: fine)').matches;
    if(fine){
      window.addEventListener('pointermove', function(e){
        mx = (e.clientX / innerWidth - 0.5); my = (e.clientY / innerHeight - 0.5);
      }, {passive: true});
    }
    window.addEventListener('scroll', function(){ sy = window.scrollY; }, {passive: true});
    (function loop(){
      tx += (mx - tx) * 0.07; ty += (my - ty) * 0.07;
      layers.forEach(function(l){
        var d = parseFloat(l.getAttribute('data-depth')) || 0;
        l.style.transform = 'translate3d(' + (-tx * 36 * d) + 'px,' + (-ty * 36 * d - sy * 0.08 * d) + 'px,0)';
      });
      requestAnimationFrame(loop);
    })();

    // карточки: подсветка под курсором и лёгкий наклон
    if(fine){
      document.querySelectorAll('.tile').forEach(function(t){
        t.addEventListener('pointermove', function(e){
          var r = t.getBoundingClientRect();
          var x = (e.clientX - r.left) / r.width, y = (e.clientY - r.top) / r.height;
          t.style.setProperty('--mx', (x * 100) + '%'); t.style.setProperty('--my', (y * 100) + '%');
          t.style.transform = 'perspective(900px) rotateX(' + ((0.5 - y) * 4) + 'deg) rotateY(' + ((x - 0.5) * 5) + 'deg) translateY(-4px)';
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
