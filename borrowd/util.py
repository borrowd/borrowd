from django.db.models import Model

from borrowd_groups.models import BorrowdGroup


class BorrowdTemplateFinderMixin:
    """
    Mixin to find the template for generic class-based views. Removes
    'borrowd_' prefix from our app names.

    Background:
    ---------------
    Django's generic class-based views save a lot of boilerplate code.
    One of the ways they do that is to make assumptions about certain
    configuration - all very overridable. One of those assumptions is
    that the template is found under a directory named after the app,
    and a file named after the model. This is a good convention, but
    it doesn't work for us because we prefix our app names with
    'borrowd_' to avoid collisions with other apps. This mixin removes
    the 'borrowd_' prefix from the app name when looking for the
    template. It's a very simply thing to do, but we've put it in a
    mixin so that we can use it generically across all of our apps.
    """

    model: type[Model | BorrowdGroup]
    template_name_suffix: str

    def get_template_names(self) -> list[str]:
        app_name = self.model._meta.app_label.replace("borrowd_", "")
        model_name = self.model.__name__.lower()
        return [f"{app_name}/{model_name}{self.template_name_suffix}.html"]
