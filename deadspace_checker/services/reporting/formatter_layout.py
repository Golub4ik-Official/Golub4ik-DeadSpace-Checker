from typing import Dict, Any, List, Optional, Tuple

from .constants import LAYOUT_CONFIG, DEFAULT_REPORT_CONFIG


class FormatterLayoutMixin:

    def print_list_items(self, items: List[str],
                         box_v_char: str, 
                         base_indent_str: str, 
                         item_indent_level: int = 1, 
                         prefix_char_key: str = 'BULLET',
                         fmt_key: Optional[str] = None,
                         max_items: Optional[int] = None) -> None:

        if not items:
            line_indent = LAYOUT_CONFIG['DEFAULT_INDENT_STRING'] * item_indent_level
            self.print_line_in_box(f"{line_indent}{self._get_fmt('GRAY')}None{self.fmt['END']}", box_v_char, base_indent_str)
            return

        bullet = self.box.get(prefix_char_key.upper(), prefix_char_key)
        item_color = self.fmt.get(fmt_key.upper(), self._get_fmt('WHITE')) if fmt_key else self._get_fmt('WHITE')
        
        effective_max_items = max_items if max_items is not None else self.config.get_dynamic_limit('LARGE') 

        line_indent_str = LAYOUT_CONFIG['DEFAULT_INDENT_STRING'] * item_indent_level

        for i, item_text in enumerate(items[:effective_max_items]):
            formatted_item_text = f"{item_color}{item_text}{self.fmt['END']}" if fmt_key or item_color != self._get_fmt('WHITE') else item_text
            line_content = f"{line_indent_str}{bullet} {formatted_item_text}"
            self.print_line_in_box(line_content, box_v_char, base_indent_str)

        if len(items) > effective_max_items:
            remaining_count = len(items) - effective_max_items
            line_content = f"{line_indent_str}{bullet} {self._get_fmt('GRAY')}... and {remaining_count} more{self.fmt['END']}"
            self.print_line_in_box(line_content, box_v_char, base_indent_str)

    def print_table_row(self, columns: List[Any], widths: List[int],
                        box_v_char: str, base_indent_str: str,
                        fmt_keys: Optional[List[Optional[Tuple[str, ...]]]] = None) -> None:
        
        if fmt_keys is None:
            fmt_keys_tuples: List[Optional[Tuple[str, ...]]] = [('WHITE',)] * len(columns)
        else:
            fmt_keys_tuples = []
            for fk_idx, fk in enumerate(fmt_keys):
                if fk is None:
                    fmt_keys_tuples.append(('WHITE',))
                elif isinstance(fk, str):
                    fmt_keys_tuples.append((fk,))
                else:
                    fmt_keys_tuples.append(fk)
            if len(fmt_keys_tuples) < len(columns):
                fmt_keys_tuples.extend([('WHITE',)] * (len(columns) - len(fmt_keys_tuples)))


        row_parts = []
        for i, (col_data, width) in enumerate(zip(columns, widths)):
            col_fmt_tuple = fmt_keys_tuples[i] if i < len(fmt_keys_tuples) else ('WHITE',)
            color_prefix = self._get_fmt(*(col_fmt_tuple if col_fmt_tuple is not None else ('WHITE',)))
            
            col_text = str(col_data) 
            current_ansi_len = 0
            if color_prefix:
                 current_ansi_len = len(color_prefix) + len(self.fmt['END'])
            
            text_space = width - current_ansi_len
            if text_space < 0: text_space = 0


            if isinstance(col_data, (int, float)) or (isinstance(col_data, str) and col_data.replace('.', '', 1).isdigit()):
                col_str = f"{color_prefix}{col_text:>{text_space}}{self.fmt['END']}"
            else:
                col_str = f"{color_prefix}{col_text:<{text_space}}{self.fmt['END']}"
            row_parts.append(col_str)

        divider = f" {self._get_fmt('GRAY')}{self.box['V']}{self.fmt['END']} "
        row_str = divider.join(row_parts)
        self.print_line_in_box(row_str, box_v_char, base_indent_str, line_padding=1)


    def print_table_header(self, headers: List[str], widths: List[int],
                           base_indent_str: str, width: Optional[int] = None) -> None:
        box_width = width or self.config.box_width_medium
        h_bar_len = box_width - 2
        if h_bar_len < 0: h_bar_len = 0
        bold_fmt = self._get_fmt('BOLD')

        print(f"{base_indent_str}{bold_fmt}{self.box['TL']}{self.box['H'] * h_bar_len}{self.box['TR']}{self.fmt['END']}")
        self.print_table_row(headers, widths, self.box['V'], base_indent_str, [('WHITE', 'BOLD')] * len(headers))
        print(f"{base_indent_str}{bold_fmt}{self.box['VR']}{self.box['H'] * h_bar_len}{self.box['VL']}{self.fmt['END']}")


    def print_stats_box(self, title: str, stats: Dict[str, Any], 
                        base_indent_str: str = LAYOUT_CONFIG['DEFAULT_INDENT_STRING'], 
                        width: Optional[int] = None, columns: int = 1) -> None:
        box_width = width or self.config.box_width_medium
        
        style_attrs = { 
            'color_keys': ('BRIGHT_CYAN', 'BOLD'), 
            'chars': ('TL', 'TR', 'BL', 'BR', 'H', 'V')
        }
        color_prefix = self._get_fmt(*style_attrs['color_keys'])
        bc_keys = ('TL', 'TR', 'BL', 'BR', 'H', 'V')
        current_box_chars = {key: self.box[val_key] for key, val_key in zip(bc_keys, style_attrs['chars'])}

        h_bar_len = box_width - 2
        if h_bar_len < 0: h_bar_len = 0
        
        print(f"\n{base_indent_str}{color_prefix}{current_box_chars['TL']}{current_box_chars['H'] * h_bar_len}{current_box_chars['TR']}{self.fmt['END']}")

        plain_title = title
        space_for_title_and_padding = box_width - 2
        
        centering_padding_total = space_for_title_and_padding - len(plain_title)
        if centering_padding_total < 0: centering_padding_total = 0
        left_pad = centering_padding_total // 2
        right_pad = centering_padding_total - left_pad
        
        print(
            f"{base_indent_str}{color_prefix}{current_box_chars['V']}{self.fmt['END']}"
            f"{' ' * left_pad}{color_prefix}{title}{self.fmt['END']}{' ' * right_pad}"
            f"{color_prefix}{current_box_chars['V']}{self.fmt['END']}")


        print(f"{base_indent_str}{color_prefix}{self.box['VR']}{current_box_chars['H'] * h_bar_len}{self.box['VL']}{self.fmt['END']}")
        
        content_padding = LAYOUT_CONFIG['STAT_BOX_COLUMN_PADDING'] 
        content_inner_width = box_width - 2 - (content_padding * 2) 
        
        divider_str_colored = f" {self._get_fmt('GRAY')}|{self.fmt['END']}  "
        plain_divider_len = len(" |  ")
        
        col_width_estimate = content_inner_width
        if columns > 1:
             col_width_estimate = (content_inner_width - ((columns - 1) * plain_divider_len)) // columns
        if col_width_estimate <=0: col_width_estimate = 10

        stats_items = list(stats.items())
        rows = (len(stats_items) + columns - 1) // columns

        for row_idx in range(rows):
            row_str_parts_colored = []
            
            for col_idx in range(columns):
                item_idx = row_idx + col_idx * rows
                if item_idx < len(stats_items):
                    key, value = stats_items[item_idx]

                    formatted_key = f"{self._get_fmt('WHITE', 'BOLD')}{key}:{self.fmt['END']}"
                    
                    if isinstance(value, bool): formatted_value = self.format_boolean(value)
                    elif isinstance(value, int) and not isinstance(value, bool): formatted_value = self.format_count(value) 
                    elif isinstance(value, float): formatted_value = f"{self._get_fmt('WHITE')}{value:.2f}{self.fmt['END']}"
                    else: formatted_value = f"{self._get_fmt('WHITE')}{str(value)}{self.fmt['END']}"
                    
                    item_str_colored = f"{formatted_key} {formatted_value}"
                    
                    plain_key_len = len(key) + 1
                    if isinstance(value, bool): plain_value_len = 1
                    elif isinstance(value, (int, float)): plain_value_len = len(str(value).split('.')[0])
                    else: plain_value_len = len(str(value))
                    item_str_plain_len = plain_key_len + 1 + plain_value_len

                    padding_needed = col_width_estimate - item_str_plain_len
                    if padding_needed < 0: padding_needed = 0
                    
                    row_str_parts_colored.append(item_str_colored + ' ' * padding_needed)
                else:
                    row_str_parts_colored.append(' ' * col_width_estimate)
            
            full_row_str = divider_str_colored.join(row_str_parts_colored)
            self.print_line_in_box(full_row_str, current_box_chars['V'], base_indent_str, line_padding=content_padding)

        print(f"{base_indent_str}{color_prefix}{current_box_chars['BL']}{current_box_chars['H'] * h_bar_len}{current_box_chars['BR']}{self.fmt['END']}")

    def print_horizontal_line(self, width: int, indent_str: str = "", char_key: str = 'H', color_keys: Tuple[str, ...] = ('GRAY',)):
        color = self._get_fmt(*color_keys)
        line_char = self.box.get(char_key.upper(), char_key)
        actual_width = width

        print(f"{indent_str}{color}{line_char * actual_width}{self.fmt['END']}")
