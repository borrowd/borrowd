from smtplib import (
    SMTPAuthenticationError,
    SMTPConnectError,
    SMTPRecipientsRefused,
    SMTPResponseException,
    SMTPServerDisconnected,
)
from unittest.mock import patch

from django.core.mail.backends.smtp import EmailBackend
from django.core.mail.message import EmailMessage
from django.test import SimpleTestCase

from borrowd.mail import RetryingSMTPEmailBackend


def _make_message() -> EmailMessage:
    return EmailMessage(
        subject="subject",
        body="body",
        from_email="from@example.com",
        to=["to@example.com"],
    )


class RetryingSMTPEmailBackendTests(SimpleTestCase):
    def setUp(self) -> None:
        # Real sleeps would make these tests slow for no reason -- retry
        # timing itself isn't under test here, only retry/no-retry behavior.
        patcher = patch("tenacity.nap.time.sleep")
        self.addCleanup(patcher.stop)
        patcher.start()

    def test_retries_transient_failure_then_succeeds(self) -> None:
        backend = RetryingSMTPEmailBackend()
        with patch.object(
            EmailBackend,
            "send_messages",
            side_effect=[SMTPServerDisconnected("connection lost"), 1],
        ) as mock_send:
            result = backend.send_messages([_make_message()])

        self.assertEqual(result, 1)
        self.assertEqual(mock_send.call_count, 2)

    def test_retries_up_to_two_attempts_then_reraises(self) -> None:
        # Capped at 2 attempts (not 3) so the worst case stays under gunicorn's
        # default 30s worker timeout -- see RetryingSMTPEmailBackend's comment.
        backend = RetryingSMTPEmailBackend()
        with (
            patch.object(
                EmailBackend,
                "send_messages",
                side_effect=SMTPServerDisconnected("connection lost"),
            ) as mock_send,
            self.assertRaises(SMTPServerDisconnected),
        ):
            backend.send_messages([_make_message()])

        self.assertEqual(mock_send.call_count, 2)

    def test_retries_bare_network_error_then_succeeds(self) -> None:
        backend = RetryingSMTPEmailBackend()
        with patch.object(
            EmailBackend,
            "send_messages",
            side_effect=[TimeoutError("timed out"), 1],
        ) as mock_send:
            result = backend.send_messages([_make_message()])

        self.assertEqual(result, 1)
        self.assertEqual(mock_send.call_count, 2)

    def test_retries_smtp_connect_error_regardless_of_code(self) -> None:
        # SMTPConnectError is a SMTPResponseException subclass but is retried
        # unconditionally, unlike the generic 4xx/5xx code check -- a 5xx code
        # here still needs to retry, distinguishing it from that branch.
        backend = RetryingSMTPEmailBackend()
        with patch.object(
            EmailBackend,
            "send_messages",
            side_effect=[SMTPConnectError(554, b"connection refused"), 1],
        ) as mock_send:
            result = backend.send_messages([_make_message()])

        self.assertEqual(result, 1)
        self.assertEqual(mock_send.call_count, 2)

    def test_retries_on_4xx_smtp_response(self) -> None:
        backend = RetryingSMTPEmailBackend()
        with patch.object(
            EmailBackend,
            "send_messages",
            side_effect=[SMTPResponseException(421, b"service not available"), 1],
        ) as mock_send:
            result = backend.send_messages([_make_message()])

        self.assertEqual(result, 1)
        self.assertEqual(mock_send.call_count, 2)

    def test_retries_on_temporary_recipients_refused(self) -> None:
        backend = RetryingSMTPEmailBackend()
        with patch.object(
            EmailBackend,
            "send_messages",
            side_effect=[
                SMTPRecipientsRefused({"to@example.com": (450, b"mailbox full")}),
                1,
            ],
        ) as mock_send:
            result = backend.send_messages([_make_message()])

        self.assertEqual(result, 1)
        self.assertEqual(mock_send.call_count, 2)

    def test_permanent_recipients_refused_is_not_retried(self) -> None:
        backend = RetryingSMTPEmailBackend()
        with (
            patch.object(
                EmailBackend,
                "send_messages",
                side_effect=SMTPRecipientsRefused(
                    {"to@example.com": (550, b"no such user")}
                ),
            ) as mock_send,
            self.assertRaises(SMTPRecipientsRefused),
        ):
            backend.send_messages([_make_message()])

        self.assertEqual(mock_send.call_count, 1)

    def test_permanent_authentication_error_is_not_retried(self) -> None:
        backend = RetryingSMTPEmailBackend()
        with (
            patch.object(
                EmailBackend,
                "send_messages",
                side_effect=SMTPAuthenticationError(535, b"authentication failed"),
            ) as mock_send,
            self.assertRaises(SMTPAuthenticationError),
        ):
            backend.send_messages([_make_message()])

        self.assertEqual(mock_send.call_count, 1)

    def test_5xx_smtp_response_is_not_retried(self) -> None:
        backend = RetryingSMTPEmailBackend()
        with (
            patch.object(
                EmailBackend,
                "send_messages",
                side_effect=SMTPResponseException(550, b"mailbox unavailable"),
            ) as mock_send,
            self.assertRaises(SMTPResponseException),
        ):
            backend.send_messages([_make_message()])

        self.assertEqual(mock_send.call_count, 1)
