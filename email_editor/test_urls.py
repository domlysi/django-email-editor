from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, re_path

urlpatterns = [
    re_path(r"^admin/preview/", include("email_editor.urls")),
    re_path(r"^admin/", admin.site.urls),
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)