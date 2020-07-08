__version__ = "0.0.2"

import re
import sys
import time
import logging
import signal
import json
import importlib
import ratelimit

STANDARD_LEVELS = ["CRITICAL", "DEBUG", "ERROR", "FATAL", "INFO", "NOTSET", "WARN", "WARNING"]

LEVELNO_TO_STR = {
    logging.CRITICAL: "CRITICAL",
    logging.DEBUG: "DEBUG",
    logging.ERROR: "ERROR",
    logging.FATAL: "FATAL",
    logging.INFO: "INFO",
    logging.WARNING: "WARNING",
}


def parse_level(level):
    global STANDARD_LEVELS
    if level in STANDARD_LEVELS:
        return getattr(logging, level)

    if not isinstance(level, int):
        raise RuntimeError("Invalid loglevel {}".format(level))
    return level


def parse_signal(sig):
    if isinstance(sig, int):
        return sig

    sig = sig.upper()
    if not sig.startswith("SIG"):
        sig = "SIG" + sig

    return getattr(signal, sig)


if sys.version_info.major < 3:
    def import_class(class_name):
        import __builtin__
        if "." not in class_name:
            return getattr(__builtin__, class_name)  # noqa

        parts = class_name.split(".")
        module = ".".join(parts[:-1])
        module = importlib.import_module(module)
        return getattr(module, parts[-1])
else:
    def import_class(class_name):
        import builtins
        if "." not in class_name:
            return getattr(builtins, class_name)

        parts = class_name.split(".")
        module = ".".join(parts[:-1])
        module = importlib.__import__(module)
        return getattr(module, parts[-1])


class SkipException(logging.Filter):
    def __init__(self, exceptions):
        if type(exceptions) == tuple or type(exceptions) == list:
            self.exceptions = exceptions

        if "," in exceptions:
            self.exceptions = exceptions.split(",")
        else:
            self.exceptions = [exceptions]
        return super(SkipException, self).__init__()

    @property
    def exception_classes(self):
        if not hasattr(self, "_exception_classes"):
            self._exception_classes = [import_class(cn) for cn in self.exceptions]
        return self._exception_classes

    def filter(self, record):
        if record.exc_info:
            for exc_class in self.exception_classes:
                if issubclass(record.exc_info[0], exc_class):
                    return False
        return True


class SkipExceptionMsg(SkipException):
    def __init__(self, exceptions, skip_exc_messages, regex=False):
        super(SkipExceptionMsg, self).__init__(exceptions)
        self.regex = regex
        if regex:
            self.skip_exc_messages = [re.compile(msg) for msg in skip_exc_messages]
        else:
            self.skip_exc_messages = skip_exc_messages

    def filter(self, record):
        ret = super(SkipExceptionMsg, self).filter(record)
        if not self.skip_exc_messages:
            return ret
        if not ret:
            exc_message = str(record.exc_info[1])
            for msg in self.skip_exc_messages:
                if self.regex:
                    if msg.match(exc_message):
                        return False
                else:
                    if msg in exc_message:
                        return False
        return True


class SkipExceptionMsgRateLimit(SkipExceptionMsg):
    def __init__(self, exceptions, skip_exc_messages, regex=False, calls=1, period=60):
        super(SkipExceptionMsgRateLimit, self).__init__(exceptions, skip_exc_messages, regex)

        @ratelimit.limits(calls=calls, period=period)
        def _true():
            return True

        self._true = _true

    def filter(self, record):
        ret = super(SkipExceptionMsgRateLimit, self).filter(record)
        if ret:
            return True
        # If ret=False let pass only rate-limited
        try:
            return self._true()
        except ratelimit.exception.RateLimitException:
            return False


class RateLimiterFilter(logging.Filter):
    def __init__(self, calls=10, period=600):
        @ratelimit.limits(calls=calls, period=period)
        def _true():
            return True

        self._true = _true

    def filter(self, record):
        try:
            return self._true()
        except ratelimit.exception.RateLimitException:
            return False


class OnlyExcFilter(logging.Filter):
    def filter(self, record):
        if record.exc_info:
            return True
        return False


class LevelRangeFilter(logging.Filter):
    def __init__(self, min_level, max_level):
        self.min_level = parse_level(min_level)
        self.max_level = parse_level(max_level)

    def filter(self, record):
        if record.levelno < self.min_level:
            return False
        if record.levelno > self.max_level:
            return False
        return True


class CounterHandler(logging.Handler):
    def __init__(self):
        super(CounterHandler, self).__init__()
        self.counts = {}
        self.last_record = {}

    def emit(self, record):
        level_str = LEVELNO_TO_STR.get(record.levelno, None)
        if level_str is None:
            level_str = "LEVEL%d" % record.levelno
        if level_str == "ERROR" and record.exc_info:
            level_str = "EXCEPTION"
        self.counts[level_str] = 1 + self.counts.get(level_str, 0)
        self.last_record[level_str] = time.time()

    def dump_json(self):
        return json.dumps({"count": self.counts, "last_record": self.last_record})

    def dump_text(self):
        keys = sorted(self.counts.keys())
        ret = ""
        for k in keys:
            ret += "%s %d %.3f\n" % (k, self.counts.get(k, 0), self.last_record.get(k, 0))
        return ret


class DumpOnSignalCounterHandler(CounterHandler):
    def __init__(self, filename, sig="SIGUSR2", format="json"):
        super(DumpOnSignalCounterHandler, self).__init__()
        self.filename = filename
        self.sig = parse_signal(sig)
        self.format = format

        signal.signal(self.sig, self.handle_signal)

    def handle_signal(self, sig, stack):
        f = open(self.filename, "wt")
        dump = getattr(self, "dump_%s" % self.format)()
        f.write(dump)
        f.close()


class StoreRecordsHandler(logging.Handler):
    def __init__(self, *args, **kargs):
        super(StoreRecordsHandler, self).__init__(*args, **kargs)
        self.records = []

    def emit(self, record):
        self.records.append(record)
