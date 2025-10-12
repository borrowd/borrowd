from typing import Any

from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError

from .models import BorrowdUser

User = get_user_model()


class CustomSignupForm(UserCreationForm[BorrowdUser]):
    """
    Custom signup form that includes first and last name fields
    and uses Django's password validation.
    """

    email = forms.EmailField(
        required=True,
        widget=forms.EmailInput(
            attrs={
                "class": "w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-borrowd-indigo-500 focus:border-borrowd-indigo-500",
                "placeholder": "Email address",
            }
        ),
    )

    first_name = forms.CharField(
        max_length=150,
        required=True,
        widget=forms.TextInput(
            attrs={
                "class": "w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-borrowd-indigo-500 focus:border-borrowd-indigo-500",
                "placeholder": "First name",
            }
        ),
    )

    last_name = forms.CharField(
        max_length=150,
        required=True,
        widget=forms.TextInput(
            attrs={
                "class": "w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-borrowd-indigo-500 focus:border-borrowd-indigo-500",
                "placeholder": "Last name",
            }
        ),
    )

    password1 = forms.CharField(
        widget=forms.PasswordInput(
            attrs={
                "class": "w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-borrowd-indigo-500 focus:border-borrowd-indigo-500",
                "placeholder": "Password",
            }
        ),
        help_text="Your password can't be too similar to your other personal information, must contain at least 8 characters, can't be a commonly used password, and can't be entirely numeric.",
    )

    password2 = forms.CharField(
        widget=forms.PasswordInput(
            attrs={
                "class": "w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-borrowd-indigo-500 focus:border-borrowd-indigo-500",
                "placeholder": "Confirm password",
            }
        ),
        help_text="Enter the same password as before, for verification.",
    )

    class Meta:
        model = User
        fields = ("email", "first_name", "last_name", "password1", "password2")

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        # Remove username field since we're using email for login
        if "username" in self.fields:
            del self.fields["username"]

    def clean_email(self) -> str | None:
        email: str | None = self.cleaned_data.get("email")
        if not email:
            raise forms.ValidationError("Email is required.")
        if User.objects.filter(email=email).exists():
            raise forms.ValidationError("A user with this email already exists.")
        return email

    def clean_password1(self) -> str | None:
        password1: str | None = self.cleaned_data.get("password1")
        if not password1:
            raise forms.ValidationError("Password is required.")
        # Use Django's built-in password validation
        try:
            validate_password(password1, self.instance)
        except ValidationError as error:
            raise forms.ValidationError(error)
        return password1

    def save(self, commit: bool = True) -> BorrowdUser:
        user = super().save(commit=False)
        user.email = self.cleaned_data["email"]
        user.username = self.cleaned_data["email"]  # Use email as username
        user.first_name = self.cleaned_data["first_name"]
        user.last_name = self.cleaned_data["last_name"]

        if commit:
            user.save()
        return user
