"""
URL configuration for borrowd project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""

from typing import List

from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import URLPattern, URLResolver, include, path

from borrowd_web.views import favicon

urlpatterns: List[URLPattern | URLResolver] = [
    path("admin/", admin.site.urls),
    path("accounts/", include("allauth.urls")),
    path("beta/", include("borrowd_beta.urls")),
    path("profile/", include("borrowd_users.urls")),
    path("items/", include("borrowd_items.urls")),
    path("groups/", include("borrowd_groups.urls")),
    path("favicon.ico", favicon, name="favicon"),
    path("", include("borrowd_web.urls")),
]

if not settings.BORROWD_USE_LOCAL_BUNDLING:
    urlpatterns += [
        path("__reload__/", include("django_browser_reload.urls")),
    ]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
