"""Welcome-страница ядра «Сибсенсор AI» (корень сайта).

Показывает все функции ядра одной страницей: для вошедшего сотрудника — с его именем
и рабочими ссылками, для администратора — ещё и блок управления. Без входа — экран
входа рабочей почтой. Параллакс и анимации — в отдельном /static/hub.js (CSP без inline-скриптов).
"""

from __future__ import annotations

from asyncio import to_thread as run_in_threadpool
import hashlib
from html import escape

from starlette.responses import HTMLResponse, Response

from gateway_mcp.config import public_url
from gateway_mcp.services import members, storage_skills
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
    ("people", "Новые участники", "/admin/members"),
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
  --bg:#050505;--bg2:#0b0b0b;--card:#0e0e0e;--card2:#131313;
  --ink:#ffffff;--txt:#d6d6d6;--soft:#a3a3a3;--mute:#737373;
  --line:#1f1f1f;--line2:#2c2c2c;
  --sun:#ff5a1f;--sun2:#ff8a3d;--sun-soft:rgba(255,90,31,.14);--ok:#22c55e;
  --font:"Segoe UI Variable Display","Segoe UI",Inter,system-ui,-apple-system,Roboto,Arial,sans-serif;
  --mono:ui-monospace,SFMono-Regular,Consolas,Menlo,monospace;
}
*{box-sizing:border-box}
html{scroll-behavior:smooth}
body{margin:0;background:var(--bg);color:var(--txt);font-family:var(--font);font-size:17px;line-height:1.55;-webkit-font-smoothing:antialiased;overflow-x:clip}
a{color:inherit}
a:focus-visible,button:focus-visible{outline:2px solid var(--sun2);outline-offset:3px;border-radius:10px}

/* фон: «солнце» за контентом, горизонт, едва заметная сетка */
.bg{position:fixed;inset:0;z-index:0;pointer-events:none;overflow:hidden}
.grid{position:absolute;inset:-5%;background:
  linear-gradient(rgba(255,255,255,.035) 1px,transparent 1px) 0 0/72px 72px,
  linear-gradient(90deg,rgba(255,255,255,.035) 1px,transparent 1px) 0 0/72px 72px;
  -webkit-mask:radial-gradient(ellipse 80% 60% at 50% 0%,#000,transparent 75%);mask:radial-gradient(ellipse 80% 60% at 50% 0%,#000,transparent 75%)}
.sun{position:absolute;left:50%;top:-38vh;width:120vw;height:90vh;margin-left:-60vw;border-radius:50%;
  background:radial-gradient(closest-side,rgba(255,106,31,.55),rgba(255,70,20,.22) 45%,transparent 72%);filter:blur(30px);
  animation:breathe 9s ease-in-out infinite}
@keyframes breathe{50%{opacity:.78}}
.horizon{position:absolute;left:10%;right:10%;top:22vh;height:1px;background:linear-gradient(90deg,transparent,rgba(255,138,61,.7),transparent);box-shadow:0 0 24px 2px rgba(255,90,31,.45)}

.board{position:absolute;inset:-4%}
.circuit{position:absolute;inset:0;width:100%;height:100%}
.circuit .trace{fill:none;stroke:rgba(255,138,61,.12);stroke-width:1.8}
.circuit .via{fill:#0b0b0b;stroke:rgba(255,138,61,.35);stroke-width:2}
.circuit .sig{fill:none;stroke:#ff8a3d;stroke-width:2.6;stroke-linecap:round;stroke-dasharray:18 900;animation:sig 7s linear infinite;filter:drop-shadow(0 0 5px rgba(255,90,31,.9))}
.circuit .sig:nth-of-type(3n){stroke:#ffb27a;animation-duration:9s}
.circuit .sig:nth-of-type(2n){animation-delay:-2.5s}
.circuit .sig:nth-of-type(5n){animation-duration:11s;animation-delay:-5s}
@keyframes sig{from{stroke-dashoffset:18}to{stroke-dashoffset:-918}}
.circuit.lit .trace{stroke:rgba(255,160,100,.85);stroke-width:2.2}
.circuit.lit .via{stroke:#ffb27a;fill:#2a1408}
.circuit.lit{-webkit-mask:radial-gradient(260px circle at var(--mx,-999px) var(--my,-999px),#000 0,transparent 100%);mask:radial-gradient(260px circle at var(--mx,-999px) var(--my,-999px),#000 0,transparent 100%)}
.spot{position:absolute;inset:0;background:radial-gradient(420px circle at var(--mx,-999px) var(--my,-999px),rgba(255,90,31,.08),transparent 70%)}
.chips{position:fixed;inset:0;z-index:15;pointer-events:none}
.chipw{position:absolute;width:118px;height:118px;pointer-events:auto;display:block;text-decoration:none;transition:scale .35s cubic-bezier(.16,1,.3,1)}
.chipw svg{position:relative;display:block;width:100%;height:100%;filter:drop-shadow(0 10px 24px rgba(0,0,0,.6))}
.chipw .pins{stroke:#5a3420;transition:stroke .3s}
.chipw .body{fill:#0e0e0e;stroke:#ff5a1f;stroke-width:2.2}
.chipw .die{fill:#170b05;stroke:rgba(255,138,61,.35)}
.chipw text{fill:#ff8a3d;transition:fill .3s}
.chipw .halo{position:absolute;inset:22%;border-radius:18px;animation:halo 3.4s ease-out infinite}
.chipw.c2 .halo{animation-delay:-1.2s}.chipw.c3 .halo{animation-delay:-2.3s}
@keyframes halo{0%{box-shadow:0 0 0 0 rgba(255,90,31,.4)}100%{box-shadow:0 0 0 26px rgba(255,90,31,0)}}
.chipw:hover,.chipw:focus-visible{scale:1.12}
.chipw:hover .pins,.chipw:focus-visible .pins{stroke:#ffb27a}
.chipw:hover text{fill:#fff}
.chipw .tip{position:absolute;top:50%;white-space:nowrap;padding:8px 12px;border-radius:10px;background:#141414;border:1px solid rgba(255,90,31,.5);
  color:#fff;font-size:14px;font-weight:600;opacity:0;transform:translateY(-50%) translateX(-6px);transition:opacity .25s,transform .25s;pointer-events:none}
.chipw.c1 .tip,.chipw.c3 .tip{left:105%}
.chipw.c2 .tip{right:105%;transform:translateY(-50%) translateX(6px)}
.chipw:hover .tip,.chipw:focus-visible .tip{opacity:1;transform:translateY(-50%)}
.chipw.c1{left:1.2%;top:30%}
.chipw.c2{right:1.2%;top:52%}
.chipw.c3{left:1.6%;top:72%;width:96px;height:96px}
.rings{position:fixed;inset:0;z-index:14;pointer-events:none;overflow:hidden}
.ring{position:absolute;width:20px;height:20px;margin:-10px 0 0 -10px;border-radius:50%;border:2px solid rgba(255,138,61,.85);
  box-shadow:0 0 18px rgba(255,90,31,.6);animation:ring .9s cubic-bezier(.16,1,.3,1) forwards}
@keyframes ring{to{transform:scale(14);opacity:0}}
.net .links line{transition:stroke .2s,opacity .2s,stroke-width .2s}
.net.hl .links line{opacity:.25}
.net .links line.on{stroke:#ffb27a;opacity:1;stroke-width:2.2}
.net .links line.fire{stroke:#fff;stroke-dasharray:6 14;animation:fire .7s linear 2}
@keyframes fire{to{stroke-dashoffset:-40}}
.net .nodes circle{cursor:pointer;transition:r .2s}
.net .nodes circle.on{r:11;fill:#ff5a1f}
@media (max-width:1280px){.chipw{width:84px;height:84px;opacity:.55}.chipw.c3{display:none}.chipw .tip{display:none}}
@media (max-width:640px){.chips{display:none}}

.page{position:relative;z-index:1}
.top{position:sticky;top:0;z-index:20;display:flex;align-items:center;justify-content:space-between;gap:16px;
  padding:14px clamp(16px,4vw,48px);background:rgba(5,5,5,.72);backdrop-filter:blur(14px);border-bottom:1px solid var(--line)}
.brand{display:flex;align-items:center;gap:12px;text-decoration:none;font-weight:750;font-size:17px;color:var(--ink);letter-spacing:-.01em}
.brand b{display:grid;place-items:center;width:34px;height:34px;border-radius:10px;color:#fff;font-size:15px;
  background:linear-gradient(135deg,var(--sun2),var(--sun));box-shadow:0 0 22px rgba(255,90,31,.45)}
.brand em{font-style:normal;color:var(--sun2)}
.who{display:flex;align-items:center;gap:14px;font-size:15px;color:var(--soft)}
.live{display:inline-flex;align-items:center;gap:8px;white-space:nowrap;padding:6px 12px;border-radius:999px;border:1px solid var(--line2);color:var(--txt);font-size:13px}
.live i{width:8px;height:8px;border-radius:50%;background:var(--ok);box-shadow:0 0 10px var(--ok)}
.out{color:var(--soft);text-decoration:none}.out:hover{color:var(--ink)}
.btn{display:inline-flex;align-items:center;gap:10px;min-height:50px;padding:0 22px;border-radius:12px;font-weight:650;font-size:16px;text-decoration:none;
  transition:transform .25s cubic-bezier(.16,1,.3,1),box-shadow .25s,background .2s,border-color .2s}
.btn .ico{width:18px;height:18px}
.btn:hover{transform:translateY(-2px)}
.btn.main{background:linear-gradient(180deg,var(--sun2),var(--sun));color:#fff;box-shadow:0 8px 28px rgba(255,90,31,.38),inset 0 1px 0 rgba(255,255,255,.3)}
.btn.main:hover{box-shadow:0 12px 36px rgba(255,90,31,.5),inset 0 1px 0 rgba(255,255,255,.3)}
.btn.ghost{background:rgba(255,255,255,.03);color:var(--ink);border:1px solid var(--line2)}
.btn.ghost:hover{border-color:var(--sun)}
.btn.sm{min-height:38px;padding:0 16px;font-size:14px}

.wrap{max-width:1200px;margin:0 auto;padding:0 clamp(16px,4vw,48px)}

/* первый экран */
.hero{padding:80px 0 40px}
.hero-txt{text-align:center;max-width:860px;margin:0 auto}
.pill{display:inline-flex;align-items:center;gap:8px;padding:7px 14px;border-radius:999px;border:1px solid rgba(255,138,61,.4);background:rgba(255,90,31,.08);color:var(--sun2);font-size:14px;font-weight:600}
.pill i{width:7px;height:7px;border-radius:50%;background:var(--sun2);box-shadow:0 0 10px var(--sun2)}
h1{margin:22px 0 0;font-size:clamp(44px,7vw,92px);line-height:1;font-weight:800;letter-spacing:-.04em;color:var(--ink)}
h1 em{font-style:normal;background:linear-gradient(180deg,#ffb27a,var(--sun) 80%);-webkit-background-clip:text;background-clip:text;color:transparent;filter:drop-shadow(0 0 24px rgba(255,90,31,.35))}
.lead{max-width:640px;margin:24px auto 0;font-size:clamp(18px,1.7vw,21px);line-height:1.55;color:var(--txt)}
.lead strong{color:var(--ink);font-weight:650}
.cta{display:flex;flex-wrap:wrap;justify-content:center;gap:12px;margin-top:32px}

/* витрина: дашборд ядра, выпрямляется при прокрутке (--p от 0 до 1) */
.stage{position:relative;margin:64px auto 0;max-width:1060px;perspective:1600px}
.stage:before{content:"";position:absolute;left:8%;right:8%;top:-40px;height:160px;border-radius:50%;
  background:radial-gradient(closest-side,rgba(255,90,31,.55),transparent);filter:blur(40px);opacity:calc(.5 + .5 * var(--p,1))}
.dash{--p:1;position:relative;transform-origin:50% 0;
  transform:rotateX(calc((1 - var(--p)) * 24deg)) scale(calc(.9 + .1 * var(--p))) translateY(calc((1 - var(--p)) * 30px));
  border-radius:20px;background:linear-gradient(180deg,#121212,#0a0a0a);border:1px solid var(--line2);
  box-shadow:0 -1px 0 rgba(255,138,61,.6),0 0 0 1px rgba(255,90,31,.12),0 40px 120px rgba(0,0,0,.8),0 0 80px rgba(255,90,31,.18);overflow:hidden}
.dash:after{content:"";position:absolute;inset:0;pointer-events:none;
  background:linear-gradient(115deg,transparent 30%,rgba(255,255,255,.07) 45%,transparent 60%);
  transform:translateX(calc((var(--p) - .5) * 120%))}
.dbar{display:flex;align-items:center;gap:10px;padding:12px 16px;border-bottom:1px solid var(--line)}
.dbar span{width:11px;height:11px;border-radius:50%;background:#2a2a2a}
.dbar .t{margin-left:10px;font-size:13px;color:var(--soft)}
.dbar .t i{display:inline-block;width:7px;height:7px;border-radius:50%;background:var(--ok);margin-right:6px;box-shadow:0 0 8px var(--ok)}
.dbody{display:grid;grid-template-columns:210px 1fr;min-height:420px}
.dside{border-right:1px solid var(--line);padding:18px 12px;display:flex;flex-direction:column;gap:4px}
.dside .si{display:flex;align-items:center;gap:10px;padding:9px 10px;border-radius:9px;color:var(--soft);text-decoration:none;font-size:14px}
.dside .si .ico{width:17px;height:17px}
.dside .si.on{background:rgba(255,90,31,.12);color:var(--ink)}
.dside .si.on .ico{color:var(--sun2)}
.dside a.si:hover{color:var(--ink)}
.dmain{padding:22px;display:grid;gap:16px;align-content:start}
.dmain h4{margin:0;font-size:18px;color:var(--ink)}
.kpis{display:grid;grid-template-columns:repeat(3,1fr);gap:12px}
.kpi{padding:14px 16px;border-radius:12px;background:var(--card2);border:1px solid var(--line)}
.kpi small{display:block;color:var(--mute);font-size:12px}
.kpi b{display:block;margin-top:4px;font-size:22px;color:var(--ink);font-weight:750}
.kpi b.ok{color:var(--ok)}
.dgrid{display:grid;grid-template-columns:1.3fr 1fr;gap:12px}
.dpanel{padding:16px;border-radius:12px;background:var(--card2);border:1px solid var(--line)}
.dpanel small{display:block;color:var(--mute);font-size:12px;margin-bottom:10px}
.srow{display:flex;align-items:center;gap:10px;padding:8px 0;border-top:1px solid var(--line);font-size:14px;color:var(--txt)}
.srow:first-of-type{border-top:0}
.srow .dot{width:26px;height:26px;border-radius:8px;display:grid;place-items:center;background:rgba(255,90,31,.12);color:var(--sun2);flex:none}
.srow .dot .ico{width:15px;height:15px}
.srow span{min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.srow em{margin-left:auto;font-style:normal;font-size:12px;color:var(--ok)}
.graph .net{display:block;width:100%;height:auto;max-height:300px}
.net .links line{stroke:rgba(255,138,61,.16);stroke-width:1.1}
.net .pulses line{stroke:#ffb27a;stroke-width:2.2;stroke-linecap:round;stroke-dasharray:10 260;animation:flow 4.2s linear infinite;filter:drop-shadow(0 0 4px rgba(255,90,31,.9))}
.net .pulses line.p2{stroke:#ff5a1f;animation-duration:5.6s}
.net .pulses line.p3{animation-delay:-2s}
@keyframes flow{to{stroke-dashoffset:-270}}
.net .nodes circle{fill:#0e0e0e;stroke:#ff8a3d;stroke-width:1.8}
.net .nodes circle.hot{fill:#ff5a1f;stroke:#ffd2b0;stroke-width:2;filter:drop-shadow(0 0 6px rgba(255,90,31,.9));animation:node 2.8s ease-in-out infinite}
.net .nodes circle.hot:nth-child(3n){animation-delay:-1.2s}
@keyframes node{50%{opacity:.55}}

/* секции: «наезд» при прокрутке */
.sec{padding:110px 0}
.zoom{--p:1;transform:scale(calc(.93 + .07 * var(--p)));opacity:calc(.25 + .75 * var(--p));transform-origin:50% 0}
.sec-h{text-align:center;max-width:720px;margin:0 auto 48px}
.label{display:inline-block;color:var(--sun2);font-size:13px;font-weight:700;letter-spacing:.16em;text-transform:uppercase;margin-bottom:14px}
.sec-h h2{margin:0;font-size:clamp(32px,4.4vw,54px);line-height:1.05;font-weight:780;letter-spacing:-.03em;color:var(--ink)}
.sec-h p{margin:16px auto 0;max-width:560px;color:var(--soft);font-size:18px}
h1,h2,h3,.lead,.sec-h p{text-wrap:balance}

.lit{position:relative;border-radius:20px;background:linear-gradient(180deg,#111,#0b0b0b);border:1px solid var(--line)}
.lit:before{content:"";position:absolute;left:12%;right:12%;top:-1px;height:1px;background:linear-gradient(90deg,transparent,rgba(255,138,61,.8),transparent)}
.tiles{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:18px}
.tile{display:flex;flex-direction:column;gap:12px;min-height:240px;padding:28px;text-decoration:none;color:var(--txt);
  transition:transform .35s cubic-bezier(.16,1,.3,1),border-color .25s,box-shadow .3s}
.tile:hover{transform:translateY(-5px);border-color:#3a2a20;box-shadow:0 20px 50px rgba(0,0,0,.6),0 0 40px rgba(255,90,31,.12)}
.tile .ic{display:grid;place-items:center;width:46px;height:46px;border-radius:12px;background:rgba(255,90,31,.12);color:var(--sun2)}
.tile .ic .ico{width:22px;height:22px}
.tile h3{margin:6px 0 0;font-size:21px;font-weight:700;color:var(--ink)}
.tile p{margin:0;color:var(--soft);font-size:16px;line-height:1.5}
.tile .go{margin-top:auto;display:flex;align-items:center;justify-content:center;gap:8px;min-height:44px;border-radius:10px;
  border:1px solid var(--line2);color:var(--ink);font-size:15px;font-weight:600;transition:background .2s,border-color .2s}
.tile .go .ico{width:16px;height:16px}
.tile:hover .go{border-color:var(--sun)}
.tile.hot{border-color:rgba(255,90,31,.55);box-shadow:0 0 0 1px rgba(255,90,31,.25),0 0 60px rgba(255,90,31,.16)}
.tile.hot .go{background:linear-gradient(180deg,var(--sun2),var(--sun));border-color:transparent;color:#fff}
.tile.hot .tag{position:absolute;top:18px;right:18px;padding:4px 10px;border-radius:999px;background:rgba(255,90,31,.15);color:var(--sun2);font-size:12px;font-weight:700}

.caps{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:18px}
.cap{padding:28px 24px}
.cap .ic{display:grid;place-items:center;width:44px;height:44px;border-radius:12px;color:#fff;background:linear-gradient(180deg,var(--sun2),var(--sun));box-shadow:0 0 24px rgba(255,90,31,.35)}
.cap .ic .ico{width:22px;height:22px}
.cap h3{margin:18px 0 8px;font-size:19px;color:var(--ink)}
.cap p{margin:0;color:var(--soft);font-size:16px;line-height:1.5}

.connect{display:grid;grid-template-columns:1.05fr .95fr;gap:18px}
.panel{padding:32px}
.panel h3{margin:0 0 6px;font-size:21px;color:var(--ink)}
.panel .muted{margin:0;color:var(--soft)}
.url{display:flex;flex-wrap:wrap;align-items:center;justify-content:space-between;gap:12px;margin:20px 0 16px;padding:12px 12px 12px 18px;border-radius:12px;background:#070707;border:1px solid var(--line2)}
.url code{font-family:var(--mono);font-size:16px;white-space:nowrap;overflow-x:auto;max-width:100%;color:var(--ink)}
.copy{display:inline-flex;align-items:center;gap:8px;border:0;background:linear-gradient(180deg,var(--sun2),var(--sun));color:#fff;padding:10px 16px;border-radius:10px;font:inherit;font-size:14px;font-weight:650;cursor:pointer}
.copy .ico{width:16px;height:16px}
.steps{margin:0;padding:0;list-style:none;display:grid;gap:18px;counter-reset:s}
.steps li{display:grid;grid-template-columns:38px 1fr;gap:14px;align-items:start;color:var(--txt)}
.steps li:before{counter-increment:s;content:counter(s);display:grid;place-items:center;width:32px;height:32px;border-radius:50%;border:1px solid rgba(255,138,61,.5);color:var(--sun2);font-weight:700;font-size:14px}
.steps b{color:var(--ink);font-weight:650}

.admin-box{padding:36px;border-color:rgba(255,90,31,.35);box-shadow:0 0 70px rgba(255,90,31,.12)}
.admin-box .sec-h{margin-bottom:28px}
.admin-tiles{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px}
.atile{display:flex;align-items:center;gap:12px;padding:16px 18px;border-radius:12px;text-decoration:none;color:var(--ink);
  background:rgba(255,255,255,.03);border:1px solid var(--line2);transition:border-color .2s,transform .25s,background .2s}
.atile:hover{border-color:var(--sun);background:rgba(255,90,31,.08);transform:translateY(-2px)}
.atile .ico{width:20px;height:20px;color:var(--sun2);flex:none}
.atile span{font-size:15px;font-weight:600}
.atile .cnt{margin-left:auto;font-style:normal;min-width:24px;padding:2px 8px;border-radius:999px;background:var(--sun);color:#fff;font-size:13px;font-weight:700;text-align:center;box-shadow:0 0 14px rgba(255,90,31,.6)}

.stats{display:flex;justify-content:center;flex-wrap:wrap;gap:12px 48px;margin-top:40px}
.stat{text-align:center}
.stat b{display:block;font-size:30px;font-weight:780;color:var(--ink)}
.stat span{color:var(--mute);font-size:14px}

.foot{padding:40px 0 56px;border-top:1px solid var(--line);color:var(--mute);font-size:14px;display:flex;justify-content:space-between;gap:16px;flex-wrap:wrap}
.foot a{color:var(--soft);text-decoration:none}.foot a:hover{color:var(--sun2)}

@media (max-width:980px){
  .dbody{grid-template-columns:1fr}.dside{display:none}
  .tiles{grid-template-columns:repeat(2,minmax(0,1fr))}.caps{grid-template-columns:repeat(2,minmax(0,1fr))}
  .connect{grid-template-columns:1fr}.admin-tiles{grid-template-columns:repeat(2,minmax(0,1fr))}
}
@media (max-width:640px){
  .hero{padding:48px 0 24px}.sec{padding:72px 0}
  .tiles,.caps,.admin-tiles{grid-template-columns:1fr}
  .kpis{grid-template-columns:1fr 1fr}.dgrid{grid-template-columns:1fr}
  .who .name,.live span{display:none}.live{padding:8px}
  .panel,.admin-box{padding:22px}
  .stats{display:grid;grid-template-columns:1fr 1fr;gap:18px}
}
@media (prefers-reduced-motion:reduce){*{animation:none!important;transition:none!important}.dash,.zoom{--p:1!important}.circuit.lit,.spot{display:none}}
"""


def _plural(n: int, one: str, few: str, many: str) -> str:
    if n % 10 == 1 and n % 100 != 11:
        return one
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return few
    return many


def _net_svg() -> str:
    """Граф-нейросеть ядра: узлы по слоям, связи и бегущие по части связей импульсы."""
    cols = [(40, [60, 140, 220, 300]), (165, [30, 105, 180, 255, 330]), (290, [60, 140, 220, 300]), (400, [130, 230])]
    lines, pulses, nodes = [], [], []
    for (x1, ys1), (x2, ys2) in zip(cols, cols[1:]):
        for i, y1 in enumerate(ys1):
            for j, y2 in enumerate(ys2):
                lines.append(
                    f'<line data-a="{x1}-{y1}" data-b="{x2}-{y2}" x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}"/>'
                )
                if (i + 2 * j) % 5 == 0:
                    kind = ("p2" if (i + j) % 2 else "") + (" p3" if j % 3 == 0 else "")
                    pulses.append(f'<line class="pulse {kind}" x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}"/>')
    for n, (x, ys) in enumerate(cols):
        for k, y in enumerate(ys):
            if (n + k) % 3 == 0:
                nodes.append(f'<circle class="hot" data-id="{x}-{y}" cx="{x}" cy="{y}" r="8"/>')
            else:
                nodes.append(f'<circle data-id="{x}-{y}" cx="{x}" cy="{y}" r="6"/>')
    return (
        '<svg class="net" viewBox="0 0 440 360" aria-hidden="true">'
        f'<g class="links">{"".join(lines)}</g>'
        f'<g class="pulses">{"".join(pulses)}</g>'
        f'<g class="nodes">{"".join(nodes)}</g></svg>'
    )


def _dashboard(*, actor, skills: int, skill_titles: tuple[str, ...]) -> str:
    """Макет рабочего экрана ядра на первом экране — с настоящими данными, если человек вошёл."""
    if actor is not None:
        who = escape(actor.display)
        kpi_first = f'<div class="kpi"><small>в каталоге</small><b>{skills}</b></div>'
        titles = skill_titles[:4] or ("Навыки компании",)
        rows = "".join(
            f'<div class="srow"><span class="dot">{_icon("book")}</span><span>{escape(t)}</span><em>активен</em></div>'
            for t in titles
        )
    else:
        who = "@sibsensor.com"
        kpi_first = '<div class="kpi"><small>навыки</small><b>отделов</b></div>'
        rows = "".join(
            f'<div class="srow"><span class="dot">{_icon(icon)}</span><span>{text}</span></div>'
            for icon, text in (
                ("book", "Навыки компании"),
                ("search", "Общие знания"),
                ("bell", "Уведомления в Telegram"),
                ("shield", "Журнал действий"),
            )
        )
    side_items = []
    for i, (icon, title, _desc, href) in enumerate(_USER_TILES):
        cls = "si on" if i == 0 else "si"
        label = f"{_icon(icon)}{escape(title)}"
        # гостю — только картинка меню, без ссылок на личные разделы
        side_items.append(f'<a class="{cls}" href="{href}">{label}</a>' if actor is not None else f'<span class="{cls}">{label}</span>')
    side = "".join(side_items)
    return (
        '<div class="stage rv"><div class="dash" data-scroll>'
        '<div class="dbar"><span></span><span></span><span></span>'
        f'<div class="t"><i></i>Сибсенсор AI · ядро · {who}</div></div>'
        '<div class="dbody">'
        f'<nav class="dside" aria-label="Разделы ядра">{side}</nav>'
        '<div class="dmain"><h4>Обзор ядра</h4>'
        '<div class="kpis">'
        f"{kpi_first}"
        '<div class="kpi"><small>вход</small><b>Яндекс ID</b></div>'
        '<div class="kpi"><small>статус</small><b class="ok">онлайн</b></div>'
        "</div>"
        '<div class="dgrid">'
        f'<div class="dpanel"><small>Навыки</small>{rows}</div>'
        f'<div class="dpanel graph" aria-hidden="true"><small>Граф ядра · связи навыков и сервисов</small>{_net_svg()}</div>'
        "</div></div></div></div></div>"
    )


# Дорожки платы: от краёв экрана внутрь, на концах — переходные отверстия.
_TRACES = (
    ("M0 140H220L260 180H420", (420, 180)),
    ("M0 230H160L200 270H330L360 300H520", (520, 300)),
    ("M0 520H120L170 470H300", (300, 470)),
    ("M0 610H240L280 650H360", (360, 650)),
    ("M0 770H200L240 810H460L500 770H640", (640, 770)),
    ("M0 890H340L380 930H560", (560, 930)),
    ("M1600 120H1380L1340 160H1180", (1180, 160)),
    ("M1600 300H1460L1420 260H1300L1260 300H1120", (1120, 300)),
    ("M1600 470H1500L1460 510H1240", (1240, 510)),
    ("M1600 700H1420L1380 740H1200L1160 700H1020", (1020, 700)),
    ("M1600 870H1300L1260 830H1100", (1100, 830)),
    ("M780 1000V880L820 840V760", (820, 760)),
    ("M1240 1000V940L1200 900V860", (1200, 860)),
)

# Микросхемы: (класс, надпись, подсказка, раздел для вошедшего, раздел для гостя)
_CHIPS = (
    ("c1", "AI", "Навыки и знания компании", "#core", "#core"),
    ("c2", "MCP", "Подключить своего ассистента", "#connect", "#connect"),
    ("c3", "API", "Рабочие разделы ядра", "#work", "#connect"),
)


def _circuit_svg(cls: str) -> str:
    traces = "".join(f'<path class="trace" d="{d}"/>' for d, _ in _TRACES)
    vias = "".join(f'<circle class="via" cx="{x}" cy="{y}" r="6"/>' for _, (x, y) in _TRACES)
    signals = "".join(f'<path class="sig" d="{d}"/>' for d, _ in _TRACES) if cls == "base" else ""
    return (
        f'<svg class="circuit {cls}" viewBox="0 0 1600 1000" preserveAspectRatio="xMidYMid slice" aria-hidden="true">'
        f"<g>{traces}</g><g>{signals}</g><g>{vias}</g></svg>"
    )


def _chip_svg(label: str) -> str:
    pins = "".join(f'<path d="M{p} 8V26M{p} 124V142M8 {p}H26M124 {p}H142"/>' for p in (45, 65, 85, 105))
    return (
        '<svg viewBox="0 0 150 150" aria-hidden="true">'
        f'<g class="pins" stroke-width="2.6" stroke-linecap="round">{pins}</g>'
        '<rect class="body" x="28" y="28" width="94" height="94" rx="16"/>'
        '<rect class="die" x="40" y="40" width="70" height="70" rx="10"/>'
        '<text x="75" y="84" text-anchor="middle" font-family="Segoe UI,Arial,sans-serif" font-size="22" '
        f'font-weight="800">{label}</text></svg>'
    )


def _background() -> str:
    return (
        '<div class="bg" aria-hidden="true">'
        '<div class="grid"></div><div class="sun" data-depth="0.4"></div><div class="horizon" data-depth="0.2"></div>'
        f'<div class="board" data-depth="0.25">{_circuit_svg("base")}{_circuit_svg("lit")}</div>'
        '<div class="spot"></div>'
        "</div>"
    )


def _chips(*, logged_in: bool) -> str:
    chips = "".join(
        f'<a class="chipw {cls}" href="{target if logged_in else guest}" data-depth="{depth}" aria-label="{escape(tip)}">'
        f'<span class="halo"></span>{_chip_svg(label)}<span class="tip">{escape(tip)} →</span></a>'
        for (cls, label, tip, target, guest), depth in zip(_CHIPS, ("0.6", "0.9", "0.45"))
    )
    return f'<div class="chips">{chips}</div><div class="rings" aria-hidden="true"></div>'


def _sec_head(label: str, title: str, text: str) -> str:
    return (
        f'<div class="sec-h"><span class="label">{escape(label)}</span><h2>{escape(title)}</h2>'
        f"<p>{escape(text)}</p></div>"
    )


def _tiles(items) -> str:
    out = []
    for icon, title, desc, href in items:
        hot = href == "/skills/new"
        out.append(
            f'<a class="tile lit{" hot" if hot else ""}" href="{href}">'
            + ('<span class="tag">главное</span>' if hot else "")
            + f'<span class="ic">{_icon(icon)}</span><h3>{escape(title)}</h3><p>{escape(desc)}</p>'
            f'<span class="go">Открыть {_icon("arrow")}</span></a>'
        )
    return "".join(out)


def _admin_block(member_pending: int = 0) -> str:
    def badge(href: str) -> str:
        if href == "/admin/members" and member_pending:
            return f'<em class="cnt">{member_pending}</em>'
        return ""

    tiles = "".join(
        f'<a class="atile" href="{href}">{_icon(icon)}<span>{escape(title)}</span>{badge(href)}</a>'
        for icon, title, href in _ADMIN_TILES
    )
    return (
        '<section class="sec" id="admin"><div class="wrap zoom" data-scroll><div class="lit admin-box">'
        + _sec_head("Только для администраторов", "Управление ядром", "Доступы, заявки, журнал и состояние шлюза.")
        + f'<div class="admin-tiles">{tiles}</div></div></div></section>'
    )


def _connect_block(mcp_url: str) -> str:
    return (
        '<section class="sec" id="connect"><div class="wrap zoom" data-scroll>'
        + _sec_head("За пять минут", "Подключить ассистента", "Ваш Claude начнёт работать с навыками и знаниями компании.")
        + '<div class="connect">'
        '<div class="lit panel"><h3>Адрес ядра</h3>'
        '<p class="muted">Вставьте его в приложении Claude: Настройки → Коннекторы → Добавить.</p>'
        f'<div class="url"><code id="mcp-url">{escape(mcp_url)}</code>'
        f'<button class="copy" type="button" data-copy="#mcp-url">{_icon("copy")}<span>Копировать</span></button></div>'
        '<p class="muted">Права администратора не нужны: доступ открывается сам для рабочей почты @sibsensor.com.</p></div>'
        '<div class="lit panel"><ol class="steps">'
        "<li><span>Установите <b>приложение Claude</b> с claude.ai/download</span></li>"
        "<li><span><b>Настройки → Коннекторы → Добавить</b>, вставьте адрес ядра</span></li>"
        "<li><span>Нажмите <b>«Войти через Яндекс»</b> и войдите рабочей почтой</span></li>"
        "<li><span>Спросите ассистента: <b>«Какие навыки есть у компании?»</b></span></li>"
        "</ol></div></div></div></section>"
    )


def _caps_block() -> str:
    cells = "".join(
        f'<div class="lit cap"><span class="ic">{_icon(icon)}</span><h3>{escape(t)}</h3><p>{escape(d)}</p></div>'
        for icon, t, d in _CAPS
    )
    return (
        '<section class="sec" id="core"><div class="wrap zoom" data-scroll>'
        + _sec_head("Что внутри", "Что даёт ядро", "Один общий мозг компании на нашем сервере — для ассистента каждого сотрудника.")
        + f'<div class="caps">{cells}</div></div></section>'
    )


def _page_html(
    *, actor, skills: int, agents: int, mcp_url: str, skill_titles: tuple[str, ...] = (), member_pending: int = 0
) -> str:
    if actor is None:
        who = '<a class="btn ghost sm" href="/auth/yandex/login?next=/">Войти</a>'
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
            '<section class="sec" id="work"><div class="wrap zoom" data-scroll>'
            + _sec_head("Рабочее место", "Всё, что можно сделать в ядре", "Каждая карточка — рабочая ссылка, в один клик.")
            + f'<div class="tiles">{_tiles(_USER_TILES)}</div></div></section>'
        )
        admin = _admin_block(member_pending) if is_admin else ""
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
<script src="/static/hub.js?v={_JS_VERSION}" defer></script>
</head>
<body>
{_background()}
<div class="page">
<header class="top">
<a class="brand" href="/"><b>С</b>Сибсенсор&nbsp;<em>AI</em></a>
<div class="who"><span class="live" title="Ядро онлайн"><i></i><span>Ядро онлайн</span></span>{who}</div>
</header>
<main>
<section class="hero"><div class="wrap">
<div class="hero-txt">
<span class="pill"><i></i>Вы на ядре</span>
<h1>Сибсенсор <em>AI-ядро</em></h1>
<p class="lead">{hero_lead}</p>
<div class="cta">{cta}</div>
<div class="stats">{stats}</div>
</div>
{_dashboard(actor=actor, skills=skills, skill_titles=skill_titles)}
</div></section>
{work}
{_caps_block()}
{_connect_block(mcp_url)}
{admin}
</main>
<div class="wrap"><footer class="foot"><span>Сибсенсор AI · корпоративное ядро на сервере компании</span>
<a href="/healthz">Проверка работы ядра</a></footer></div>
</div>
{_chips(logged_in=actor is not None)}
</body>
</html>"""


_JS = r"""
(function(){
  var reduce = window.matchMedia && matchMedia('(prefers-reduced-motion: reduce)').matches;
  function ready(fn){ if(document.readyState!=='loading') fn(); else document.addEventListener('DOMContentLoaded', fn); }
  ready(function(){
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

    // прокрутка: дашборд выпрямляется из наклона, секции «наезжают» (--p от 0 до 1)
    var scrolled = Array.prototype.slice.call(document.querySelectorAll('[data-scroll]'));
    var depth = Array.prototype.slice.call(document.querySelectorAll('[data-depth]'));
    var mx = 0, my = 0, tx = 0, ty = 0;
    var fine = window.matchMedia && matchMedia('(pointer: fine)').matches;
    if(fine){
      window.addEventListener('pointermove', function(e){
        mx = (e.clientX / innerWidth - 0.5); my = (e.clientY / innerHeight - 0.5);
      }, {passive: true});
    }
    function clamp(v){ return v < 0 ? 0 : (v > 1 ? 1 : v); }
    function update(){
      var vh = innerHeight;
      scrolled.forEach(function(el){
        var r = el.getBoundingClientRect();
        var start = el.classList.contains('dash') ? vh * 0.98 : vh;
        var span = el.classList.contains('dash') ? vh * 0.55 : vh * 0.45;
        el.style.setProperty('--p', clamp((start - r.top) / span).toFixed(3));
      });
    }
    update();
    window.addEventListener('scroll', update, {passive: true});
    window.addEventListener('resize', update);
    (function loop(){
      tx += (mx - tx) * 0.06; ty += (my - ty) * 0.06;
      depth.forEach(function(l){
        var d = parseFloat(l.getAttribute('data-depth')) || 0;
        l.style.translate = (-tx * 40 * d) + 'px ' + (-ty * 30 * d - scrollY * 0.15 * d) + 'px';
      });
      requestAnimationFrame(loop);
    })();

    // микросхемы: плавная прокрутка к разделу; если раздела нет — обычный переход
    document.querySelectorAll('.chipw').forEach(function(c){
      c.addEventListener('click', function(e){
        var t = document.querySelector(c.getAttribute('href'));
        if(t){ e.preventDefault(); t.scrollIntoView({behavior: 'smooth', block: 'start'}); }
      });
    });

    // фонарик: дорожки платы подсвечиваются вокруг курсора
    var bg = document.querySelector('.bg');
    if(fine && bg){
      window.addEventListener('pointermove', function(e){
        bg.style.setProperty('--mx', e.clientX + 'px'); bg.style.setProperty('--my', e.clientY + 'px');
      }, {passive: true});
    }

    // клик по пустому месту — световая волна
    var rings = document.querySelector('.rings');
    document.addEventListener('pointerdown', function(e){
      if(!rings || e.target.closest('a,button,input,textarea,select,.net')) return;
      var r = document.createElement('span'); r.className = 'ring';
      r.style.left = e.clientX + 'px'; r.style.top = e.clientY + 'px';
      rings.appendChild(r); setTimeout(function(){ r.remove(); }, 950);
    });

    // граф: наведение подсвечивает связи узла, клик пускает разряд
    document.querySelectorAll('.net').forEach(function(net){
      function links(id){ return net.querySelectorAll('.links line[data-a="' + id + '"], .links line[data-b="' + id + '"]'); }
      net.querySelectorAll('.nodes circle').forEach(function(n){
        var id = n.getAttribute('data-id');
        n.addEventListener('pointerenter', function(){
          net.classList.add('hl'); n.classList.add('on');
          links(id).forEach(function(l){ l.classList.add('on'); });
        });
        n.addEventListener('pointerleave', function(){
          net.classList.remove('hl'); n.classList.remove('on');
          links(id).forEach(function(l){ l.classList.remove('on'); });
        });
        n.addEventListener('click', function(){
          links(id).forEach(function(l){
            l.classList.remove('fire'); void l.getBoundingClientRect(); l.classList.add('fire');
            setTimeout(function(){ l.classList.remove('fire'); }, 1500);
          });
        });
      });
    });

    // магнитные кнопки
    if(fine){
      document.querySelectorAll('.btn').forEach(function(b){
        b.addEventListener('pointermove', function(e){
          var r = b.getBoundingClientRect();
          b.style.translate = ((e.clientX - r.left - r.width / 2) * 0.18) + 'px ' + ((e.clientY - r.top - r.height / 2) * 0.25) + 'px';
        });
        b.addEventListener('pointerleave', function(){ b.style.translate = ''; });
      });
    }

    // карточки: свет следует за курсором
    if(fine){
      document.querySelectorAll('.lit').forEach(function(c){
        c.addEventListener('pointermove', function(e){
          var r = c.getBoundingClientRect();
          c.style.backgroundImage = 'radial-gradient(420px 220px at ' + (e.clientX - r.left) + 'px ' + (e.clientY - r.top) + 'px, rgba(255,90,31,.10), transparent 60%), linear-gradient(180deg,#111,#0b0b0b)';
        });
        c.addEventListener('pointerleave', function(){ c.style.backgroundImage = ''; });
      });
    }
  });
})();
"""


# Метка версии скрипта: после обновления ядра браузер не возьмёт старый скрипт из кэша.
_JS_VERSION = hashlib.sha256(_JS.encode("utf-8")).hexdigest()[:10]


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
        titles: tuple[str, ...] = ()
        if actor is not None:
            try:
                catalog = await run_in_threadpool(skill_summaries)
                skills = len(catalog)
                titles = tuple(str(s.get("title") or s.get("name") or "") for s in catalog if s.get("title") or s.get("name"))
            except Exception:  # noqa: BLE001 - страница не должна падать из-за счётчика
                skills = 0
            try:
                agents = len(await run_in_threadpool(storage_skills.list_agents))
            except Exception:  # noqa: BLE001
                agents = 0
        member_pending = 0
        if actor is not None and has_scope(actor, "access:admin"):
            try:
                member_pending = await run_in_threadpool(members.pending_count)
            except Exception:  # noqa: BLE001
                member_pending = 0
        html = _page_html(
            actor=actor,
            skills=skills,
            agents=agents,
            mcp_url=public_url() + "/mcp",
            skill_titles=titles,
            member_pending=member_pending,
        )
        return _secure(HTMLResponse(html), private=True)

    @mcp.custom_route("/static/hub.js", methods=["GET"], include_in_schema=False)
    async def hub_js(request):
        return _secure(Response(_JS, media_type="application/javascript"), private=False)
