"""
URL configuration for UploadData project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.1/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path, include, re_path  # Add 'path' here
from django.views.static import serve
from django.conf import settings
from django.conf.urls.static import static

# urlpatterns = [
#     path('admin/', admin.site.urls),  # Admin login
#     path('', include('users.urls')),  # Custom login for users
# ] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include('users.urls')),
]

# Uploaded files are served whatever DEBUG is set to. They were previously
# inside the DEBUG branch, so turning debug off - which is what stops Django
# leaking tracebacks - would have broken every Download button on the L1, L2
# and home pages.
#
# The route is written out rather than built with conf.urls.static.static():
# that helper returns an empty list whenever DEBUG is False, by design, so it
# cannot be used for exactly the case this needs to cover.
urlpatterns += [
    re_path(
        r'^%s(?P<path>.*)$' % settings.MEDIA_URL.lstrip('/'),
        serve,
        {'document_root': settings.MEDIA_ROOT},
    ),
]

# Static is only needed by the Django admin. Served whatever DEBUG is set to,
# for the same reason as media above: gunicorn serves nothing on its own, so
# turning debug off would otherwise leave the admin unstyled.
urlpatterns += [
    re_path(
        r'^%s(?P<path>.*)$' % settings.STATIC_URL.lstrip('/'),
        serve,
        {'document_root': settings.STATIC_ROOT},
    ),
]
