import logging
import queue


class QueueLogHandler(logging.Handler):
    def __init__(self, out_queue, formatter):
        super().__init__()
        self.out_queue = out_queue
        self.setFormatter(formatter)

    def emit(self, record):
        try:
            self.out_queue.put({"type": "log", "text": self.format(record) + "\n"})
        except Exception:
            pass
