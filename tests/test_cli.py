import os
import time
import unittest
import logging
import tempfile
import logging_plugins
import logging_plugins.cli as cli


class TestCheckLogDump(unittest.TestCase):
    level = logging.DEBUG

    def setUp(self):
        self.logger = logging.getLogger()
        self.logger.setLevel(self.level)
        self.handler = self._make_handler()
        self.logger.handlers = []
        self.logger.addHandler(self.handler)

    def _make_handler(self):
        self.filename = tempfile.mktemp()
        return logging_plugins.DumpOnSignalCounterHandler(
            filename=self.filename, format="json"
        )

    def test_without_rules(self):
        ret = cli.check_log_dump(os.getpid(), self.filename)
        assert ret == 0

    def test_unmodified_file(self):
        ret = cli.check_log_dump(os.getpid(), self.filename + "foobar")
        assert ret == 2

    def test_rule_count(self):
        ret = cli.check_log_dump(os.getpid(), self.filename, "SIGUSR2", "info count gt 2")
        assert ret == 3
        self.logger.info("Foo")
        self.logger.info("Bar")
        self.logger.info("Three")
        ret = cli.check_log_dump(os.getpid(), self.filename, "SIGUSR2", "info count gt 2", "any count lt 1")
        assert ret == 4

    def test_rule_last_record(self):
        self.logger.info("Foo")
        ret = cli.check_log_dump(os.getpid(), self.filename, "SIGUSR2", "info last_record gt -2")
        assert ret == 0
        time.sleep(1)
        ret = cli.check_log_dump(os.getpid(), self.filename, "SIGUSR2", "any last_record gt -1.5")
        assert ret == 3
