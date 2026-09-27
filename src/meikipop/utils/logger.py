# meikipop/utils/logger.py
import logging
import os
import sys
import threading

from meikipop.config.config import APP_NAME
from meikipop.utils.paths import paths

TRACE_LEVEL_NUM = 5
logging.addLevelName(TRACE_LEVEL_NUM, "TRACE")


def trace(self, message, *args, **kws):
    if self.isEnabledFor(TRACE_LEVEL_NUM):
        self._log(TRACE_LEVEL_NUM, message, args, **kws)


logging.Logger.trace = trace

def setup_logging():
    log_formatter = logging.Formatter(
        f"%(asctime)s - [%(levelname)-5s] - [{APP_NAME}] - %(message)s",
        datefmt='%H:%M:%S'
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(log_formatter)

    logger = logging.getLogger()
    logger.setLevel(logging.INFO)  # logging.INFO or TRACE_LEVEL_NUM

    if logger.hasHandlers():
        logger.handlers.clear()
    logger.addHandler(handler)

    # also keep the last session's log in a file, for when the console isn't at hand
    try:
        file_handler = logging.FileHandler(os.path.join(paths.data_dir, 'meikipop.log'), mode='w', encoding='utf-8')
        file_handler.setFormatter(log_formatter)
        logger.addHandler(file_handler)
    except OSError:
        pass

    # errors in background threads would otherwise only reach the console window, not the log file
    def log_thread_exception(args):
        if args.exc_type is not SystemExit:
            logger.error(f"Uncaught exception in thread {args.thread.name if args.thread else '?'}",
                         exc_info=(args.exc_type, args.exc_value, args.exc_traceback))
    threading.excepthook = log_thread_exception