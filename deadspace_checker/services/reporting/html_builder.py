import json as _json
from datetime import datetime
from typing import List, Dict


def esc(s):
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


REPORT_CSS = """
*{margin:0;padding:0;box-sizing:border-box}
body{background:#070714;color:#d4d4d4;font-family:'Segoe UI',sans-serif;padding:24px;display:flex;justify-content:center}
body::before{content:'';position:fixed;top:0;left:0;right:0;bottom:0;background:radial-gradient(ellipse at 20%% 50%%, rgba(124,58,237,0.08) 0%%, transparent 60%%),radial-gradient(ellipse at 80%% 20%%, rgba(34,211,238,0.06) 0%%, transparent 50%%),radial-gradient(ellipse at 50%% 80%%, rgba(251,191,36,0.04) 0%%, transparent 50%%);pointer-events:none;z-index:0}
.report{max-width:780px;width:100%%;position:relative;z-index:1}
.header{display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:20px;background:linear-gradient(135deg,#0f0f24,#151530);border-radius:12px;padding:20px 24px;border:1px solid #2a2a50}
.header-left h1{font-size:24px;margin-bottom:4px;color:#22d3ee}
.header-left .sub{color:#6b7280;font-size:13px}
.status-badge{display:inline-block;padding:6px 18px;border-radius:6px;font-weight:700;font-size:13px;color:#fff;background:%s;box-shadow:0 0 20px %s44}
.section-title{font-size:16px;font-weight:700;margin:24px 0 10px;padding-bottom:6px;border-bottom:1px solid #2a2a50;color:#e2e8f0}
.info-card{border-radius:8px;padding:12px 16px;margin-bottom:6px;display:flex;gap:12px;align-items:start;border:1px solid #2a2a50}
.badge{color:#fff;font-weight:700;font-size:13px;border-radius:50%%;width:28px;height:28px;min-width:28px;display:flex;align-items:center;justify-content:center}
.bad-red{background:#ef4444}
.bad-green{background:#22c55e;color:#070714}
.bad-blue{background:#22d3ee;color:#070714}
.bad-purple{background:#7c3aed}
.bad-orange{background:#fbbf24;color:#070714}
.card-fields{flex:1;min-width:0}
.field{display:flex;gap:8px;margin-bottom:3px;font-size:13px;align-items:baseline}
.key{color:#6b7280;min-width:70px;flex-shrink:0;font-weight:600}
.val{word-break:break-word}
.yellow{color:#fbbf24}
.blue{color:#22d3ee}
.green{color:#22c55e}
.purple{color:#a78bfa}
.gray{color:#6b7280}
.orange{color:#fbbf24}
.cyan{color:#22d3ee}
.mono{font-family:'Consolas','Courier New',monospace;font-size:12px;word-break:break-all}
.link{color:#22d3ee;text-decoration:underline;word-break:break-all}
.nick-list{background:#0f0f24;border-radius:8px;padding:12px 16px;font-size:13px;line-height:1.7;color:#a78bfa;border:1px solid #2a2a50}
.content-box{background:#070714;border-radius:6px;padding:8px 10px;margin-top:4px;font-size:12px;line-height:1.5;color:#94a3b8;white-space:pre-wrap;word-break:break-word;max-height:200px;overflow-y:auto;border:1px solid #2a2a50}
.footer{margin-top:32px;padding-top:12px;border-top:1px solid #2a2a50;font-size:11px;color:#4b5563;text-align:center}
.footer .brand{color:#22d3ee;font-weight:600}
.tag{display:inline-block;padding:1px 8px;border-radius:3px;font-size:11px;font-weight:600;margin-right:4px}
.tag-red{background:#ef444444;color:#ef4444}
.tag-green{background:#22c55e44;color:#22c55e}
.tag-orange{background:#fbbf2444;color:#fbbf24}
.tag-blue{background:#22d3ee44;color:#22d3ee}
.tag-cyan{background:#22d3ee44;color:#22d3ee}
.geo-tag{display:inline-block;padding:1px 8px;border-radius:3px;font-size:11px;font-weight:400;margin-right:4px;background:#151530;color:#9ca3af;border:1px solid #2a2a50}
.expired{opacity:.55}
.expired .tag-exp{display:inline-block;padding:1px 8px;border-radius:3px;font-size:11px;font-weight:600;background:#6b728044;color:#9ca3af}
.copy-btn{background:#151530;color:#22d3ee;border:1px solid #2a2a50;border-radius:4px;cursor:pointer;font-size:13px;padding:2px 8px;transition:.15s;white-space:nowrap}
.copy-btn:hover{background:#1f1f40;border-color:#22d3ee}
.copy-btn::after{content:attr(data-tip);display:none;position:absolute;bottom:130%%;left:50%%;transform:translateX(-50%%);background:#0f0f24;color:#e2e8f0;padding:4px 10px;border-radius:4px;font-size:11px;white-space:nowrap;pointer-events:none;z-index:10;border:1px solid #2a2a50}
.copy-btn:hover::after{display:block}
.copy-btn-wrap{position:relative;display:inline-flex;align-items:center}
.nick-item{display:inline-flex;align-items:center;gap:4px;margin:2px 0}
#graph-container{border:1px solid #2a2a50;border-radius:8px;overflow:hidden}
"""

BAN_BYPASS_CSS = """
*{margin:0;padding:0;box-sizing:border-box}
body{background:#070714;color:#d4d4d4;font-family:'Segoe UI',sans-serif;padding:24px;display:flex;justify-content:center}
body::before{content:'';position:fixed;top:0;left:0;right:0;bottom:0;background:radial-gradient(ellipse at 20%% 50%%, rgba(124,58,237,0.08) 0%%, transparent 60%%),radial-gradient(ellipse at 80%% 20%%, rgba(34,211,238,0.06) 0%%, transparent 50%%);pointer-events:none;z-index:0}
.wrap{max-width:960px;width:100%%;position:relative;z-index:1}
h1{font-size:22px;margin-bottom:4px;color:#22d3ee}
.sub{color:#6b7280;font-size:13px;margin-bottom:16px}
.summary{display:flex;gap:16px;margin:16px 0;flex-wrap:wrap}
.sum-card{background:#0f0f24;border-radius:8px;padding:14px 20px;flex:1;min-width:140px;border:1px solid #2a2a50}
.sum-card .num{font-size:28px;font-weight:700;color:#22d3ee}
.sum-card .lbl{font-size:12px;color:#6b7280;margin-top:2px}
.bypass-card{background:#0f0f24;border-radius:10px;margin-bottom:14px;border:1px solid #2a2a50;overflow:hidden;position:relative}
.bypass-card::before{content:'';position:absolute;top:0;left:0;bottom:0;width:4px}
.bypass-card.hwid::before{background:#ef4444}
.bypass-card.ip-very-close::before{background:#fbbf24}
.bypass-card.ip-close::before{background:#f59e0b}
.bypass-card.ip-moderate::before{background:#22d3ee}
.bypass-card.ip-distant::before{background:#22d3ee}
.bypass-card.ip-match::before{background:#6b7280}
.bypass-card.no-match::before{background:#374151}
.card-header{padding:14px 18px 10px 22px;display:flex;justify-content:space-between;align-items:flex-start;gap:12px;flex-wrap:wrap}
.card-header .name{font-size:17px;font-weight:700;color:#e2e8f0}
.card-header .name .author-id{font-size:12px;font-weight:400;color:#6b7280}
.conf-badge{display:inline-block;padding:3px 12px;border-radius:4px;font-size:12px;font-weight:700;color:#fff;white-space:nowrap}
.card-body{padding:0 18px 14px 22px}
.card-body .field{display:flex;gap:8px;margin-bottom:4px;font-size:13px;align-items:baseline}
.card-body .key{color:#6b7280;min-width:80px;flex-shrink:0;font-weight:600}
.card-body .val{word-break:break-word}
.twins-section{margin-top:10px;background:#0a0a1a;border-radius:6px;padding:10px 12px;border:1px solid #1a1a3a}
.twins-section .twin-title{font-size:12px;font-weight:700;color:#6b7280;text-transform:uppercase;margin-bottom:6px}
.twin-item{display:flex;align-items:center;gap:10px;padding:4px 0;font-size:13px;flex-wrap:wrap}
.twin-item+.twin-item{border-top:1px solid #1a1a3a;margin-top:4px;padding-top:8px}
.twin-name{color:#c792ea;font-weight:600;min-width:120px}
.twin-ip{color:#89ddff;font-family:'Consolas','Courier New',monospace;font-size:12px;word-break:break-all;min-width:130px}
.twin-hwid{color:#6b7280;font-family:'Consolas','Courier New',monospace;font-size:12px;word-break:break-all}
.status-ok{display:inline-flex;align-items:center;gap:4px;padding:2px 10px;border-radius:4px;font-size:11px;font-weight:600;background:#22c55e22;color:#22c55e;border:1px solid #22c55e44}
.status-fail{display:inline-flex;align-items:center;gap:4px;padding:2px 10px;border-radius:4px;font-size:11px;font-weight:600;background:#ef444422;color:#ef4444;border:1px solid #ef444444}
.status-unknown{display:inline-flex;align-items:center;gap:4px;padding:2px 10px;border-radius:4px;font-size:11px;font-weight:600;background:#6b728022;color:#9ca3af;border:1px solid #6b728044}
.no-twins{color:#6b7280;font-size:12px;font-style:italic;padding:4px 0}
.mono{font-family:'Consolas','Courier New',monospace;font-size:12px;word-break:break-all}
.gray{color:#6b7280}
.cyan{color:#89ddff}
.purple{color:#c792ea}
.green{color:#22c55e}
.link{color:#22d3ee;text-decoration:underline;word-break:break-all}
.footer{margin-top:32px;padding-top:12px;border-top:1px solid #2a2a50;font-size:11px;color:#4b5563;text-align:center}
.footer .brand{color:#22d3ee;font-weight:600}
"""



def build_report_script(nickname_data: dict) -> str:
    data_json = _json.dumps(nickname_data, ensure_ascii=False)
    return f"""<script>
function copyText(text) {{
    if (navigator.clipboard && navigator.clipboard.writeText) {{
        navigator.clipboard.writeText(text).catch(function() {{ fallbackCopy(text); }});
    }} else {{ fallbackCopy(text); }}
}}
function fallbackCopy(text) {{
    var ta = document.createElement('textarea');
    ta.value = text; ta.style.position='fixed'; ta.style.left='-9999px';
    document.body.appendChild(ta); ta.select();
    try {{ document.execCommand('copy'); }} catch(e) {{}}
    document.body.removeChild(ta);
}}
function copyNicknameData(nick) {{
    var data = nicknameData[nick]; if (!data) return;
    var lines = [];
    for (var i = 0; i < data.ips.length; i++) lines.push(data.ips[i]);
    for (var i = 0; i < data.hwids.length; i++) lines.push(data.hwids[i]);
    copyText(lines.join('\\\\n'));
}}
var nicknameData = {data_json};
</script>"""


def collect_nickname_data(data: List[dict]) -> dict:
    nickname_data = {}
    for item in data[1:]:
        typ = item.get("type", "")
        if typ == "associated_accounts":
            for nick in item.get("nicknames", []):
                nickname_data.setdefault(nick, {"ips": [], "hwids": []})
        elif typ == "associated_ips":
            for ip_entry in item.get("ips", []):
                ip = ip_entry.get("direct_ip_connections", "")
                for user in ip_entry.get("raw_users", []):
                    entry = nickname_data.setdefault(user, {"ips": [], "hwids": []})
                    if ip and ip not in entry["ips"]:
                        entry["ips"].append(ip)
        elif typ == "associated_hwids":
            for hw_entry in item.get("hwids", []):
                hwid = hw_entry.get("hwid", "")
                for user in hw_entry.get("raw_users", []):
                    entry = nickname_data.setdefault(user, {"ips": [], "hwids": []})
                    if hwid and hwid not in entry["hwids"]:
                        entry["hwids"].append(hwid)
    return nickname_data


def _render_accounts_section(html_parts: list, item: dict, graph_injected: bool):
    nicks = item.get("nicknames", [])
    all_nicks_text = "\n".join(esc(n) for n in nicks)
    html_parts.append(f'<div class="section-title" style="display:flex;align-items:center;gap:10px"><span>👤 Связанные никнеймы ({len(nicks)})</span><div class="copy-btn-wrap"><button class="copy-btn" onclick="copyText(\'{all_nicks_text.replace("'", "\\\'")}\')" data-tip="Скопировать все никнеймы">📋</button></div></div>')
    nick_items = []
    for n in nicks:
        safe_n = esc(n).replace("'", "\\'")
        nick_items.append(f'<span class="nick-item"><span class="copy-btn-wrap"><button class="copy-btn" onclick="copyNicknameData(\'{safe_n}\')" data-tip="Скопировать IP и HWID для {esc(n)}">📋</button></span>{esc(n)}</span>')
    html_parts.append(f'<div class="nick-list">{"<br>".join(nick_items)}</div>\n')


def _is_expired(expires: str, admin: str) -> bool:
    if "unbanned" in admin.lower():
        return True
    if expires and expires.lower() not in ("никогда", "never", "n/a", ""):
        try:
            exp = datetime.strptime(expires[:19], "%Y-%m-%d %H:%M:%S")
            if exp < datetime.now():
                return True
        except ValueError:
            pass
    return False


def _render_punishments_section(html_parts: list, item: dict):
    reasons = item.get("reasons", [])
    html_parts.append(f'<div class="section-title">⚖️ Наказания из админ-панели ({len(reasons)})</div>')
    for idx, ban in enumerate(reasons[:30]):
        reason = ban.get("reason", "")
        username = ban.get("username", "?")
        admin = ban.get("admin", "N/A")
        ban_type = ban.get("type", "")
        date = ban.get("date", "")
        expires = ban.get("expires", "")
        date_str = date
        expired = _is_expired(expires, admin)
        if expires and expires.lower() not in ("никогда", "never", "n/a", ""):
            date_str += f" → {expires}"
        stripe = "#2a2a2a" if idx % 2 == 0 else "#252526"
        exp_tag = ' <span class="tag-exp">Истёк</span>' if expired else ""
        html_parts.append(f'''<div class="info-card{' expired' if expired else ''}" style="background:{stripe}">
            <div class="badge{' bad-red' if not expired else ' gray'}" style="background{'#6b7280' if expired else '#ef4444'}">{idx+1}</div>
            <div class="card-fields">
              <div class="field"><span class="key">Игрок</span><span class="val">{esc(username)}{exp_tag}</span></div>
              <div class="field"><span class="key">Причина</span><span class="val">{esc(reason)}</span></div>
              <div class="field"><span class="key">Админ</span><span class="val blue">{esc(admin)}</span></div>
              <div class="field"><span class="key">Тип</span><span class="val orange">{esc(ban_type)}</span></div>
              <div class="field"><span class="key">Дата</span><span class="val gray">{esc(date_str)}</span></div>
            </div>
          </div>''')


def _render_complaints_section(html_parts: list, item: dict):
    links = item.get("links", [])
    html_parts.append(f'<div class="section-title">📋 Наказания на других серверах ({len(links)})</div>')
    for ci, c in enumerate(links[:30]):
        ch = c.get("channel", "?")
        auth = c.get("author", "?")
        content = c.get("content", "")
        link = c.get("link", "")
        stripe = "#2a2a2a" if ci % 2 == 0 else "#252526"
        content_short = (content[:800] + "...") if len(content) > 800 else content
        content_html = f'<div class="content-box">{esc(content_short)}</div>' if content else ""
        link_html = f'<div class="field"><span class="key">Ссылка</span><a class="val link" href="{esc(link)}">{esc(link[:90])}{"..." if len(link) > 90 else ""}</a></div>' if link else ""
        html_parts.append(f'''<div class="info-card" style="background:{stripe}">
            <div class="badge bad-blue">{ci+1}</div>
            <div class="card-fields">
              <div class="field"><span class="key">Канал</span><span class="val orange">#{esc(ch)}</span></div>
              <div class="field"><span class="key">Автор</span><span class="val blue">{esc(auth)}</span></div>
              {link_html}
              {content_html}
            </div>
          </div>''')


def _geo_html(vpn_info: dict) -> str:
    parts = []
    cc = vpn_info.get("countryCode", "")
    country = vpn_info.get("country", "")
    city = vpn_info.get("city", "")
    flag_img = ""
    if cc and len(cc) == 2:
        flag_img = f'<img src="https://flagcdn.com/16x12/{cc.lower()}.png" width="16" height="12" alt="{cc.upper()}" style="vertical-align:middle;border-radius:2px">'
    if country and city:
        parts.append(f'{flag_img} {city}, {country}')
    elif country:
        parts.append(f'{flag_img} {country}')
    elif city:
        parts.append(city)
    sep = '</span> <span class="geo-tag">'
    return f'<span class="geo-tag">{sep.join(parts)}</span>' if parts else ""


def _render_ips_section(html_parts: list, item: dict):
    ips = item.get("ips", [])
    all_ips_text = "\n".join(esc(ip_entry.get("direct_ip_connections", "?")) for ip_entry in ips)
    html_parts.append(f'<div class="section-title" style="display:flex;align-items:center;gap:10px"><span>🌐 Связанные IP-адреса ({len(ips)})</span><div class="copy-btn-wrap"><button class="copy-btn" onclick="copyText(\'{all_ips_text.replace("'", "\\\'")}\')" data-tip="Скопировать все IP-адреса">📋</button></div></div>')
    for idx, ip_entry in enumerate(ips[:20]):
        ip_addr = ip_entry.get("direct_ip_connections", "?")
        shared = ip_entry.get("shared_with", [])
        owned_by_primary = ip_entry.get("owned_by_primary", False)
        owned_by_alt = ip_entry.get("owned_by_alt", False)
        vpn_info = ip_entry.get("vpn_info", {})
        vpn_badges = ""
        if vpn_info.get("proxy"):
            vpn_badges = '<span class="tag tag-red">VPN</span>'
        if vpn_info.get("hosting"):
            vpn_badges += '<span class="tag tag-cyan">Хостинг</span>'
        geo_badge = _geo_html(vpn_info)
        owner_tag = '<span class="tag tag-green">Основной</span>' if owned_by_primary else ('<span class="tag tag-orange">Альт</span>' if owned_by_alt else '<span class="tag tag-red">Чужой</span>')
        shared_html = f'<div class="field"><span class="key">Общие с</span><span class="val purple">{esc(", ".join(shared[:8]))}</span></div>' if shared else ""
        html_parts.append(f'''<div class="info-card" style="background:#252526">
            <div class="badge bad-purple">{idx+1}</div>
            <div class="card-fields">
              <div class="field"><span class="key">IP</span><span class="val mono cyan">{esc(ip_addr)}</span> {owner_tag} {vpn_badges} {geo_badge}</div>
              {shared_html}
            </div>
          </div>''')


def _render_hwids_section(html_parts: list, item: dict):
    hwids = item.get("hwids", [])
    all_hwids_text = "\n".join(esc(hw_entry.get("hwid", "?")) for hw_entry in hwids)
    html_parts.append(f'<div class="section-title" style="display:flex;align-items:center;gap:10px"><span>🔑 Связанные HWID ({len(hwids)})</span><div class="copy-btn-wrap"><button class="copy-btn" onclick="copyText(\'{all_hwids_text.replace("'", "\\\'")}\')" data-tip="Скопировать все HWID">📋</button></div></div>')
    for idx, hw_entry in enumerate(hwids[:20]):
        hwid = hw_entry.get("hwid", "?")
        shared = hw_entry.get("shared_with", [])
        owned_by_primary = hw_entry.get("owned_by_primary", False)
        owned_by_alt = hw_entry.get("owned_by_alt", False)
        owner_tag = '<span class="tag tag-green">Основной</span>' if owned_by_primary else ('<span class="tag tag-orange">Альт</span>' if owned_by_alt else '<span class="tag tag-red">Чужой</span>')
        shared_html = f'<div class="field"><span class="key">Общие с</span><span class="val purple">{esc(", ".join(shared[:8]))}</span></div>' if shared else ""
        html_parts.append(f'''<div class="info-card" style="background:#252526">
            <div class="badge bad-orange">{idx+1}</div>
            <div class="card-fields">
              <div class="field"><span class="key">HWID</span><span class="val mono">{esc(hwid)}</span> {owner_tag}</div>
              {shared_html}
            </div>
          </div>''')


def _render_denied_logins_section(html_parts: list, item: dict):
    attempts = item.get("attempts", [])
    if not attempts:
        return
    html_parts.append(f'<div class="section-title">🚫 Отклонённые входы ({len(attempts)})</div>')
    for ai, a in enumerate(attempts[:12]):
        t = a.get("time", "?")[:19]
        u = a.get("user_name", "?")
        ip_addr = a.get("ip_address", "?")
        server = a.get("server", "?")
        hwid = a.get("hwid", "")
        stripe = "#2a2a2a" if ai % 2 == 0 else "#252526"
        vpn_info = a.get("vpn_info", {})
        vpn_badge = ""
        if vpn_info.get("proxy"):
            vpn_badge = '<span class="tag tag-red">VPN</span>'
        if vpn_info.get("hosting"):
            vpn_badge += '<span class="tag tag-cyan">Хостинг</span>'
        geo_badge = _geo_html(vpn_info)
        hwid_html = f'<div class="field"><span class="key">HWID</span><span class="val mono gray">{esc(hwid)}</span></div>' if hwid else ""
        html_parts.append(f'''<div class="info-card" style="background:{stripe}">
            <div class="badge bad-red">{ai+1}</div>
            <div class="card-fields">
              <div class="field"><span class="key">Время</span><span class="val">{esc(t)}</span></div>
              <div class="field"><span class="key">Ник</span><span class="val yellow">{esc(u)}</span></div>
              <div class="field"><span class="key">IP</span><span class="val mono cyan">{esc(ip_addr)}</span> {vpn_badge} {geo_badge}</div>
              <div class="field"><span class="key">Сервер</span><span class="val">{esc(server)}</span></div>
              {hwid_html}
            </div>
          </div>''')
