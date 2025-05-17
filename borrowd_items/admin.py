from django.contrib import admin

from .models import Item, ItemCategory, ItemPhoto

admin.site.register([Item, ItemCategory, ItemPhoto])
