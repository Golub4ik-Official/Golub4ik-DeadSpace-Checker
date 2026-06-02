import tkinter as tk


def add_section_embed(output_text, title, accent_color, fields, copy_text=None):
    outer = tk.Frame(output_text, bg='#252526', bd=1, relief='solid',
                     highlightbackground='#3a3a3a', padx=0, pady=0)
    accent = tk.Frame(outer, bg=accent_color, width=4)
    accent.pack(side='left', fill='y')
    content = tk.Frame(outer, bg='#252526', padx=10, pady=6)
    content.pack(side='left', fill='x', expand=True)

    title_row = tk.Frame(content, bg='#252526')
    title_row.pack(fill='x')
    tk.Label(title_row, text=title,
             font=('Consolas', 10, 'bold'), fg=accent_color, bg='#252526').pack(side='left')
    if copy_text:
        tk.Button(title_row, text='📋', font=('Consolas', 9),
                  command=lambda t=copy_text: _copy_to_clipboard(output_text, t),
                  bg='#333333', fg='#eeffff', bd=0, padx=4, cursor='hand2',
                  activebackground='#444444').pack(side='right')

    tk.Frame(content, bg='#3a3a3a', height=1).pack(fill='x', pady=4)

    for field in fields:
        suffix = None
        if len(field) == 4:
            label, value, val_color, suffix = field
        else:
            label, value, val_color = field
        row = tk.Frame(content, bg='#252526')
        row.pack(fill='x', pady=1)
        tk.Label(row, text=label + ':', font=('Consolas', 9, 'bold'),
                 fg='#969696', bg='#252526', width=14, anchor='w').pack(side='left')
        lbl = tk.Label(row, text=str(value), font=('Consolas', 9),
                       fg=val_color, bg='#252526', anchor='w', wraplength=500, justify='left')
        lbl.pack(side='left', fill='x', expand=True)
        if suffix:
            tk.Label(row, text=str(suffix), font=('Consolas', 9),
                     fg='#969696', bg='#252526', anchor='w').pack(side='left')

    output_text.window_create(tk.END, window=outer)
    output_text.insert(tk.END, '\n')


def _copy_to_clipboard(output_text, text):
    output_text.clipboard_clear()
    output_text.clipboard_append(text)


def build_punishment_fields(data):
    st = data.get('status', '').upper()
    if st == 'BANNED':
        return '#f07178', 'ЗАБАНЕН', '#f07178'
    elif st == 'SUSPICIOUS':
        return '#ffcb6b', 'ПОДОЗРИТЕЛЬНЫЙ', '#ffcb6b'
    elif st == 'CLEAN':
        return '#c3e88d', 'ЧИСТ', '#c3e88d'
    return '#546e7a', st, '#546e7a'


def render_player_summary(output_text, d):
    st = d.get('status', '').upper()
    if st == 'BANNED':
        ac, st_txt, sc = '#f07178', 'ЗАБАНЕН', '#f07178'
    elif st == 'SUSPICIOUS':
        ac, st_txt, sc = '#ffcb6b', 'ПОДОЗРИТЕЛЬНЫЙ', '#ffcb6b'
    elif st == 'CLEAN':
        ac, st_txt, sc = '#c3e88d', 'ЧИСТ', '#c3e88d'
    else:
        ac, st_txt, sc = '#546e7a', st, '#546e7a'
    search_nick = d.get('nickname', '?')
    primary_nick = d.get('primary', search_nick)
    fields = [
        ('Статус', st_txt, sc),
        ('Наказаний', str(d.get('ban_counts', 0)), '#ffcb6b'),
        ('HWID стёрт', 'Да' if d.get('hwid_erased') else 'Нет', '#969696'),
    ]
    if primary_nick != search_nick:
        fields.insert(0, ('Основной ник', primary_nick, '#ffcb6b'))
    copy = '\n'.join([
        f"Игрок: {search_nick}",
        f"Статус: {st}",
        f"Наказаний: {d.get('ban_counts', 0)}",
    ])
    add_section_embed(output_text, f"ИГРОК: {search_nick}", ac, fields, copy_text=copy)


def render_punishment(output_text, d):
    ac, st_txt, sc = build_punishment_fields(d)
    player_nick = d.get('player', '?')
    banned_nick = d.get('banned_nickname', player_nick)
    is_alt = banned_nick != player_nick
    nickname_display = banned_nick
    nickname_suffix = ' (альт)' if is_alt else None
    admin = d.get('admin', 'N/A')
    ban_type = d.get('ban_type', '')
    ban_date = d.get('ban_date', '')
    ban_expires = d.get('ban_expires', '')
    date_str = ''
    if ban_date and ban_date != 'N/A':
        date_str = ban_date
        if ban_expires and ban_expires != 'N/A' and ban_expires.lower() not in ('никогда', 'never'):
            date_str += f' → {ban_expires}'
    copy = '\n'.join([
        f"Наказание #{d.get('index', '?')}",
        f"Игрок: {player_nick}",
        f"Статус: {d.get('status', '?')}",
        f"Причина: {d.get('reason', '?')}",
        f"Никнейм: {banned_nick}{' (альт)' if is_alt else ''}",
        f"Выдал: {admin}",
        f"Тип: {ban_type}" if ban_type and ban_type != 'N/A' else '',
        f"Дата: {date_str}" if date_str else '',
    ])
    fields = [
        ('Игрок', player_nick, '#eeffff'),
        ('Статус', st_txt, sc),
        ('Причина', d.get('reason', '?'), '#ffcb6b'),
    ]
    if ban_type and ban_type != 'N/A':
        fields.append(('Тип', ban_type, '#c792ea'))
    if nickname_suffix:
        fields.append(('Никнейм', nickname_display, '#82aaff', nickname_suffix))
    else:
        fields.append(('Никнейм', nickname_display, '#82aaff'))
    fields.append(('Выдал', admin, '#82aaff'))
    if date_str:
        fields.append(('Дата', date_str, '#89ddff'))
    add_section_embed(output_text, f"НАКАЗАНИЕ #{d.get('index', '?')}", ac, fields, copy_text=copy)


def render_nicknames(output_text, d):
    nicks = d.get('nicknames', [])
    copy = '\n'.join(nicks)
    max_show = 12
    shown = nicks[:max_show]
    rest = len(nicks) - max_show
    lines = shown[:]
    if rest > 0:
        lines.append(f"... и ещё {rest}")
    add_section_embed(output_text, f"НИКНЕЙМЫ ({len(nicks)})", '#82aaff', [
        ('Основной', d.get('primary', '?'), '#eeffff'),
        ('Всего', str(len(nicks)), '#82aaff'),
        ('Список', '\n'.join(lines), '#c792ea'),
    ], copy_text=copy)


def render_complaint(output_text, d):
    link = d.get('link', '?')
    copy = '\n'.join([
        f"Жалоба #{d.get('index', '?')}",
        f"Канал: {d.get('channel', '?')}",
        f"Автор: {d.get('author', '?')}",
        f"Ссылка: {link}",
    ])
    add_section_embed(output_text, f"ЖАЛОБА #{d.get('index', '?')}", '#f07178', [
        ('Канал', d.get('channel', '?'), '#eeffff'),
        ('Автор', d.get('author', '?'), '#82aaff'),
        ('Ссылка', link, '#89ddff'),
        ('Содержание', d.get('content', '')[:200], '#969696'),
    ], copy_text=copy)


def render_ips(output_text, d):
    items = d.get('items', [])
    copy = '\n'.join(items)
    max_show = 15
    shown = items[:max_show]
    rest = len(items) - max_show
    lines = shown[:]
    if rest > 0:
        lines.append(f"... и ещё {rest}")
    add_section_embed(output_text, f"IP-АДРЕСА ({len(items)})", '#89ddff', [
        ('Всего', str(len(items)), '#89ddff'),
        ('Основной', d.get('primary', '?'), '#eeffff'),
        ('Список', '\n'.join(lines), '#c792ea'),
    ], copy_text=copy)


def render_hwids(output_text, d):
    items = d.get('items', [])
    copy = '\n'.join(items)
    max_show = 15
    shown = items[:max_show]
    rest = len(items) - max_show
    lines = shown[:]
    if rest > 0:
        lines.append(f"... и ещё {rest}")
    add_section_embed(output_text, f"HWID ({len(items)})", '#89ddff', [
        ('Всего', str(len(items)), '#89ddff'),
        ('Основной', d.get('primary', '?'), '#eeffff'),
        ('Список', '\n'.join(lines), '#c792ea'),
    ], copy_text=copy)


def render_denied_logins(output_text, d):
    logins = d.get('logins', [])
    max_show = 8
    copy = '\n'.join([
        f"{l.get('time', '?')} | {l.get('user_name', '?')} | {l.get('ip_address', '?')}"
        for l in logins
    ])
    lines = []
    for l in logins[:max_show]:
        t = l.get('time', '?')[:19]
        u = l.get('user_name', '?')
        ip = l.get('ip_address', '?')
        lines.append(f"{t} | {u} | {ip}")
    if len(logins) > max_show:
        lines.append(f"... и ещё {len(logins) - max_show}")
    add_section_embed(output_text, f"ОТКЛОНЁННЫЕ ВХОДЫ ({len(logins)})", '#f07178', [
        ('Всего', str(len(logins)), '#f07178'),
        ('Последние', '\n'.join(lines), '#eeffff'),
    ], copy_text=copy)
