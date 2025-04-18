from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render

from borrowd_items.models import Item


@login_required
def profile_view(request: HttpRequest) -> HttpResponse:
    # It's annoying that we have to ignore this. The OneToOne field
    # linking Profiles to the User model results in a reciprocal
    # `profile` field added to the User model at runtime, hence
    # not available to mypy. The usual solution is to add an explicit
    # forward declaration on the other end of the relationship, but
    # since this is the User class we're talking about, our options
    # for making that change are limited; it looks like the easiest
    # way would be to replace the default User class wholesale, which
    # in itself is not easy.
    profile = request.user.profile  # type: ignore
    user_items = Item.objects.filter(owner=request.user)
    return render(
        request, "users/profile.html", {"profile": profile, "user_items": user_items}
    )
