# borrowd_beta
Models, signup form/view, and middleware to support beta release of app

## Features
- Generate beta codes to send link to beta users and track usage
- Beta signup form and token handling
- Permission middleware to check/validate beta tokens

### Installation
1. Add the app to your `INSTALLED_APPS` in `settings.py`:

    ```settings.py
    INSTALLED_APPS = [
        ...
        'borrowd_beta',
        ...
    ]
    ```
2. Add the app to your `MIDDLEWARE` in `settings.py`:

    ```settings.py
    MIDDLEWARE = [
        ...
        "borrowd_beta.middleware.BetaAccessMiddleware",
        ...
    ]
    ```

3. Run migrations:

    ```bash
    python manage.py migrate
    ```

4. Include the app's URLs in your project's `urls.py`:

    ```python
    from django.urls import path, include

    urlpatterns = [
        ...
        path('', include('borrowd_beta.urls')),
        ...
    ]
    ```

## Configuration

Available Settings:

```settings.py
BETA_SIGNUP_REDIRECT_PATH = '/'  # Default to base path
BETA_COOKIE_DOMAIN = None  # domain (if not localhost)
BETA_SECURE_COOKIE = False # whether cookie is https only
```
