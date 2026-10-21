
"""
URL configuration for Chama Link.
"""

from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static


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

    # Main Chama Link application
    path('', include('groups.urls')),
]


# Serve uploaded media files during development
if settings.DEBUG:
    urlpatterns += static(
        settings.MEDIA_URL,
        document_root=settings.MEDIA_ROOT
    )
