import abc
import os
import re
from typing import Union

import bleach
from django.template import Context, Template, TemplateSyntaxError, loader
from django.template.backends.django import DjangoTemplates
from django.template.loader import _engine_list

from email_editor.settings import app_settings

is_post_office_installed = None

DJANGO_TEMPLATE_PLACEHOLDERS = {
    "{%": "__EMAIL_EDITOR_DJANGO_BLOCK_OPEN__",
    "%}": "__EMAIL_EDITOR_DJANGO_BLOCK_CLOSE__",
    "{{": "__EMAIL_EDITOR_DJANGO_VARIABLE_OPEN__",
    "}}": "__EMAIL_EDITOR_DJANGO_VARIABLE_CLOSE__",
    "{#": "__EMAIL_EDITOR_DJANGO_COMMENT_OPEN__",
    "#}": "__EMAIL_EDITOR_DJANGO_COMMENT_CLOSE__",
}

ALLOWED_EMAIL_ATTRIBUTES = {
    "*": ["style"],
    "a": [
        "href",
        "title",
        "name",
        "style",
        "id",
        "class",
        "shape",
        "coords",
        "alt",
        "target",
    ],
    "b": ["style", "id", "class"],
    "br": ["style", "id", "class"],
    "big": ["style", "id", "class"],
    "blockquote": ["title", "style", "id", "class"],
    "caption": ["style", "id", "class"],
    "code": ["style", "id", "class"],
    "del": ["title", "style", "id", "class"],
    "div": ["title", "style", "id", "class", "align"],
    "dt": ["style", "id", "class"],
    "dd": ["style", "id", "class"],
    "font": ["color", "size", "face", "style", "id", "class"],
    "h1": ["style", "id", "class", "align"],
    "h2": ["style", "id", "class", "align"],
    "h3": ["style", "id", "class", "align"],
    "h4": ["style", "id", "class", "align"],
    "h5": ["style", "id", "class", "align"],
    "h6": ["style", "id", "class", "align"],
    "hr": ["style", "id", "class"],
    "i": ["style", "id", "class"],
    "img": ["style", "id", "class", "src", "alt", "height", "width", "title"],
    "ins": ["title", "style", "id", "class"],
    "li": ["style", "id", "class"],
    "map": ["shape", "coords", "href", "alt", "title", "style", "id", "class", "name"],
    "ol": ["style", "id", "class"],
    "p": ["style", "id", "class", "align"],
    "pre": ["style", "id", "class"],
    "s": ["style", "id", "class"],
    "small": ["style", "id", "class"],
    "strong": ["style", "id", "class"],
    "span": ["title", "style", "id", "class", "align"],
    "sub": ["style", "id", "class"],
    "sup": ["style", "id", "class"],
    "table": ["border", "width", "style", "id", "class", "cellspacing", "cellpadding"],
    "tbody": ["align", "valign", "style", "id", "class"],
    "td": [
        "width",
        "height",
        "style",
        "id",
        "class",
        "align",
        "valign",
        "colspan",
        "rowspan",
    ],
    "tfoot": ["align", "valign", "style", "id", "class"],
    "th": ["width", "height", "style", "id", "class", "colspan", "rowspan"],
    "thead": ["align", "valign", "style", "id", "class"],
    "tr": ["align", "valign", "style", "id", "class"],
    "u": ["style", "id", "class"],
    "ul": ["style", "id", "class"],
    "html": ["xmlns"],
    "head": [],
    "body": [],
    "meta": ["content", "name", "http-equiv"],
    "title": [],
    "link": ["type", "rel", "href"],
}

try:
    from post_office.models import EmailTemplate
    is_post_office_installed = True
except ModuleNotFoundError as e:
    is_post_office_installed = False

CLASS_REGISTRY = []


def _humanize_class_name(cls_name: str) -> str:
    """Convert e.g. 'WelcomeEmailPreview' -> 'Welcome Email'."""
    original = cls_name
    if cls_name.endswith("Preview"):
        cls_name = cls_name[: -len("Preview")]
    cls_name = cls_name.lstrip("_")
    return re.sub(r"(?<=[a-z])(?=[A-Z])", " ", cls_name).strip() or original


def register(cls):
    CLASS_REGISTRY.append((cls.__name__, cls))


def get_preview_classes():
    return [
        {
            "key": name,
            "label": cls.label or _humanize_class_name(name),
            "category": cls.category,
            "cls": cls,
        }
        for name, cls in CLASS_REGISTRY
    ]


def extract_subject(template: Template, context=None) -> Union[str, None]:
    """
    This will extract the subject from a html file if it's in the first line like following format:

    e.g. <!-- Subject: test!! -->
    => results in "test!!"
    """
    rendered = template.render(context)
    subject_regex = re.search(r"<!--.*[sS]ubject: *(?P<subject>.*) *-->", rendered)
    if not subject_regex:
        return
    return subject_regex.group('subject').strip()


class EmailPreview(abc.ABC):
    template_name = None
    is_post_office = False
    language = None
    label: str = None  # human-readable name; auto-derived from class name if None
    category: str = None  # optional grouping; shown as 'General' if None

    def __init__(self):
        if not self.template_name:
            raise Exception(f'No "template_name" set in "{self.__class__.__name__}"')

        if self.is_post_office and not is_post_office_installed:
            raise Exception(f'"post_office" is used by "{self.__class__.__name__}" but is not installed.')

    @staticmethod
    def _build_tree(item: dict, depth=0, max_depth=app_settings.CONTEXT_TREE_MAX_DEPTH):
        result = {}
        for key, value in item.items():
            if depth == max_depth:
                result[key] = value
                continue

            if hasattr(value, "__dict__") and not isinstance(value, type):
                result[key] = EmailPreview._build_tree(
                    value.__dict__, depth=depth + 1, max_depth=max_depth
                )
                continue

            if isinstance(value, dict):
                result[key] = EmailPreview._build_tree(
                    value, depth=depth + 1, max_depth=max_depth
                )
                continue

            result[key] = value

        return result

    @property
    def context(self):
        return self.get_template_context()

    @property
    def subject(self):
        if self.is_post_office:
            # render str
            template = Template(self.template.subject or '')
            return template.render(Context(self.context))

        return extract_subject(self.template, context=self.context)

    @staticmethod
    def _is_full_html(content: str) -> bool:
        """Return True if content is a full HTML document (has a <body> tag)."""
        return bool(re.search(r"<body[\s>]", content, re.IGNORECASE))

    @staticmethod
    def _extract_body(content: str) -> str:
        """Extract the innerHTML of <body> from a full HTML document."""
        match = re.search(
            r"<body[^>]*>(.*?)</body>", content, re.IGNORECASE | re.DOTALL
        )
        if match:
            return match.group(1).strip()
        return content

    @staticmethod
    def _inject_body(original: str, new_body: str) -> str:
        """Replace the <body> content in the original HTML with new_body."""
        return re.sub(
            r"(<body[^>]*>)(.*?)(</body>)",
            lambda m: m.group(1) + "\n" + new_body + "\n" + m.group(3),
            original,
            flags=re.IGNORECASE | re.DOTALL,
        )

    @staticmethod
    def _clean_content(content):
        for token, placeholder in DJANGO_TEMPLATE_PLACEHOLDERS.items():
            content = content.replace(token, placeholder)

        cleaned = bleach.clean(
            content,
            tags=ALLOWED_EMAIL_ATTRIBUTES.keys(),
            attributes=ALLOWED_EMAIL_ATTRIBUTES,
            strip_comments=False,
        )

        for token, placeholder in DJANGO_TEMPLATE_PLACEHOLDERS.items():
            cleaned = cleaned.replace(placeholder, token)

        return cleaned

    def write(self, content):
        cleaned_content = self._clean_content(content)

        if self.is_post_office:
            template_instance = self.template
            template_instance.html_content = cleaned_content
            template_instance.save()
            return

        # If the file is a full HTML document, preserve head/doctype and only
        # replace the body content so that <style>, <meta>, etc. are not lost.
        try:
            with open(self.path, "r") as f:
                original = f.read()
            if self._is_full_html(original):
                cleaned_content = self._inject_body(original, cleaned_content)
        except OSError:
            pass

        tmp_path = self.path + ".tmp"
        with open(tmp_path, "w") as file:
            file.write(cleaned_content)
        os.replace(tmp_path, self.path)

    @property
    def context_tree(self):
        return self._build_tree(self.get_template_context())

    @property
    def path(self):
        try:
            return self.template.origin.name
        except TemplateSyntaxError:
            pass

        engines = _engine_list(using=None)
        for django_template in engines:
            for t_dir in django_template.template_dirs:
                template_path = os.path.join(t_dir, self.template_name)
                is_file = os.path.isfile(template_path)
                if not is_file:
                    continue
                return template_path

    @property
    def raw_content(self):
        if self.is_post_office:
            return self.template.html_content or self.template.content or ''

        with open(self.path, 'r') as file:
            content = file.read()

        # Full HTML documents: expose only the body content to the editor so
        # that <head>, <style> and DOCTYPE don't appear as raw text in WYSIWYG.
        if self._is_full_html(content):
            return self._extract_body(content)

        return content

    @property
    def template(self) -> Union[EmailTemplate, Template]:
        if self.is_post_office:
            try:
                return EmailTemplate.objects.get(
                    name=self.template_name,
                    default_template__isnull=True if not self.language else False,
                    language=self.language or ''
                )
            except EmailTemplate.DoesNotExist as e:
                raise EmailTemplate.DoesNotExist(f'"{self.template_name}" - {e}')

        return loader.get_template(self.template_name)

    def get_template_context(self, *args, **kwargs):
        raise NotImplementedError('No context defined')

    def render(self, request, **kwargs):
        kwargs['request'] = request
        if self.is_post_office:
            template = Template(self.template.html_content)
            return template.render(Context(self.get_template_context(**kwargs)))

        return self.template.render(context=self.get_template_context(**kwargs), request=request).strip()