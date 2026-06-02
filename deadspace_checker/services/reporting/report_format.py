import os
import shutil
from typing import Optional

from .constants import (
    TERMINAL_FORMATTING, BOX_CHARS, ASCII_BOX_CHARS, DISPLAY_LIMITS,
    LAYOUT_CONFIG, ANALYSIS_CONFIG, DEFAULT_REPORT_CONFIG,
    REPORT_FILE_SETTINGS, PLAYER_STATUS, SEVERITY_LEVELS,
    CONFIDENCE_LEVELS, TIME_ANALYSIS_THRESHOLDS
)


class ReportConfig:

    def __init__(self, **kwargs):
        terminal_size = shutil.get_terminal_size((DEFAULT_REPORT_CONFIG['BOX_WIDTH_LARGE'], 40))
        terminal_width = terminal_size.columns

        self.box_width_large = min(
            kwargs.get('box_width_large', DEFAULT_REPORT_CONFIG['BOX_WIDTH_LARGE']),
            terminal_width - LAYOUT_CONFIG['PADDING_SMALL'] 
        )
        self.box_width_medium = min(
            kwargs.get('box_width_medium', DEFAULT_REPORT_CONFIG['BOX_WIDTH_MEDIUM']),
            terminal_width - LAYOUT_CONFIG['PADDING_SMALL']
        )
        self.box_width_small = min(
            kwargs.get('box_width_small', DEFAULT_REPORT_CONFIG['BOX_WIDTH_SMALL']),
            terminal_width - LAYOUT_CONFIG['PADDING_SMALL']
        )
        self.box_width_medium = min(self.box_width_medium, self.box_width_large)
        self.box_width_small = min(self.box_width_small, self.box_width_medium)


        self.truncate_list_limit = kwargs.get(
            'truncate_list_limit',
            DEFAULT_REPORT_CONFIG['TRUNCATE_LIST_LIMIT']
        )
        self.truncate_text_length = kwargs.get(
            'truncate_text_length',
            DEFAULT_REPORT_CONFIG['TRUNCATE_TEXT_LENGTH']
        )
        
        self.display_limit_small_items = kwargs.get(
            'display_limit_small', 
            DEFAULT_REPORT_CONFIG['DISPLAY_LIMIT_SMALL']
        )
        self.display_limit_medium_items = kwargs.get(
            'display_limit_medium',
            DEFAULT_REPORT_CONFIG['DISPLAY_LIMIT_MEDIUM']
        )
        self.display_limit_large_items = kwargs.get(
            'display_limit_large',
            DEFAULT_REPORT_CONFIG['DISPLAY_LIMIT_LARGE']
        )

        self.detail_level = kwargs.get('detail_level', DEFAULT_REPORT_CONFIG['DETAIL_LEVEL'])
        self.color_intensity = kwargs.get('color_intensity', DEFAULT_REPORT_CONFIG['COLOR_INTENSITY'])
        self.show_timestamps = kwargs.get('show_timestamps', DEFAULT_REPORT_CONFIG['SHOW_TIMESTAMPS'])

        self.report_filename = kwargs.get('report_filename', REPORT_FILE_SETTINGS['REPORT_FILENAME'])
        self.report_output_dir = kwargs.get('report_output_dir', REPORT_FILE_SETTINGS['REPORT_OUTPUT_DIR'])
        
        self.count_threshold_medium = kwargs.get('count_threshold_medium', DEFAULT_REPORT_CONFIG['COUNT_THRESHOLD_MEDIUM'])
        self.count_threshold_high = kwargs.get('count_threshold_high', DEFAULT_REPORT_CONFIG['COUNT_THRESHOLD_HIGH'])


        os.makedirs(self.report_output_dir, exist_ok=True)

    def get_dynamic_limit(self, category: Optional[str] = None) -> int:

        if category and category.upper() in DISPLAY_LIMITS:
            base_limit = DISPLAY_LIMITS[category.upper()]
            if self.detail_level == 0:
                return max(1, round(base_limit * 0.5))
            elif self.detail_level == 1:
                return base_limit
            else:
                return round(base_limit * 1.5) if base_limit > 2 else base_limit + 1
        
        if self.detail_level == 0:
            return self.display_limit_small_items
        elif self.detail_level == 1:
            return self.display_limit_medium_items
        else:
            return self.display_limit_large_items

    def get_specific_display_limit(self, name: str) -> int:
        upper_name = name.upper()
        if upper_name not in DISPLAY_LIMITS:
            return self.get_dynamic_limit('MEDIUM') 
            
        base_limit = DISPLAY_LIMITS[upper_name]
        
        if self.detail_level == 0:
            if base_limit <= 3: return max(1, base_limit -1)
            return max(1, round(base_limit * 0.5))
        elif self.detail_level == 1:
            return base_limit
        else:
            if base_limit <=3 : return base_limit + 1
            return round(base_limit * 1.5)


def load_config_from_file(config_file: Optional[str] = None) -> dict:
    import json

    config = DEFAULT_REPORT_CONFIG.copy()

    if config_file and os.path.exists(config_file):
        try:
            with open(config_file, 'r') as f:
                user_config = json.load(f)
                config.update(user_config)
        except Exception as e:
            print(f"{TERMINAL_FORMATTING.get('RED', '')}Error loading config file '{config_file}': {e}{TERMINAL_FORMATTING.get('END', '')}")
    return config
