import os
from typing import Any, Dict, Optional

from .report_format import ReportConfig
from .formatter import ReportFormatter
from .console_printer import ConsolePrinterMixin
from .report_generator import ReportDataGeneratorMixin
from deadspace_checker.utils.logging_utils import get_logger

logger = get_logger(__name__)


class ReportService(ConsolePrinterMixin, ReportDataGeneratorMixin):

    def __init__(self, config: Optional[ReportConfig] = None) -> None:
        self.config = config or ReportConfig()
        self.formatter = ReportFormatter(self.config)
        self.cache: Dict[Any, Any] = {}

        os.makedirs(self.config.report_output_dir, exist_ok=True)
