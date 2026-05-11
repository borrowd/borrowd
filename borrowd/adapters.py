from typing import Any

from allauth.account.adapter import DefaultAccountAdapter, HttpRequest
from ipware import get_client_ip


class IPWareAccountAdapter(DefaultAccountAdapter):  # type: ignore[misc]
    def get_client_ip(self, request: HttpRequest) -> Any:
        # ipware will automatically check common headers like X-Forwarded-For
        client_ip, is_routable = get_client_ip(request)

        # If ipware can't find it, we return None (which allauth expects)
        # or you can return a fallback/dummy if you're in a local environment.
        return client_ip
