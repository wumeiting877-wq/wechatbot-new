# -*- coding: utf-8 -*-
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from url_safety import host_is_blocked_for_fetch, url_is_blocked_for_fetch


def _fake_resolver(hostname, _port):
    mapping = {
        "example.com": [("AF", "SOCK", 0, "", ("93.184.216.34", 0))],
        "evil.internal": [("AF", "SOCK", 0, "", ("10.0.0.8", 0))],
    }
    if hostname not in mapping:
        import socket
        raise socket.gaierror("unknown")
    return mapping[hostname]


class SsrfTests(unittest.TestCase):
    def test_block_localhost(self):
        self.assertTrue(url_is_blocked_for_fetch("http://127.0.0.1/secret"))
        self.assertTrue(url_is_blocked_for_fetch("http://localhost/admin"))

    def test_block_private_ip(self):
        self.assertTrue(url_is_blocked_for_fetch("http://192.168.1.1/"))
        self.assertTrue(url_is_blocked_for_fetch("http://10.0.0.2/"))

    def test_allow_public_url(self):
        self.assertFalse(url_is_blocked_for_fetch("https://example.com/page", resolver=_fake_resolver))

    def test_block_internal_hostname(self):
        self.assertTrue(host_is_blocked_for_fetch("metadata.google.internal"))
        self.assertTrue(url_is_blocked_for_fetch("http://evil.internal/x", resolver=_fake_resolver))

    def test_block_non_http(self):
        self.assertTrue(url_is_blocked_for_fetch("file:///etc/passwd"))


if __name__ == "__main__":
    unittest.main()
