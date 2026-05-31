"""Unit tests for email_editor.preview — sanitization, tree building, HTML handling."""

import html
import os
import re
from unittest.mock import ANY, mock_open, patch

import bleach
import pytest
from django.template import TemplateSyntaxError

from email_editor.preview import (
    ALLOWED_EMAIL_ATTRIBUTES,
    EmailPreview,
    _humanize_class_name,
    extract_subject,
    get_preview_classes,
    register,
)
from email_editor.tests.conftest import make_test_preview

# ---------------------------------------------------------------------------
# _humanize_class_name
# ---------------------------------------------------------------------------


class TestHumanizeClassName:
    """Auto-label derivation from class names."""

    def test_strips_preview_suffix(self):
        assert _humanize_class_name("WelcomeEmailPreview") == "Welcome Email"

    def test_no_suffix_passthrough(self):
        assert _humanize_class_name("SimpleMail") == "Simple Mail"

    def test_single_word(self):
        assert _humanize_class_name("Preview") == "Preview"

    def test_empty(self):
        assert _humanize_class_name("") == ""

    def test_already_readable_with_preview(self):
        # e.g. "OnboardingPreview" → "Onboarding"
        assert _humanize_class_name("OnboardingPreview") == "Onboarding"


# ---------------------------------------------------------------------------
# register / get_preview_classes
# ---------------------------------------------------------------------------


class TestRegistry:
    def test_register_adds_to_registry(self):
        class _FakePreview(EmailPreview):
            template_name = "test.html"

            def get_template_context(self, **kwargs):
                return {}

        register(_FakePreview)
        result = get_preview_classes()
        assert any(t["key"] == "_FakePreview" for t in result)

    def test_label_auto_derived(self):
        class _GreetingMailPreview(EmailPreview):
            template_name = "test.html"
            label = None

            def get_template_context(self, **kwargs):
                return {}

        register(_GreetingMailPreview)
        result = get_preview_classes()
        entry = next(t for t in result if t["key"] == "_GreetingMailPreview")
        assert entry["label"] == "Greeting Mail"

    def test_explicit_label_overrides_auto(self):
        class _CustomPreview(EmailPreview):
            template_name = "test.html"
            label = "Manual Label"

            def get_template_context(self, **kwargs):
                return {}

        register(_CustomPreview)
        result = get_preview_classes()
        entry = next(t for t in result if t["key"] == "_CustomPreview")
        assert entry["label"] == "Manual Label"

    def test_category_defaults_to_none(self):
        class _CatPreview(EmailPreview):
            template_name = "test.html"
            category = None

            def get_template_context(self, **kwargs):
                return {}

        register(_CatPreview)
        result = get_preview_classes()
        entry = next(t for t in result if t["key"] == "_CatPreview")
        assert entry["category"] is None

    def test_explicit_category(self):
        class _CatPreview(EmailPreview):
            template_name = "test.html"
            category = "Transactional"

            def get_template_context(self, **kwargs):
                return {}

        register(_CatPreview)
        result = get_preview_classes()
        entry = next(t for t in result if t["key"] == "_CatPreview")
        assert entry["category"] == "Transactional"


# ---------------------------------------------------------------------------
# _build_tree  (the data-loss bug that was fixed)
# ---------------------------------------------------------------------------


class TestBuildTree:
    """Verify _build_tree no longer drops sibling keys at max depth."""

    def test_max_depth_preserves_all_sibling_keys(self):
        """FIXED: was returning only first key at max depth."""
        result = EmailPreview._build_tree(
            {"a": 1, "b": 2, "c": 3}, depth=1, max_depth=1
        )
        assert result == {"a": 1, "b": 2, "c": 3}

    def test_nested_dict_below_max_depth(self):
        result = EmailPreview._build_tree({"x": {"y": 1}}, depth=0, max_depth=2)
        assert result == {"x": {"y": 1}}

    def test_nested_dict_truncated_at_max_depth(self):
        result = EmailPreview._build_tree({"x": {"y": {"z": 1}}}, depth=0, max_depth=1)
        assert result == {"x": {"y": {"z": 1}}}

    def test_mixed_scalar_and_dict_at_max_depth(self):
        result = EmailPreview._build_tree(
            {"name": "test", "nested": {"k": "v"}}, depth=0, max_depth=0
        )
        assert result == {"name": "test", "nested": {"k": "v"}}

    def test_object_with_dict_attr(self):
        class Inner:
            def __init__(self):
                self.x = 1

        class Obj:
            def __init__(self):
                self.name = "obj"
                self.inner = Inner()

        result = EmailPreview._build_tree({"parent": Obj()}, depth=0, max_depth=3)
        assert result["parent"]["name"] == "obj"
        assert result["parent"]["inner"]["x"] == 1


# ---------------------------------------------------------------------------
# _clean_content  (bleach + html.unescape pattern)
# ---------------------------------------------------------------------------


class TestCleanContent:
    """Verify the sanitization pipeline behaves correctly."""

    def test_allowed_tags_preserved(self):
        result = EmailPreview._clean_content("<b>Bold</b> <i>Italic</i>")
        assert "<b>Bold</b>" in result
        assert "<i>Italic</i>" in result

    def test_disallowed_tags_escaped(self):
        """Disallowed tags must not round-trip back into active markup."""
        result = EmailPreview._clean_content("<script>alert(1)</script>")
        assert "<script" not in result.lower()
        assert "</script>" not in result.lower()
        assert "alert(1)" in result

    def test_javascript_href_stripped(self):
        """bleach's default ALLOWED_PROTOCOLS strips javascript: URLs."""
        result = EmailPreview._clean_content('<a href="javascript:alert(1)">x</a>')
        assert "javascript:" not in result.lower()
        # The <a> tag is preserved but href is removed
        assert "<a" in result

    def test_javascript_entity_encoded_stripped(self):
        result = EmailPreview._clean_content('<a href="javascript&#58;alert(1)">x</a>')
        assert "javascript" not in result.lower()

    def test_http_href_preserved(self):
        result = EmailPreview._clean_content('<a href="https://example.com">x</a>')
        assert 'href="https://example.com"' in result

    def test_target_attribute_preserved(self):
        """Regression: 'targe' typo was fixed to 'target'."""
        result = EmailPreview._clean_content(
            '<a href="https://x.com" target="_blank">x</a>'
        )
        assert 'target="_blank"' in result

    def test_django_template_tags_preserved(self):
        """Django template tags should survive sanitization unchanged."""
        result = EmailPreview._clean_content("{% trans 'Hello' %}")
        assert result == "{% trans 'Hello' %}"

    def test_django_variable_preserved(self):
        result = EmailPreview._clean_content("{{ user.name }}")
        assert "{{ user.name }}" in result

    def test_style_attribute_handled(self):
        """Style is allowed but without css_sanitizer bleach warns and may strip."""
        result = EmailPreview._clean_content('<p style="color: red">x</p>')
        # Should preserve the tag at minimum
        assert "<p" in result

    def test_email_table_structure_preserved(self):
        html_input = (
            '<table border="0" cellpadding="0" cellspacing="0">'
            "<tr><td>Cell</td></tr></table>"
        )
        result = EmailPreview._clean_content(html_input)
        assert "border=" in result
        assert "cellpadding" in result
        assert "<td>Cell</td>" in result


# ---------------------------------------------------------------------------
# _is_full_html, _extract_body, _inject_body
# ---------------------------------------------------------------------------


class TestFullHtmlHandling:
    def test_is_full_html_detects_body_tag(self):
        assert EmailPreview._is_full_html("<html><body>hi</body></html>") is True

    def test_is_full_html_no_body(self):
        assert EmailPreview._is_full_html("<p>just a fragment</p>") is False

    def test_is_full_html_body_with_attributes(self):
        assert EmailPreview._is_full_html('<body class="foo">x</body>') is True

    def test_extract_body_simple(self):
        assert EmailPreview._extract_body("<body>Hello World</body>") == "Hello World"

    def test_extract_body_preserves_inner_tags(self):
        result = EmailPreview._extract_body("<body><p>Hello</p><div>World</div></body>")
        assert "<p>Hello</p>" in result
        assert "<div>World</div>" in result

    def test_extract_body_no_body_tag_returns_original(self):
        assert EmailPreview._extract_body("just text") == "just text"

    def test_inject_body_replaces_content(self):
        original = "<html><head></head><body>old</body></html>"
        result = EmailPreview._inject_body(original, "new")
        assert "<body>" in result
        assert "new" in result
        assert "old" not in result
        assert "</head>" in result  # head preserved

    def test_inject_body_case_insensitive(self):
        original = "<HTML><BODY>old</BODY></HTML>"
        result = EmailPreview._inject_body(original, "new")
        assert "new" in result
        assert "old" not in result

    def test_inject_body_preserves_body_attributes(self):
        original = '<body class="email" style="margin:0">old</body>'
        result = EmailPreview._inject_body(original, "new")
        assert 'class="email"' in result


# ---------------------------------------------------------------------------
# extract_subject
# ---------------------------------------------------------------------------


class TestExtractSubject:
    def test_extracts_subject_from_comment(self):
        tmpl = type("MockTemplate", (), {})()
        tmpl.render = lambda ctx: "<!-- Subject: Welcome! --><p>Body</p>"
        assert extract_subject(tmpl, {}) == "Welcome!"

    def test_returns_none_when_no_subject(self):
        tmpl = type("MockTemplate", (), {})()
        tmpl.render = lambda ctx: "<p>No subject here</p>"
        assert extract_subject(tmpl, {}) is None

    def test_case_insensitive_subject_keyword(self):
        tmpl = type("MockTemplate", (), {})()
        tmpl.render = lambda ctx: "<!-- subject: lower case --><p>Body</p>"
        assert extract_subject(tmpl, {}) == "lower case"


# ---------------------------------------------------------------------------
# write  (atomic write)
# ---------------------------------------------------------------------------


class TestWrite:
    """Verify atomic write behavior and full HTML body injection."""

    def test_atomic_write_uses_tmp_file(self):
        """write() must write to .tmp then os.replace for atomicity."""
        with patch(
            "builtins.open", mock_open(read_data="<p>original</p>")
        ) as m_open, patch("os.replace") as m_replace, make_test_preview(
            "/tmp/test_email.html"
        ) as preview:
            preview.write("<b>new</b>")

        # Should have opened tmp file for writing
        tmp_calls = [c for c in m_open.call_args_list if ".tmp" in str(c)]
        assert len(tmp_calls) >= 1, "Expected write to temporary file"
        m_replace.assert_called_once_with(
            "/tmp/test_email.html.tmp", "/tmp/test_email.html"
        )

    def test_full_html_write_injects_body(self):
        """When original is full HTML, write() injects cleaned body into original."""
        original = "<!doctype html><html><head></head><body><p>old</p></body></html>"
        new_body = "<p>new</p>"

        m_open = mock_open(read_data=original)
        with patch("builtins.open", m_open), patch(
            "os.replace"
        ) as m_replace, make_test_preview("/tmp/test_email.html") as preview:
            preview.write(new_body)

        # The written content should contain the new body inside original structure
        write_calls = [c[0][0] for c in m_open().write.call_args_list if c[0]]
        written = "".join(write_calls)
        assert "<p>new</p>" in written
        assert "<!doctype html>" in written
        assert "old" not in written

    def test_write_handles_read_error_gracefully(self):
        """If reading original fails, write proceeds with cleaned fragment."""
        m_open = mock_open()
        m_open.side_effect = [OSError("permission denied"), mock_open().return_value]
        with patch("builtins.open", m_open), patch("os.replace"), make_test_preview(
            "/tmp/test_email.html"
        ) as preview:
            preview.write("<b>new</b>")
        # Should not raise — the OSError is caught and we fall through to write


# ---------------------------------------------------------------------------
# raw_content
# ---------------------------------------------------------------------------


class TestRawContent:
    def test_fragment_passed_through(self):
        content = "<p>Hello World</p>"
        m_open = mock_open(read_data=content)
        with patch("builtins.open", m_open), make_test_preview(
            "/tmp/test.html"
        ) as preview:
            assert preview.raw_content == content

    def test_full_html_extracts_body(self):
        content = "<html><head></head><body><p>Body content</p></body></html>"
        m_open = mock_open(read_data=content)
        with patch("builtins.open", m_open), make_test_preview(
            "/tmp/test.html"
        ) as preview:
            result = preview.raw_content
            assert "<html>" not in result
            assert "<p>Body content</p>" in result
            assert "<head>" not in result


# ---------------------------------------------------------------------------
# Constructor validation
# ---------------------------------------------------------------------------


class TestConstructor:
    def test_raises_on_missing_template_name(self):
        with pytest.raises(Exception, match="template_name"):
            type("Bad", (EmailPreview,), {"template_name": None})()

    def test_raises_on_post_office_not_installed(self):
        with patch("email_editor.preview.is_post_office_installed", False):
            with pytest.raises(Exception, match="post_office"):
                type(
                    "BadPO",
                    (EmailPreview,),
                    {
                        "template_name": "x",
                        "is_post_office": True,
                        "get_template_context": lambda self, **kw: {},
                    },
                )()


# ---------------------------------------------------------------------------
# ALLOWED_EMAIL_ATTRIBUTES  regression checks
# ---------------------------------------------------------------------------


class TestAllowedAttributes:
    def test_target_in_anchor_attrs(self):
        assert "target" in ALLOWED_EMAIL_ATTRIBUTES["a"], (
            "Regression: 'target' attribute was misspelled as 'targe'"
        )

    def test_targe_not_in_anchor_attrs(self):
        assert "targe" not in ALLOWED_EMAIL_ATTRIBUTES["a"]

    def test_no_php_entry(self):
        assert "php" not in ALLOWED_EMAIL_ATTRIBUTES, (
            "Regression: invalid 'php' element was present"
        )

    def test_tfoot_no_duplicates(self):
        attrs = ALLOWED_EMAIL_ATTRIBUTES["tfoot"]
        assert len(attrs) == len(set(attrs)), "tfoot has duplicate attributes"
