import re
import tkinter as tk


ANSI_RE = re.compile(r'\x1b\[[\d;]*[a-zA-Z]')

ANSI_TAG_MAP = {
    '0': '_reset',
    '1': 'bold',
    '4': 'underline',
    '90': 'gray',
    '91': 'red',
    '92': 'green',
    '93': 'yellow',
    '94': 'blue',
    '95': 'magenta',
    '96': 'cyan',
    '97': 'white',
}

TAG_COLORS = {
    'red': ('#f07178', 'normal'),
    'green': ('#c3e88d', 'normal'),
    'yellow': ('#ffcb6b', 'normal'),
    'blue': ('#82aaff', 'normal'),
    'magenta': ('#c792ea', 'normal'),
    'cyan': ('#89ddff', 'normal'),
    'white': ('#eeffff', 'normal'),
    'gray': ('#546e7a', 'normal'),
    'bold_red': ('#f07178', 'bold'),
    'bold_green': ('#c3e88d', 'bold'),
    'bold_yellow': ('#ffcb6b', 'bold'),
    'bold_blue': ('#82aaff', 'bold'),
    'bold_magenta': ('#c792ea', 'bold'),
    'bold_cyan': ('#89ddff', 'bold'),
    'bold_white': ('#ffffff', 'bold'),
    'bold': ('#eeffff', 'bold'),
    'underline': ('#eeffff', 'normal'),
}


def setup_color_tags(text_widget):
    for name, (fg, weight) in TAG_COLORS.items():
        opts = {'foreground': fg}
        if weight == 'bold':
            opts['font'] = ("Consolas", 9, "bold")
        if name == 'underline':
            opts['underline'] = True
        text_widget.tag_config(name, **opts)


def ensure_tag(text_widget, name):
    if name not in text_widget.tag_names():
        opts = TAG_COLORS.get(name, {})
        if opts:
            text_widget.tag_config(name, **opts)


def insert_colored(text_widget, text):
    parts = re.split(r'(\x1b\[[\d;]*m)', text)
    active_tags = []
    for part in parts:
        if not part:
            continue
        if part.startswith('\x1b[') and part.endswith('m'):
            code = part[2:-1]
            if not code or code == '0':
                active_tags = []
            else:
                codes = code.split(';')
                for c in codes:
                    tag = ANSI_TAG_MAP.get(c)
                    if tag == '_reset':
                        active_tags = []
                    elif tag and tag not in active_tags:
                        active_tags.append(tag)
        else:
            for t in active_tags:
                ensure_tag(text_widget, t)
            if active_tags:
                text_widget.insert(tk.END, part, tuple(active_tags))
            else:
                text_widget.insert(tk.END, part)
