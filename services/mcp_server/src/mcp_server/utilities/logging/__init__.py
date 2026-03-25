from logging import (
    getLogger,
    DEBUG,
    INFO,
    WARNING,
    ERROR,
    CRITICAL,
    Formatter,
    StreamHandler,
)
import sys
from enum import Enum
from typing import Optional
import time


class Colour(Enum):
    """ANSI color escape sequences used for logs and terminal tables."""

    grey = "\x1b[38;20m"
    green = "\x1b[32m"
    bold_green = "\x1b[1;32m"
    yellow = "\x1b[33;20m"
    bold_yellow = "\x1b[33;1m"
    red = "\x1b[31;20m"
    bold_red = "\x1b[31;1m"
    purple = "\x1b[35;20m"
    bold_purple = "\x1b[35;1m"
    reset = "\x1b[0m"
    cyan = "\x1b[36;1m"
    bold_cyan = "\x1b[2;36;1m"
    bold_white = "\x1b[2;37;1m"
    dim_grey = "\x1b[2;37m"


class LogFormatter(Formatter):
    """Apply level-aware ANSI color formatting to standard log records."""

    grey = Colour.grey
    green = Colour.green
    bold_green = Colour.bold_green
    yellow = Colour.yellow
    bold_yellow = Colour.bold_yellow
    red = Colour.red
    bold_red = Colour.bold_red
    purple = Colour.purple
    bold_purple = Colour.bold_purple
    reset = Colour.reset

    identifier = "%(levelname)s:%(name)s:"
    message = "%(message)s"

    FORMATS = {
        DEBUG: grey,
        INFO: bold_green,
        WARNING: bold_yellow,
        ERROR: bold_red,
        CRITICAL: bold_purple,
    }

    def format(self, record):
        """Format a log record using the configured color for its level."""
        id = self.FORMATS.get(record.levelno)
        formatter = Formatter(
            f"{id.value if id is not None else Colour.bold_white.value}{self.identifier}{self.reset.value}{self.message}"
        )
        return formatter.format(record)


def timed(f):
    """Wrap an async method and emit a debug log with its execution time."""

    async def timing(*args, **kw):
        """Execute the wrapped coroutine while measuring elapsed time."""
        ts = time.time()
        result = await f(*args, **kw)
        te = time.time()
        args[0].log.debug("%r completed in: %2.4f sec" % (f.__name__, te - ts))
        return result

    return timing


def get_logger(name: str):
    """Return a configured logger with the shared color formatter attached."""
    log = getLogger(name)
    log.setLevel(DEBUG)
    if not log.handlers:
        stream_handler = StreamHandler()
        stream_handler.setLevel(DEBUG)
        stream_handler.setFormatter(LogFormatter())
        log.addHandler(stream_handler)
    return log


def pp(text: str, colour: Colour = Colour.reset, end: Optional[str] = None):
    """Write colored text directly to stdout."""
    sys.stdout.write(colour.value)
    sys.stdout.write(text)
    sys.stdout.write(Colour.reset.value)
    if end:
        sys.stdout.write(end)
    sys.stdout.flush()
