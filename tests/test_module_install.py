# -*- coding: utf-8 -*-
import os
import sys
import types
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from module_install import install_exports, rebind


def _read_host_flag():
    return HOST_FLAG


class ModuleInstallTests(unittest.TestCase):
    def test_rebind_reads_host_namespace(self):
        host = types.ModuleType("host")
        host.HOST_FLAG = "from-host"
        rebound = rebind(_read_host_flag, host.__dict__)
        self.assertEqual(rebound(), "from-host")
        self.assertEqual(_read_host_flag.__module__, "test_module_install")

    def test_install_exports_copies_names(self):
        source = {"_read_host_flag": _read_host_flag}
        host = types.ModuleType("host")
        host.HOST_FLAG = 7
        install_exports(source, ("_read_host_flag",), host)
        self.assertEqual(host._read_host_flag(), 7)
        self.assertIs(host._read_host_flag.__globals__, host.__dict__)


if __name__ == "__main__":
    unittest.main()
