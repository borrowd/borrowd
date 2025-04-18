from django.contrib import admin

from .models import Item, ItemCategory

admin.site.register([Item, ItemCategory])
