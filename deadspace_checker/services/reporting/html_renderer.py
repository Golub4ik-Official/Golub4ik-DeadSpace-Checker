import logging
import os
import webbrowser
from datetime import datetime
from typing import List, Dict

from ..graph_service import generate_vis_graph_from_report_data
from ..vpn_detector import enrich_report_data
from .html_builder import (
    REPORT_CSS, BAN_BYPASS_CSS,
    esc, build_report_script, collect_nickname_data,
    _render_accounts_section, _render_punishments_section, _render_complaints_section,
    _render_ips_section, _render_hwids_section, _render_denied_logins_section
)


def render_scan_report_html(data: List[dict], logo_b64: str = "") -> str:
    enrich_report_data(data)

    player = data[0] if data else {}
    nick = player.get("nickname", "Неизвестно")
    primary = player.get("primary_nickname", nick)
    status = player.get("status", "unknown")
    ban_counts = player.get("ban_counts", 0)

    status_lower = status.lower()
    if status_lower in ("banned", "suspicious", "clean"):
        status_color = {"banned": "#ef4444", "suspicious": "#fbbf24", "clean": "#22c55e"}[status_lower]
        status_ru = {"banned": "ЗАБАНЕН", "suspicious": "ПОДОЗРИТЕЛЬНЫЙ", "clean": "ЧИСТ"}[status_lower]
    elif status_lower in ("unknown", "not_found", ""):
        status_ru = "НЕ НАЙДЕН"
        status_color = "#6b7280"
    else:
        status_ru = status
        status_color = "#6b7280"

    has_data = len(data) > 1

    html_parts = ['<!DOCTYPE html><html lang="ru"><head><meta charset="utf-8">']
    html_parts.append(f"<title>DeadSpace Check — {esc(primary)}</title>")
    html_parts.append(f"<style>{REPORT_CSS % (status_color, status_color)}</style>")
    html_parts.append('<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/vis-network/9.1.2/dist/dist/vis-network.min.css">')
    html_parts.append('<script src="https://cdnjs.cloudflare.com/ajax/libs/vis-network/9.1.2/dist/vis-network.min.js"></script>')
    html_parts.append(f'</head><body><div class="report">')
    logo_html = f'<img src="data:image/png;base64,{logo_b64}" width="48" height="48" alt="" style="border-radius:6px;border:1px solid #2a2a50">' if logo_b64 else ""
    support_html = '<div style="text-align:right;font-size:11px;white-space:nowrap"><a href="#" onclick="showSupport()" style="color:#fbbf24;text-decoration:none;font-weight:600">❤️ Поддержать автора</a></div>'
    html_parts.append(f'  <div class="header"><div class="header-left"><h1>🔍 {esc(primary)}</h1><div class="sub">Ник поиска: {esc(nick)}</div></div><div style="display:flex;align-items:center;gap:10px">{logo_html}{support_html}</div></div>')
    html_parts.append(f'<span class="status-badge">{esc(status_ru)}</span>')

    if not has_data:
        not_found_msg = (
            f'<div style="text-align:center;padding:48px 16px;margin-top:24px;'
            f'background:#0f0f24;border-radius:8px;border:1px solid #2a2a50">'
            f'<div style="font-size:48px;margin-bottom:12px">🌌</div>'
            f'<div style="font-size:18px;color:#e2e8f0;margin-bottom:8px">Игрок <strong>{esc(primary)}</strong> не найден</div>'
            f'<div style="font-size:13px;color:#6b7280">'
            f'По запросу «{esc(nick)}» не найдено ни одного аккаунта в системе Dead Space 14.<br>'
            f'Возможно, игрок никогда не заходил на сервер или указан неверный ник.</div></div>'
        )
        html_parts.append(not_found_msg)
    else:
        nickname_data = collect_nickname_data(data)
        html_parts.append(build_report_script(nickname_data))

        graph_injected = False
        for item in data[1:]:
            typ = item.get("type", "")
            if typ == "associated_accounts":
                _render_accounts_section(html_parts, item, graph_injected)
                if not graph_injected:
                    html_parts.append(generate_vis_graph_from_report_data(data, primary_nickname=primary))
                    graph_injected = True
            elif typ == "punishments":
                _render_punishments_section(html_parts, item)
            elif typ == "complaints":
                _render_complaints_section(html_parts, item)
            elif typ == "associated_ips":
                _render_ips_section(html_parts, item)
            elif typ == "associated_hwids":
                _render_hwids_section(html_parts, item)
            elif typ == "denied_login_attempts":
                _render_denied_logins_section(html_parts, item)

    html_parts.append("""
<div id="supportModal" style="display:none;position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,0.7);z-index:999;align-items:center;justify-content:center" onclick="if(event.target===this)closeSupport()">
<div style="background:#0f0f24;border:1px solid #2a2a50;border-radius:12px;padding:24px;max-width:440px;width:90%;color:#d4d4d4;font-family:'Segoe UI',sans-serif">
<h2 style="color:#22d3ee;margin:0 0 4px;font-size:18px">❤️ Поддержать автора</h2>
<p style="color:#d4d4d4;font-size:13px;margin:8px 0 14px">Спасибо, что используете DeadSpace Checker! Если проект вам помог, вы можете поддержать автора:</p>
<div style="margin:10px 0">
<div style="display:flex;align-items:center;gap:6px;padding:6px 0"><span style="color:#fbbf24;font-weight:600;min-width:100px">Карта Сбербанк:</span><span style="font-family:Consolas,monospace;font-size:13px;color:#e2e8f0">2202 2068 9547 6567</span><button onclick="copyText('2202206895476567')" style="background:#151530;color:#22d3ee;border:1px solid #2a2a50;border-radius:4px;cursor:pointer;font-size:12px;padding:2px 6px">📋</button></div>
<div style="display:flex;align-items:center;gap:6px;padding:6px 0"><span style="color:#fbbf24;font-weight:600;min-width:100px">Boosty:</span><a href="https://boosty.to/golub4ik" target="_blank" style="color:#22d3ee;font-size:13px">boosty.to/golub4ik</a><span style="color:#6b7280;font-size:11px">(скоро будет работать)</span><button onclick="copyText('https://boosty.to/golub4ik')" style="background:#151530;color:#22d3ee;border:1px solid #2a2a50;border-radius:4px;cursor:pointer;font-size:12px;padding:2px 6px">📋</button></div>
<div style="display:flex;align-items:center;gap:6px;padding:6px 0"><span style="color:#fbbf24;font-weight:600;min-width:100px">Steam:</span><span style="font-family:Consolas,monospace;font-size:13px;color:#e2e8f0">osnova_golubia</span><span style="color:#6b7280;font-size:11px">(Россия)</span><button onclick="copyText('osnova_golubia')" style="background:#151530;color:#22d3ee;border:1px solid #2a2a50;border-radius:4px;cursor:pointer;font-size:12px;padding:2px 6px">📋</button></div>
</div>
<p style="color:#6b7280;font-size:11px;margin:8px 0 0">Boosty пока не работает, но скоро будет доступен</p>
<button onclick="closeSupport()" style="margin-top:14px;background:#151530;color:#22d3ee;border:1px solid #2a2a50;border-radius:6px;padding:8px 20px;cursor:pointer;font-size:13px;font-weight:600">Закрыть</button>
</div></div>
<script>
function copyText(t){if(navigator.clipboard&&navigator.clipboard.writeText)navigator.clipboard.writeText(t).catch(function(){fallbackCopy(t)});else fallbackCopy(t)}
function fallbackCopy(t){var e=document.createElement('textarea');e.value=t;e.style.position='fixed';e.style.left='-9999px';document.body.appendChild(e);e.select();try{document.execCommand('copy')}catch(ex){}document.body.removeChild(e)}
function showSupport(){document.getElementById('supportModal').style.display='flex'}
function closeSupport(){document.getElementById('supportModal').style.display='none'}
</script>""")
    html_parts.append('<div class="footer">🚀 <span class="brand">Golub4ik (WikiHampter) DeadSpace Checker</span> ☆ Dead Space 14</div>')
    html_parts.append('</div></body></html>')
    return "".join(html_parts)


def render_ban_bypass_report_html(report_data: List[dict]) -> str:
    confidence_config = {
        "HWID_MATCH":       {"color": "#ef4444", "label": "HWID-совпадение",  "cls": "hwid"},
        "IP_VERY_CLOSE_TIME":{"color": "#fbbf24", "label": "IP+время (очень близко)", "cls": "ip-very-close"},
        "IP_CLOSE_TIME":    {"color": "#f59e0b", "label": "IP+время (близко)", "cls": "ip-close"},
        "IP_MODERATE_TIME": {"color": "#22d3ee", "label": "IP+время (умеренно)", "cls": "ip-moderate"},
        "IP_DISTANT_TIME":  {"color": "#22d3ee", "label": "IP+время (давно)", "cls": "ip-distant"},
        "IP_MATCH":         {"color": "#6b7280", "label": "IP-совпадение",     "cls": "ip-match"},
        "NO_MATCH":         {"color": "#374151", "label": "Нет совпадений",    "cls": "no-match"},
    }

    html_parts = ['<!DOCTYPE html><html lang="ru"><head><meta charset="utf-8">']
    html_parts.append('<title>Проверка обхода банов — DeadSpace Checker</title>')
    html_parts.append(f'<style>{BAN_BYPASS_CSS}</style>')
    html_parts.append('</head><body><div class="wrap">')

    scan_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    html_parts.append(f'<div style="display:flex;justify-content:space-between;align-items:flex-start"><div><h1>🛡 Проверка обхода банов</h1><div class="sub">Время сканирования: {esc(scan_time)} | Всего записей: {len(report_data)}</div></div><div style="text-align:right;font-size:11px;white-space:nowrap"><a href="#" onclick="showSupport()" style="color:#fbbf24;text-decoration:none;font-weight:600">❤️ Поддержать автора</a></div></div>')

    total = len(report_data)
    hwid_matches = sum(1 for r in report_data if r.get("ban_bypass_confidence") == "HWID_MATCH")
    ip_matches = sum(1 for r in report_data if r.get("ban_bypass_confidence", "").startswith("IP_"))
    with_findings = sum(1 for r in report_data if r.get("ban_bypass_confidence") != "NO_MATCH")

    html_parts.append('<div class="summary">')
    html_parts.append(f'<div class="sum-card"><div class="num">{total}</div><div class="lbl">Всего проверено</div></div>')
    html_parts.append(f'<div class="sum-card"><div class="num">{with_findings}</div><div class="lbl">Найдено обходов</div></div>')
    html_parts.append(f'<div class="sum-card"><div class="num">{hwid_matches}</div><div class="lbl">HWID совпадений</div></div>')
    html_parts.append(f'<div class="sum-card"><div class="num">{ip_matches}</div><div class="lbl">IP совпадений</div></div>')
    html_parts.append('</div>')

    if not report_data:
        html_parts.append('<div style="text-align:center;padding:48px 0;color:#888;font-size:16px">✅ Обходов бана не обнаружено</div>')
    else:
        for idx, r in enumerate(report_data, 1):
            confidence = r.get("ban_bypass_confidence", "NO_MATCH")
            conf = confidence_config.get(confidence, confidence_config["NO_MATCH"])
            banned = esc(r.get("author_name", "?"))
            author_id = esc(str(r.get("author_id", "")))
            ban_time = esc(r.get("ban_time", "")[:19])
            message_link = r.get("message_link", "")
            scan_time_raw = esc(r.get("scan_time", "")[:19])
            hwid_erased = r.get("hwid_erased", False)
            search_depth = r.get("search_depth", "?")
            connections = r.get("connections_analyzed", "?")
            success_status = r.get("bypass_success_status", "Unknown")
            results = r.get("results", [{}])[0]
            ip_address = esc(results.get("ip_address", ""))
            hwid_val = esc(results.get("hwid", ""))
            ban_entries = r.get("all_ban_entries", [])
            ban_reason = esc(ban_entries[0].get("ban_reason", "")) if ban_entries else ""

            card_cls = conf["cls"]
            html_parts.append(f'<div class="bypass-card {card_cls}">')
            html_parts.append(f'  <div class="card-header">')
            html_parts.append(f'    <div>')
            html_parts.append(f'      <div class="name">{idx}. {banned} <span class="author-id">(ID: {author_id})</span></div>')
            html_parts.append(f'    </div>')
            html_parts.append(f'    <span class="conf-badge" style="background:{conf["color"]}">{esc(conf["label"])}</span>')
            html_parts.append(f'  </div>')
            html_parts.append(f'  <div class="card-body">')

            if ban_reason:
                html_parts.append(f'    <div class="field"><span class="key">Причина</span><span class="val">{ban_reason}</span></div>')
            html_parts.append(f'    <div class="field"><span class="key">Время бана</span><span class="val">{ban_time}</span></div>')
            html_parts.append(f'    <div class="field"><span class="key">IP адрес</span><span class="val mono cyan">{ip_address}</span></div>')
            if hwid_val and not hwid_val.isspace():
                hwid_display = f'<span class="mono gray">{esc(hwid_val[:64])}</span>'
                if hwid_erased:
                    hwid_display += ' <span class="status-fail">HWID стёрт</span>'
                html_parts.append(f'    <div class="field"><span class="key">HWID</span><span class="val">{hwid_display}</span></div>')
            elif hwid_erased:
                html_parts.append(f'    <div class="field"><span class="key">HWID</span><span class="val"><span class="status-fail">Стёрт</span></span></div>')
            html_parts.append(f'    <div class="field"><span class="key">Глубина</span><span class="val gray">{search_depth} | {connections} соединений</span></div>')
            if message_link:
                html_parts.append(f'    <div class="field"><span class="key">Ссылка</span><a class="val link" href="{esc(message_link)}">{esc(message_link[:80])}{"..." if len(message_link) > 80 else ""}</a></div>')

            bypass_users = r.get("bypass_user_names", [])
            html_parts.append(f'    <div class="twins-section">')
            html_parts.append(f'      <div class="twin-title">Твинки ({len(bypass_users)}) — статус: <span class="green">{"✅" if "Successful" in success_status else "❌" if "Unsuccessful" in success_status else "❓"}</span> {esc(success_status)}</div>')
            if bypass_users:
                for twin_name in bypass_users:
                    twin_ip = ""
                    twin_hwid = ""
                    for conn_ref in [r]:
                        ref_results = conn_ref.get("results", [{}])[0]
                        initial_acc = ref_results.get("initial_account", {})
                        assoc_ips = initial_acc.get("associated_ips", {})
                        assoc_hwids = initial_acc.get("associated_hwids", {})
                        for ip_candidates in assoc_ips.values():
                            for candidate in (ip_candidates if isinstance(ip_candidates, list) else []):
                                if isinstance(candidate, str) and candidate.lower() == twin_name.lower():
                                    pass
                        for ip_addr, users in assoc_ips.items():
                            if isinstance(users, list) and twin_name in users:
                                twin_ip = ip_addr
                                break
                        for hwid_str, users in assoc_hwids.items():
                            if isinstance(users, list) and twin_name in users:
                                twin_hwid = hwid_str
                                break
                    safe_twin = esc(twin_name)
                    html_parts.append(f'      <div class="twin-item">')
                    html_parts.append(f'        <span class="twin-name">👤 {safe_twin}</span>')
                    if twin_ip:
                        html_parts.append(f'        <span class="twin-ip">🌐 {esc(twin_ip)}</span>')
                    if twin_hwid:
                        html_parts.append(f'        <span class="twin-hwid">🔑 {esc(twin_hwid[:48])}</span>')
                    html_parts.append(f'      </div>')
            else:
                twin_ip = ip_address
                twin_hwid_display = hwid_val
                html_parts.append(f'      <div class="no-twins">Твинки не найдены (забанен по IP/HWID, но другие аккаунты не обнаружены)</div>')
            html_parts.append(f'    </div>')

            complaint_links = results.get("complaint_links", [])
            if complaint_links:
                html_parts.append(f'    <div class="field" style="margin-top:6px"><span class="key">Жалобы</span><span class="val orange">{len(complaint_links)} жалоб на других серверах</span></div>')

            html_parts.append(f'  </div>')
            html_parts.append(f'</div>')

    html_parts.append("""
<div id="supportModal" style="display:none;position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,0.7);z-index:999;align-items:center;justify-content:center" onclick="if(event.target===this)closeSupport()">
<div style="background:#0f0f24;border:1px solid #2a2a50;border-radius:12px;padding:24px;max-width:440px;width:90%;color:#d4d4d4;font-family:'Segoe UI',sans-serif">
<h2 style="color:#22d3ee;margin:0 0 4px;font-size:18px">❤️ Поддержать автора</h2>
<p style="color:#d4d4d4;font-size:13px;margin:8px 0 14px">Спасибо, что используете DeadSpace Checker! Если проект вам помог, вы можете поддержать автора:</p>
<div style="margin:10px 0">
<div style="display:flex;align-items:center;gap:6px;padding:6px 0"><span style="color:#fbbf24;font-weight:600;min-width:100px">Карта Сбербанк:</span><span style="font-family:Consolas,monospace;font-size:13px;color:#e2e8f0">2202 2068 9547 6567</span><button onclick="copyText('2202206895476567')" style="background:#151530;color:#22d3ee;border:1px solid #2a2a50;border-radius:4px;cursor:pointer;font-size:12px;padding:2px 6px">📋</button></div>
<div style="display:flex;align-items:center;gap:6px;padding:6px 0"><span style="color:#fbbf24;font-weight:600;min-width:100px">Boosty:</span><a href="https://boosty.to/golub4ik" target="_blank" style="color:#22d3ee;font-size:13px">boosty.to/golub4ik</a><span style="color:#6b7280;font-size:11px">(скоро будет работать)</span><button onclick="copyText('https://boosty.to/golub4ik')" style="background:#151530;color:#22d3ee;border:1px solid #2a2a50;border-radius:4px;cursor:pointer;font-size:12px;padding:2px 6px">📋</button></div>
<div style="display:flex;align-items:center;gap:6px;padding:6px 0"><span style="color:#fbbf24;font-weight:600;min-width:100px">Steam:</span><span style="font-family:Consolas,monospace;font-size:13px;color:#e2e8f0">osnova_golubia</span><span style="color:#6b7280;font-size:11px">(Россия)</span><button onclick="copyText('osnova_golubia')" style="background:#151530;color:#22d3ee;border:1px solid #2a2a50;border-radius:4px;cursor:pointer;font-size:12px;padding:2px 6px">📋</button></div>
</div>
<p style="color:#6b7280;font-size:11px;margin:8px 0 0">Boosty пока не работает, но скоро будет доступен</p>
<button onclick="closeSupport()" style="margin-top:14px;background:#151530;color:#22d3ee;border:1px solid #2a2a50;border-radius:6px;padding:8px 20px;cursor:pointer;font-size:13px;font-weight:600">Закрыть</button>
</div></div>
<script>
function copyText(t){if(navigator.clipboard&&navigator.clipboard.writeText)navigator.clipboard.writeText(t).catch(function(){fallbackCopy(t)});else fallbackCopy(t)}
function fallbackCopy(t){var e=document.createElement('textarea');e.value=t;e.style.position='fixed';e.style.left='-9999px';document.body.appendChild(e);e.select();try{document.execCommand('copy')}catch(ex){}document.body.removeChild(e)}
function showSupport(){document.getElementById('supportModal').style.display='flex'}
function closeSupport(){document.getElementById('supportModal').style.display='none'}
</script>""")
    html_parts.append('<div class="footer">🚀 <span class="brand">Golub4ik (WikiHampter) DeadSpace Checker</span> ☆ Dead Space 14</div>')
    html_parts.append('</div></body></html>')
    return "".join(html_parts)


def write_report_html(data: List[dict], output_path: str, logo_path: str = "") -> str:
    logo_b64 = ""
    if logo_path:
        try:
            import base64
            with open(logo_path, "rb") as f:
                logo_b64 = base64.b64encode(f.read()).decode()
        except Exception:
            pass

    html = render_scan_report_html(data, logo_b64)
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(html)
    logging.info(f"HTML report saved to '{output_path}'")
    webbrowser.open(f'file://{os.path.abspath(output_path)}')
    return html


def write_ban_bypass_html(report_data: List[dict], output_path: str) -> str:
    html = render_ban_bypass_report_html(report_data)
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(html)
    logging.info(f"Ban bypass HTML report saved to '{output_path}'")
    webbrowser.open(f'file://{os.path.abspath(output_path)}')
    return html
