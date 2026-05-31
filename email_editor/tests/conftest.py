"""Shared fixtures for email_editor tests."""

import os
import tempfile
from contextlib import contextmanager
from unittest.mock import MagicMock, PropertyMock, patch

import pytest
from django.contrib.auth.models import User
from django.template import Context, Template, TemplateSyntaxError

from email_editor.preview import (
    CLASS_REGISTRY,
    EmailPreview,
    _humanize_class_name,
    get_preview_classes,
    register,
)


@contextmanager
def make_test_preview(path_value="/tmp/test_email.html", **overrides):
    """Create a minimal EmailPreview instance with ``path`` property mocked.

    Usage::

        with make_test_preview("/tmp/x.html") as preview:
            preview.write("<b>new</b>")
    """
    extra = {
        "template_name": "test.html",
        "is_post_office": False,
        "get_template_context": lambda self, **kw: {},
        **overrides,
    }
    klass = type("_TestPreview", (EmailPreview,), extra)
    instance = klass()
    with patch.object(
        klass, "path", new_callable=PropertyMock, return_value=path_value
    ):
        yield instance


@pytest.fixture(autouse=True)
def _reset_registry():
    """Isolate registry between tests so one test's register() doesn't leak."""
    original = list(CLASS_REGISTRY)
    CLASS_REGISTRY.clear()
    yield
    CLASS_REGISTRY.clear()
    CLASS_REGISTRY.extend(original)


@pytest.fixture
def staff_user(db):
    """Create a staff user for view tests."""
    return User.objects.create_user(username="staff", password="pass", is_staff=True)


@pytest.fixture
def regular_user(db):
    """Create a non-staff authenticated user."""
    return User.objects.create_user(username="regular", password="pass", is_staff=False)


@pytest.fixture
def tmp_template_dir():
    """Create a temporary directory with a test template file."""
    with tempfile.TemporaryDirectory() as tmpdir:
        template_path = os.path.join(tmpdir, "test_email.html")
        yield tmpdir, template_path


@pytest.fixture
def simple_preview_cls():
    """Return a minimal registered EmailPreview subclass using a file template."""

    class _TestPreview(EmailPreview):
        template_name = "test_project/welcome_mail.html"
        label = "Test Preview"
        category = "Test Category"

        def get_template_context(self, **kwargs):
            return {"user": None}

    # Register and unregister around test
    register(_TestPreview)
    yield _TestPreview
    CLASS_REGISTRY.remove((_TestPreview.__name__, _TestPreview))


@pytest.fixture
def mock_template():
    """Return a mock Django Template that renders predictably."""
    tmpl = MagicMock(spec=Template)
    tmpl.render.return_value = "<!-- Subject: Hello World --><p>Body</p>"
    return tmpl
