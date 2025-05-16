from ..base import *  # noqa: F403

DEBUG = False

# Media storage
# will need to add media storage settings for cloud provider
# e.g. using django-storages[google]
# Security considerations: https://docs.djangoproject.com/en/5.2/topics/security/#user-uploaded-content-security
# MEDIA_ROOT = ''
# MEDIA_URL = "https://storage.googleapis.com/<your-bucket-name>/media/"
# STORAGES = {
#     "default": {
#         "BACKEND": "storages.backends.gcloud.GoogleCloudStorage"
#     }
# }