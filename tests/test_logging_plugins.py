# -*- coding: utf-8 -*-
import os
import time
import tempfile
import logging
import unittest
import logging_plugins
import json
import signal


class TestFilters(unittest.TestCase):
    def setUp(self):
        self.logger = logging.getLogger("TestExceptionFilters")
        self.logger.filters = []
        self.store_handler = logging_plugins.StoreRecordsHandler()
        self.logger.handlers = []
        self.logger.addHandler(self.store_handler)

    def test_parse_level(self):
        assert logging_plugins.parse_level("ERROR") == 40
        assert True

    def test_skip_exception_filter(self):
        self.logger.addFilter(logging_plugins.SkipException("ZeroDivisionError"))

        assert self.store_handler.records == []

        try:
            1 / 0
        except Exception:
            self.logger.exception("Should be skipped")

        assert self.store_handler.records == []

        try:
            1 + "a"
        except Exception:
            self.logger.exception("Should NOT be skipped")

        assert len(self.store_handler.records) == 1

    def test_skip_exception_msg_filter(self):
        self.logger.addFilter(logging_plugins.SkipExceptionMsg("RuntimeError,ValueError", ["foobar"]))

        assert self.store_handler.records == []

        try:
            raise ValueError("Hello foobar")
        except Exception:
            self.logger.exception("Should be skipped")

        assert len(self.store_handler.records) == 0

        try:
            raise RuntimeError("Hello")
        except Exception:
            self.logger.exception("Should NOT be skipped")

        assert len(self.store_handler.records) == 1

        try:
            1 / 0
        except Exception:
            self.logger.exception("Should NOT be skipped")

        assert len(self.store_handler.records) == 2

        try:
            raise RuntimeError("foobar is great")
        except Exception:
            self.logger.exception("Should be skipped")

        assert len(self.store_handler.records) == 2

    def test_skip_exception_msg_rate_limit(self):
        self.logger.addFilter(logging_plugins.SkipExceptionMsgRateLimit(
            "RuntimeError,ValueError", [".*foobar [0-9] .*"], regex=True,
            calls=2, period=2,
        ))

        for x in range(11):
            try:
                raise RuntimeError("foobar %d error" % x)
            except Exception:
                self.logger.exception("Should NOT be skipped" if x in (0, 1, 10) else "Should be skipped")

        assert len(self.store_handler.records) == 3

        time.sleep(2)

        for x in range(5):
            try:
                raise RuntimeError("foobar %d error" % x)
            except Exception:
                self.logger.exception("Should NOT be skipped" if x in (0, 1) else "Should be skipped")

        assert len(self.store_handler.records) == 5
        assert ["Should NOT be skipped"] * 5 == [r.message for r in self.store_handler.records]

    def test_rate_limiter_filter(self):
        self.logger.addFilter(logging_plugins.RateLimiterFilter(
            calls=3, period=2,
        ))

        for x in range(11):
            self.logger.error("Should NOT be skipped" if x in (0, 1, 2) else "Should be skipped")
        assert len(self.store_handler.records) == 3

        time.sleep(2)

        for x in range(5):
            self.logger.warning("Should NOT be skipped" if x in (0, 1, 2) else "Should be skipped")

        assert len(self.store_handler.records) == 6
        assert ["Should NOT be skipped"] * 6 == [r.message for r in self.store_handler.records]


class TestCounterHandler(unittest.TestCase):
    level = logging.DEBUG

    def _make_handler(self):
        return logging_plugins.CounterHandler()

    def setUp(self):
        self.logger = logging.getLogger()
        self.logger.setLevel(self.level)
        self.handler = self._make_handler()
        self.logger.handlers = []
        self.logger.addHandler(self.handler)

    def test_counts(self):
        t0 = time.time()

        self.logger.debug("Debug message")
        self.logger.info("Some info message")
        self.logger.info("Some info message")
        self.logger.error("Error message 1")
        self.logger.error("Error message 2")
        self.logger.error("Error message 3")
        try:
            raise ValueError("Foobar")
        except Exception:
            self.logger.exception("Exception message")

        expected = {"DEBUG": 1, "INFO": 2, "ERROR": 3, "EXCEPTION": 1}
        assert self.handler.counts == expected

        for v in expected.keys():
            self.assertAlmostEqual(t0, self.handler.last_record[v], 0)

        assert json.loads(self.handler.dump_json())["counts"] == expected
        test_dump = self.handler.dump_text().splitlines()

        assert len(test_dump) == 4
        test_dump = [line.split(" ") for line in test_dump]
        assert ["DEBUG", "ERROR", "EXCEPTION", "INFO"] == [row[0] for row in test_dump]
        assert ["1", "3", "1", "2"] == [row[1] for row in test_dump]
        for row in test_dump:
            t = float(row[2].rstrip("\n"))
            self.assertAlmostEqual(t, t0, 0)


class TestDumpOnSignalCounterHandler(TestCounterHandler):
    def _make_handler(self):
        self.filename = tempfile.mktemp()
        return logging_plugins.DumpOnSignalCounterHandler(
            filename=self.filename, sig=signal.SIGALRM, format="text"
        )

    def test_counts(self):
        super(TestDumpOnSignalCounterHandler, self).test_counts()
        assert not os.path.exists(self.filename)
        signal.alarm(1)
        time.sleep(3)
        assert os.path.exists(self.filename)
        text = open(self.filename, "rt").read()
        assert text == self.handler.dump_text()
