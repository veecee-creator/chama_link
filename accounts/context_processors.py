from django.conf import settings


def google_oauth(request):
    return {
        'google_oauth_enabled': bool(
            settings.GOOGLE_OAUTH_CLIENT_ID
            and settings.GOOGLE_OAUTH_CLIENT_SECRET
        ),
    }
