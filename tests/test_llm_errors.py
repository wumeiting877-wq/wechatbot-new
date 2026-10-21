# -*- coding: utf-8 -*-
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from llm_errors import (
    AUTH_ERROR,
    INSUFFICIENT_BALANCE,
    RATE_LIMIT,
    TIMEOUT,
    classify_api_error,
)


class FakeHttpError(Exception):
    def __init__(self, message, status_code):
        super().__init__(message)
        self.status_code = status_code


class LlmErrorTests(unittest.TestCase):
    def test_auth_error(self):
        err = classify_api_error(FakeHttpError("Api key is invalid", 401))
        self.assertEqual(err.code, AUTH_ERROR)
        self.assertIn("API Key", err.user_message)

    def test_rate_limit(self):
        err = classify_api_error(FakeHttpError("rate limit exceeded", 429))
        self.assertEqual(err.code, RATE_LIMIT)

    def test_timeout(self):
        err = classify_api_error(TimeoutError("timed out"))
        self.assertEqual(err.code, TIMEOUT)

    def test_balance(self):
        err = classify_api_error(FakeHttpError("user quota is not enough", 402))
        self.assertEqual(err.code, INSUFFICIENT_BALANCE)

    def test_does_not_call_everything_balance(self):
        err = classify_api_error(FakeHttpError("connection reset by peer", 500))
        self.assertNotEqual(err.code, INSUFFICIENT_BALANCE)


if __name__ == "__main__":
    unittest.main()
