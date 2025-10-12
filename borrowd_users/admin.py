from django.contrib import admin

from .models import BorrowdUser, Profile

admin.site.register(Profile)
admin.site.register(BorrowdUser)
