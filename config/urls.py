
"""
URL configuration for Chama Link.
"""

from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import path, include, re_path
from django.conf import settings
from django.conf.urls.static import static
from django.views.static import serve
from django.http import Http404


def serve_profile_picture(request, path):
    """Serve only raster profile images, with a safe, explicit content type."""
    content_types = {
        '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.png': 'image/png',
        '.gif': 'image/gif', '.webp': 'image/webp',
    }
    extension = path.rsplit('.', 1)[-1].lower() if '.' in path else ''
    content_type = content_types.get(f'.{extension}')
    if not content_type:
        raise Http404

    response = serve(request, path, document_root=settings.MEDIA_ROOT)
    response['Content-Type'] = content_type
    response['X-Content-Type-Options'] = 'nosniff'
    return response


urlpatterns = [
    # Django Admin
    path('admin/', admin.site.urls),

    # Password Change
    path(
        'accounts/password_change/',
        auth_views.PasswordChangeView.as_view(
            template_name='registration/password_change_form.html',
            success_url='/settings/'
        ),
        name='password_change'
    ),

    # Accounts: Login, Registration, Logout
    path('accounts/', include('accounts.urls')),
    path('accounts/', include('allauth.urls')),

    # Profile pictures are validated as images by ProfilePictureForm and need
    # to remain reachable on hosted deployments where DEBUG is disabled.
    re_path(
        r'^media/profile_pictures/(?P<path>.+)$',
        serve_profile_picture,
        name='profile_picture_media',
    ),

    # Main Chama Link application
    path('', include('groups.urls')),
]


# Serve uploaded media files during development
if settings.DEBUG:
    urlpatterns += static(
        settings.MEDIA_URL,
        document_root=settings.MEDIA_ROOT
    )
