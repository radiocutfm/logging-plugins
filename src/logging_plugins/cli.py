from __future__ import print_function
import time
import os
import json
import sys
import logging_plugins


def _get_m_time(filename):
    try:
        st = os.stat(filename)
        return st.st_mtime
    except OSError:
        return 0


def parse_rule(rule):
    rule_parts = rule.split(" ")
    log_type = rule_parts[0].upper()
    var_type = rule_parts[1].lower()
    if var_type not in ("count", "last_record"):
        raise RuntimeError(
            "Invalid rule '{}' unknown variable {}, allowed 'count', 'last_record'".format(rule, var_type)
        )
    comp = rule_parts[2].lower()
    if comp not in ("lt", "gt"):
        raise RuntimeError(
            "Invalid rule '{}' invalid comparison {}, allowed 'gt', 'lt'".format(rule, var_type)
        )

    value = float(rule_parts[3])
    return log_type, var_type, comp, value


def check_log_dump(pid, filename, sig="SIGUSR2", *args):
    pid = int(pid)
    m_time = _get_m_time(filename)
    os.kill(pid, logging_plugins.parse_signal(sig))

    for i in range(10):
        time.sleep(0.5)
        new_m_time = _get_m_time(filename)
        if new_m_time > m_time:
            break

    if new_m_time <= m_time:
        print("Error {} not updated after 5 seconds, process not responding".format(filename),
              file=sys.stderr)
        return 2

    count_dump = open(filename, "rt").read()

    if "{" in count_dump:
        count_dump = json.loads(count_dump)
    else:
        lines = count_dump.splitlines()
        count_dump = {"count": {}, "last_record": {}}
        for row in [line.rstrip("\n").split(" ") for line in lines]:
            count_dump["count"][row[0]] = int(row[1])
            count_dump["last_record"][row[0]] = float(row[2])

    for i, rule in enumerate(args):
        log_type, var_type, comp, value = parse_rule(rule)

        if var_type == "last_record":
            value += time.time()

        if log_type == "ANY":
            dump_value = count_dump[var_type].values()
            dump_value = sum(dump_value) if var_type == "count" else max(dump_value)
        else:
            dump_value = count_dump[var_type].get(log_type, 0)
        ok = dump_value < value if comp == "lt" else dump_value > value
        if not ok:
            print("Error in rule '{}' {} {} = {}".format(rule, log_type, var_type, dump_value),
                  file=sys.stderr)
            return 3 + i

    return 0


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage {} check-log-dump".format(sys.argv[0]), file=sys.stderr)
        sys.exit(1)

    if sys.argv[1] == "check-log-dump":
        ret = check_log_dump(*sys.argv[2:])
    else:
        print("Unknown command {}".format(sys.argv[1]), file=sys.stderr)
        sys.exit(1)
    sys.exit(ret)
