"""Integration tests for email_editor.views — auth, API, raw endpoint, POST."""

import json
from unittest.mock import PropertyMock, patch

import pytest
from django.contrib.auth.models import AnonymousUser
from django.test import RequestFactory
from django.urls import reverse

from email_editor.preview import (
    CLASS_REGISTRY,
    EmailPreview,
    get_preview_classes,
    register,
)
from email_editor.settings import app_settings

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_request(factory, method="get", url="/", user=None, data=None, **extra):
    """Build a request with optional authenticated user."""
    if method == "post":
        req = factory.post(url, data=data or {}, **extra)
    else:
        req = factory.get(url, data=data or {}, **extra)
    if user is not None:
        req.user = user
    else:
        req.user = AnonymousUser()
    req.session = {}
    return req


# ---------------------------------------------------------------------------
# Auth ordering  (CRITICAL — is_staff must fire before any processing)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestAuthOrdering:
    """The is_staff check must be the FIRST thing checked in dispatch()."""

    def test_unauthenticated_redirects_to_login(self, rf):
        """Anonymous users should be redirected before any class resolution."""
        url = reverse("preview-template", kwargs={"preview_cls": "SomePreview"})
        req = _make_request(rf, url=url, user=AnonymousUser())
        # We can't easily test dispatch ordering without mocking,
        # but we can verify the redirect response.
        from email_editor.views import EmailTemplatePreviewView

        view = EmailTemplatePreviewView.as_view()
        resp = view(req, preview_cls="SomePreview")
        assert resp.status_code == 302
        assert "/admin/login/" in resp.url

    def test_non_staff_redirects(self, rf, regular_user):
        """Authenticated but non-staff users must be redirected."""
        url = reverse("preview-template", kwargs={"preview_cls": "SomePreview"})
        req = _make_request(rf, url=url, user=regular_user)
        from email_editor.views import EmailTemplatePreviewView

        view = EmailTemplatePreviewView.as_view()
        resp = view(req, preview_cls="SomePreview")
        assert resp.status_code == 302
        assert "/admin/login/" in resp.url

    def test_staff_can_access(self, rf, staff_user):
        """Staff users should pass the gate."""
        url = reverse("preview-template")
        req = _make_request(rf, url=url, user=staff_user)
        from email_editor.views import EmailTemplatePreviewView

        view = EmailTemplatePreviewView.as_view()
        resp = view(req)
        # Should return a template render (200), not a redirect
        assert resp.status_code == 200

    def test_gate_checked_before_preview_cls_lookup(self, rf):
        """is_staff is the first check — non-staff never reach class lookup."""
        url = reverse("preview-template", kwargs={"preview_cls": "NonexistentPreview"})
        req = _make_request(rf, url=url, user=AnonymousUser())
        from email_editor.views import EmailTemplatePreviewView

        view = EmailTemplatePreviewView.as_view()
        resp = view(req, preview_cls="NonexistentPreview")
        # Must redirect (auth gate fires), NOT 400 (which would mean class lookup ran)
        assert resp.status_code == 302
        assert "/admin/login/" in resp.url


# ---------------------------------------------------------------------------
# API response  (JsonResponse serialization)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestApiResponse:
    """Verify the ?api=1 endpoint returns valid JSON with string errors."""

    def test_api_returns_json_without_preview_cls(self, rf, staff_user):
        """Without a preview_cls, the view returns the HTML template even with ?api=1."""
        url = reverse("preview-template") + "?api=1"
        req = _make_request(rf, url=url, user=staff_user)
        from email_editor.views import EmailTemplatePreviewView

        view = EmailTemplatePreviewView.as_view()
        resp = view(req)
        assert resp.status_code == 200
        resp.render()
        # When no preview_cls is registered, render_to_response returns HTML
        assert "text/html" in resp["Content-Type"]

    def test_api_with_registered_preview(self, rf, staff_user):
        """API returns rendered preview data for a registered class."""

        class _ApiTestPreview(EmailPreview):
            template_name = "test_project/welcome_mail.html"
            label = "API Test"

            def get_template_context(self, **kwargs):
                return {"user": staff_user}

        register(_ApiTestPreview)
        try:
            url = (
                reverse("preview-template", kwargs={"preview_cls": "_ApiTestPreview"})
                + "?api=1"
            )
            req = _make_request(rf, url=url, user=staff_user, HTTP_HOST="testserver")
            from email_editor.views import EmailTemplatePreviewView

            view = EmailTemplatePreviewView.as_view()
            resp = view(req, preview_cls="_ApiTestPreview")
            assert resp.status_code == 200
            data = json.loads(resp.content)
            assert "html" in data
            assert "subject" in data
            assert isinstance(data["errors"], list)
        finally:
            CLASS_REGISTRY.remove(("_ApiTestPreview", _ApiTestPreview))


# ---------------------------------------------------------------------------
# Raw endpoint
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestRawEndpoint:
    """?raw=1 returns raw text/html without any wrapper."""

    def test_raw_returns_html_content_type(self, rf, staff_user):
        class _RawTestPreview(EmailPreview):
            template_name = "test_project/welcome_mail.html"

            def get_template_context(self, **kwargs):
                return {"user": staff_user}

        register(_RawTestPreview)
        try:
            url = (
                reverse("preview-template", kwargs={"preview_cls": "_RawTestPreview"})
                + "?raw=1"
            )
            req = _make_request(rf, url=url, user=staff_user, HTTP_HOST="testserver")
            from email_editor.views import EmailTemplatePreviewView

            view = EmailTemplatePreviewView.as_view()
            resp = view(req, preview_cls="_RawTestPreview")
            assert resp.status_code == 200
            assert resp["Content-Type"] == "text/html; charset=utf-8"
            assert "sandbox allow-popups allow-popups-to-escape-sandbox" in resp["Content-Security-Policy"]
            assert "script-src 'none'" in resp["Content-Security-Policy"]
        finally:
            CLASS_REGISTRY.remove(("_RawTestPreview", _RawTestPreview))


@pytest.mark.django_db
class TestEditorEscaping:
    """Stored markup must not break out of the admin editing shell."""

    def test_editor_shell_escapes_embedded_template_content(self, rf, staff_user):
        class _EscapingPreview(EmailPreview):
            template_name = "test.html"

            def get_template_context(self, **kwargs):
                return {}

            def render(self, request=None, context=None):
                return '</template><script>window.previewPwned = true</script>'

            @property
            def subject(self):
                return None

            @property
            def raw_content(self):
                return '</textarea><script>window.editorPwned = true</script>'

            @property
            def context_tree(self):
                return {"user": "staff"}

        register(_EscapingPreview)
        try:
            url = reverse("preview-template", kwargs={"preview_cls": "_EscapingPreview"})
            req = _make_request(rf, url=url, user=staff_user, HTTP_HOST="testserver")
            from email_editor.views import EmailTemplatePreviewView

            view = EmailTemplatePreviewView.as_view()
            resp = view(req, preview_cls="_EscapingPreview")
            assert resp.status_code == 200
            resp.render()

            content = resp.content.decode()
            assert 'sandbox="allow-popups allow-popups-to-escape-sandbox"' in content
            assert '<textarea id="htmlEditor" name="content">&lt;/textarea&gt;' in content
            assert '{{ html|json_script:"email-html-data" }}' not in content
            assert 'id="email-html-data"' in content
            assert '\\u003C/template\\u003E\\u003Cscript\\u003Ewindow.previewPwned = true\\u003C/script\\u003E' in content
        finally:
            CLASS_REGISTRY.remove(("_EscapingPreview", _EscapingPreview))


# ---------------------------------------------------------------------------
# POST  (template save)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestPostSave:
    """Template content posting and saving via preview."""

    def test_post_updates_content(self, rf, staff_user, tmp_template_dir):
        """POST should call instance.write(content) and re-render."""
        _, template_path = tmp_template_dir
        with open(template_path, "w") as temp_template:
            temp_template.write("<p>Original content</p>")

        class _PostTestPreview(EmailPreview):
            template_name = "test_project/welcome_mail.html"

            def get_template_context(self, **kwargs):
                return {"user": staff_user}

        register(_PostTestPreview)
        try:
            url = reverse(
                "preview-template", kwargs={"preview_cls": "_PostTestPreview"}
            )
            from email_editor.views import EmailTemplatePreviewView

            view = EmailTemplatePreviewView.as_view()
            req = _make_request(
                rf,
                method="post",
                url=url,
                user=staff_user,
                data={"content": "<p>Updated content</p>"},
                HTTP_HOST="testserver",
            )
            with patch.object(
                _PostTestPreview,
                "path",
                new_callable=PropertyMock,
                return_value=template_path,
            ):
                resp = view(req, preview_cls="_PostTestPreview")

            assert resp.status_code == 200
            with open(template_path, "r") as temp_template:
                assert temp_template.read() == "<p>Updated content</p>"
        finally:
            CLASS_REGISTRY.remove(("_PostTestPreview", _PostTestPreview))

    def test_post_preview_only_blocked(self, rf, staff_user):
        """When PREVIEW_ONLY is True, POST returns 400."""

        class _ReadonlyPreview(EmailPreview):
            template_name = "test_project/welcome_mail.html"

            def get_template_context(self, **kwargs):
                return {"user": staff_user}

        register(_ReadonlyPreview)
        orig_preview_only = app_settings.PREVIEW_ONLY
        try:
            # Force preview-only mode
            app_settings.PREVIEW_ONLY = True
            url = reverse(
                "preview-template", kwargs={"preview_cls": "_ReadonlyPreview"}
            )
            req = _make_request(
                rf,
                method="post",
                url=url,
                user=staff_user,
                data={"content": "<p>x</p>"},
                HTTP_HOST="testserver",
            )
            from email_editor.views import EmailTemplatePreviewView

            view = EmailTemplatePreviewView.as_view()
            resp = view(req, preview_cls="_ReadonlyPreview")
            assert resp.status_code == 400
        finally:
            app_settings.PREVIEW_ONLY = orig_preview_only
            CLASS_REGISTRY.remove(("_ReadonlyPreview", _ReadonlyPreview))


# ---------------------------------------------------------------------------
# Context data  (category grouping)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestContextData:
    """Verify the context structure: grouping, categories, current template."""

    def test_grouped_by_category(self, rf, staff_user):
        class _CatAPreview(EmailPreview):
            template_name = "test_project/welcome_mail.html"
            category = "Marketing"

            def get_template_context(self, **kwargs):
                return {"user": staff_user}

        class _CatBPreview(EmailPreview):
            template_name = "test_project/welcome_mail.html"
            category = "Transactional"

            def get_template_context(self, **kwargs):
                return {"user": staff_user}

        register(_CatAPreview)
        register(_CatBPreview)
        try:
            url = reverse("preview-template")
            req = _make_request(rf, url=url, user=staff_user)
            from email_editor.views import EmailTemplatePreviewView

            view = EmailTemplatePreviewView.as_view()
            resp = view(req)
            assert resp.status_code == 200
            data = resp.context_data
            assert "preview_cls_grouped" in data
            grouped = data["preview_cls_grouped"]
            assert "Marketing" in grouped
            assert "Transactional" in grouped
            assert data["show_categories"] is True
        finally:
            CLASS_REGISTRY.remove(("_CatAPreview", _CatAPreview))
            CLASS_REGISTRY.remove(("_CatBPreview", _CatBPreview))

    def test_show_categories_false_when_single_group(self, rf, staff_user):
        """When all previews are in one category, show_categories should be False."""

        class _SoloPreview(EmailPreview):
            template_name = "test_project/welcome_mail.html"
            category = None  # becomes "General"

            def get_template_context(self, **kwargs):
                return {"user": staff_user}

        register(_SoloPreview)
        try:
            url = reverse("preview-template")
            req = _make_request(rf, url=url, user=staff_user)
            from email_editor.views import EmailTemplatePreviewView

            view = EmailTemplatePreviewView.as_view()
            resp = view(req)
            assert resp.context_data["show_categories"] is False
        finally:
            CLASS_REGISTRY.remove(("_SoloPreview", _SoloPreview))

    def test_editor_list_in_context(self, rf, staff_user):
        url = reverse("preview-template")
        req = _make_request(rf, url=url, user=staff_user)
        from email_editor.views import EmailTemplatePreviewView

        view = EmailTemplatePreviewView.as_view()
        resp = view(req)
        assert "editor_list" in resp.context_data
        assert "tinymce" in resp.context_data["editor_list"]
        assert "ace" in resp.context_data["editor_list"]


# ---------------------------------------------------------------------------
# Preview class lookup  (404 behavior)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestPreviewClassLookup:
    def test_nonexistent_preview_returns_400(self, rf, staff_user):
        url = reverse("preview-template", kwargs={"preview_cls": "DoesNotExist"})
        req = _make_request(rf, url=url, user=staff_user, HTTP_HOST="testserver")
        from email_editor.views import EmailTemplatePreviewView

        view = EmailTemplatePreviewView.as_view()
        resp = view(req, preview_cls="DoesNotExist")
        assert resp.status_code == 400

    def test_get_preview_cls_returns_none_for_empty_string(self):
        from email_editor.views import EmailTemplatePreviewView

        view = EmailTemplatePreviewView()
        assert view.get_preview_cls("") is None
        assert view.get_preview_cls(None) is None
