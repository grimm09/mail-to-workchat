from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from tests.support import PROJECT_ROOT  # noqa: F401
from mail_to_workchat.notifiers.http import WebhookTransportError, _NoRedirect, post_json


class HTTPTransportTests(unittest.TestCase):
    def response(self, body):
        opener = MagicMock()
        response = opener.open.return_value.__enter__.return_value
        response.status = 200
        response.read.return_value = body
        return opener

    def test_invalid_json_and_non_object_are_errors(self):
        for body in (b"<html>failure</html>", b"[]", b"null", b"x" * 32769):
            with self.subTest(body=body[:16]), patch("urllib.request.build_opener", return_value=self.response(body)), self.assertRaises(WebhookTransportError):
                post_json("https://example.com/hook", {}, 10)

    def test_empty_generic_response_remains_supported(self):
        with patch("urllib.request.build_opener", return_value=self.response(b"")) as build:
            self.assertEqual(post_json("https://example.com/hook", {}, 10), {})
        self.assertEqual(build.return_value.open.call_args.kwargs["timeout"], 10)

    def test_redirect_handler_never_follows(self):
        self.assertIsNone(_NoRedirect().redirect_request(None, None, 302, "", {}, "https://attacker.invalid"))
