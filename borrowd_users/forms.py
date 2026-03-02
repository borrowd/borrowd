from typing import Any

from allauth.account.forms import SetPasswordForm
from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError

from .models import BorrowdUser, Profile

User = get_user_model()

# Common field styles
INPUT_CLASSES = "input w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-borrowd-indigo-500 focus:border-borrowd-indigo-500"


# Factory functions for creating form fields with consistent styling
def create_email_field() -> forms.EmailField:
    """Create an EmailField with consistent styling."""
    return forms.EmailField(
        required=True,
        widget=forms.EmailInput(attrs={"class": INPUT_CLASSES}),
    )


def create_first_name_field() -> forms.CharField:
    """Create a CharField for first name with consistent styling."""
    return forms.CharField(
        max_length=150,
        required=True,
        widget=forms.TextInput(attrs={"class": INPUT_CLASSES}),
    )


def create_last_name_field() -> forms.CharField:
    """Create a CharField for last name with consistent styling."""
    return forms.CharField(
        max_length=150,
        required=True,
        widget=forms.TextInput(attrs={"class": INPUT_CLASSES}),
    )


def create_bio_field(
    placeholder: str = "Tell others a bit about yourself",
    alpine_model: str = "",
) -> forms.CharField:
    """Create a textarea field for bio with consistent styling."""
    attrs = {
        "class": "textarea  w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-borrowd-indigo-500 focus:border-borrowd-indigo-500 placeholder:text-base-content-scale-50",
        "placeholder": placeholder,
        "rows": 3,
        "maxlength": 200,
    }
    if alpine_model:
        attrs["x-model"] = alpine_model

    return forms.CharField(
        required=False,
        max_length=200,
        widget=forms.Textarea(attrs=attrs),
    )


def create_password_input() -> forms.PasswordInput:
    """Create a PasswordInput widget with consistent styling."""
    return forms.PasswordInput(attrs={"class": INPUT_CLASSES})


# Validation utilities
def validate_name_field(value: str | None, field_name: str) -> str:
    """Validate a name field, ensuring it's not empty after stripping whitespace."""
    if not value or not value.strip():
        raise forms.ValidationError(f"{field_name.title()} cannot be empty.")
    return value.strip()


def validate_password_mixed_case(password: str) -> None:
    """Validate password contains both uppercase and lowercase characters."""
    has_upper = any(c.isupper() for c in password)
    has_lower = any(c.islower() for c in password)
    if not (has_upper and has_lower):
        raise forms.ValidationError(
            "Password must contain both uppercase and lowercase characters."
        )


def validate_email_unique(email: str | None) -> str | None:
    """Validate that email is provided and unique."""
    if not email:
        raise forms.ValidationError("Email is required.")
    if User.objects.filter(email=email).exists():
        raise forms.ValidationError("A user with this email already exists.")
    return email


class CustomSignupForm(UserCreationForm[BorrowdUser]):
    """
    Custom signup form that includes first and last name fields
    and uses Django's password validation.
    """

    email = create_email_field()
    first_name = create_first_name_field()
    last_name = create_last_name_field()
    bio = create_bio_field(
        placeholder="Add a little information about yourself! (optional)",
        alpine_model="bioText",
    )

    password1 = forms.CharField(
        widget=create_password_input(),
        help_text="Your password can't be too similar to your other personal information, must contain at least 8 characters, can't be a commonly used password, and can't be entirely numeric.",
    )

    password2 = forms.CharField(
        widget=create_password_input(),
        help_text="Enter the same password as before, for verification.",
    )

    class Meta:
        model = User
        fields = ("email", "first_name", "last_name", "bio", "password1", "password2")

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        # Remove username field since we're using email for login
        if "username" in self.fields:
            del self.fields["username"]

    def clean_email(self) -> str | None:
        email: str | None = self.cleaned_data.get("email")
        return validate_email_unique(email)

    def clean_password1(self) -> str | None:
        password1: str | None = self.cleaned_data.get("password1")
        if not password1:
            raise forms.ValidationError("Password is required.")
        validate_password_mixed_case(password1)
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
            if hasattr(user, "profile"):
                user.profile.bio = self.cleaned_data.get("bio", "")
                user.profile.save()
        return user


class ProfileUpdateForm(forms.ModelForm[Profile]):
    """
    Custom form for updating both Profile and User fields.
    Includes image from Profile and first_name/last_name from User.
    """

    first_name = create_first_name_field()
    last_name = create_last_name_field()

    class Meta:
        model = Profile
        fields = ["image", "bio"]
        widgets = {
            "image": forms.FileInput(
                attrs={
                    "class": "file-input file-input-bordered w-full sr-only",
                    "id": "id_image",
                    "accept": "image/*",
                }
            ),
        }

    email = create_email_field()
    bio = create_bio_field()

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        # Populate the name fields from the associated user
        if self.instance and self.instance.user:
            self.fields["first_name"].initial = self.instance.user.first_name
            self.fields["last_name"].initial = self.instance.user.last_name
            self.fields["email"].initial = self.instance.user.email
        self.fields["bio"].initial = self.instance.bio

    def clean_first_name(self) -> str:
        first_name: str | None = self.cleaned_data.get("first_name")
        return validate_name_field(first_name, "first name")

    def clean_last_name(self) -> str:
        last_name: str | None = self.cleaned_data.get("last_name")
        return validate_name_field(last_name, "last name")

    def clean_email(self) -> str:
        email: str | None = self.cleaned_data.get("email")
        if not email:
            raise forms.ValidationError("Email is required.")
        existing_user = (
            User.objects.filter(email__iexact=email)
            .exclude(pk=self.instance.user.pk)
            .exists()
        )
        if existing_user:
            raise forms.ValidationError("A user with this email already exists.")
        return email

    def save(self, commit: bool = True) -> Profile:
        profile = super().save(commit=False)

        # Update the associated user's name fields
        if profile.user:
            profile.user.first_name = self.cleaned_data["first_name"]
            profile.user.last_name = self.cleaned_data["last_name"]
            profile.user.email = self.cleaned_data["email"]

        profile.bio = self.cleaned_data.get("bio", profile.bio)

        if commit:
            if profile.user:
                profile.user.save()
            profile.save()

        return profile


class ChangePasswordForm(SetPasswordForm):  # type: ignore[misc]
    """
    Custom password change form that doesn't require the old password.

    Why this is the way it is:
    ---------------------
    Django-allauth's default ChangePasswordForm requires three fields:
    - oldpassword (current password)
    - password1 (new password)
    - password2 (confirm new password)

    Our UX design only shows two fields (new password + confirmation).
    This omits the old password requirement. By extending SetPasswordForm instead of
    ChangePasswordForm, we get only password1/password2 fields (no need for the old password)

    This class exists as a named form so that it can be referenced in ACCOUNT_FORMS
    settings (borrowd/config/base.py).

    You can add custom validation to this class if AllAuth's validators are not enough.
    Validation will only apply on the password change form, not on signup.

    Design reference:
    https://www.figma.com/design/wMliTL8KGBlUACk0d8fkZ3/Borrow-d---Mobile-App--mid-fidelity-?node-id=746-18213&m=dev
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        msg = "Fill a password to change it."
        self.fields["password1"].error_messages["required"] = msg
        self.fields["password2"].error_messages["required"] = msg

    def clean_password1(self) -> str:
        """Validate password contains both uppercase and lowercase characters."""
        password1: str | None = self.cleaned_data.get("password1")
        if not password1:
            raise forms.ValidationError("Fill a password to change it.")
        validate_password_mixed_case(password1)
        return password1
