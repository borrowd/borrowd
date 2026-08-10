from typing import Any

from django.http import Http404, HttpRequest, HttpResponse
from django.test import RequestFactory, SimpleTestCase, override_settings

from borrowd_messaging.mixins import MessagingEnabledMixin


class MessagingView(MessagingEnabledMixin):
    def get(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        return HttpResponse("ok")


class MessagingEnabledMixinTests(SimpleTestCase):
    def request(self) -> HttpResponse:
        response = MessagingView.as_view()(RequestFactory().get("/"))
        assert isinstance(response, HttpResponse)
        return response

    @override_settings(MESSAGING_ENABLED=True)
    def test_serves_the_view_while_the_feature_flag_is_on(self) -> None:
        self.assertEqual(self.request().status_code, 200)

    @override_settings(MESSAGING_ENABLED=False)
    def test_hides_the_view_while_the_feature_flag_is_off(self) -> None:
        with self.assertRaises(Http404):
            self.request()
