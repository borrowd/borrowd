from collections.abc import Sequence
from smtplib import (
    SMTPConnectError,
    SMTPException,
    SMTPResponseException,
    SMTPServerDisconnected,
)

from django.core.mail.backends.smtp import EmailBackend
from django.core.mail.message import EmailMessage
from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)


def _is_transient_smtp_error(exception: BaseException) -> bool:
    # smtplib.SMTPException subclasses OSError, so a bare OSError check would also
    # match permanent failures like SMTPRecipientsRefused/SMTPAuthenticationError.
    # Those are handled by the SMTPResponseException branch (or fall through to
    # "not transient"); this branch is only for genuine network-level errors.
    if isinstance(exception, OSError) and not isinstance(exception, SMTPException):
        return True
    if isinstance(exception, (SMTPServerDisconnected, SMTPConnectError)):
        return True
    if isinstance(exception, SMTPResponseException):
        return 400 <= exception.smtp_code < 500
    return False


class RetryingSMTPEmailBackend(EmailBackend):
    # Retries the whole `email_messages` batch, so this is only safe because every
    # current send_mail() call sends a single message to a single recipient — a
    # retried multi-message batch could double-send ones that already succeeded.
    def send_messages(self, email_messages: Sequence[EmailMessage]) -> int:
        @retry(
            retry=retry_if_exception(_is_transient_smtp_error),
            stop=stop_after_attempt(3),
            wait=wait_exponential(multiplier=0.5, max=2),
            reraise=True,
        )
        def _send() -> int:
            return super(RetryingSMTPEmailBackend, self).send_messages(email_messages)

        return _send()
