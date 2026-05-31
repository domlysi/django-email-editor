from enum import Enum

from django.conf import settings
from django.test.signals import setting_changed


class WYSIWYGEditor(str, Enum):
    TINY_MCE = 'tinymce'
    CKEDITOR5 = "ckeditor5"
    ACE = 'ace'


DEFAULTS = {
    "TINY_MCE_COLOR_MAP": [
        "000000",
        "Black",
        "808080",
        "Gray",
        "FFFFFF",
        "White",
        "FF0000",
        "Red",
        "FFFF00",
        "Yellow",
        "008000",
        "Green",
        "0000FF",
        "Blue",
    ],
    "PREVIEW_ONLY": False,
    "TINY_MCE_INIT": {
        "selector": "#htmlEditor",
        "license_key": "gpl",
        "plugins": [
            "code",
            "fullscreen",
            "preview",
            "searchreplace",
            "table",
            "link",
            "lists",
            "media",
            "image",
            "emoticons",
            "quickbars",
            "autoresize",
            "visualblocks",
            "charmap",
            "anchor",
            "wordcount",
            "help",
        ],
        "entity_encoding": "raw",
        "toolbar": (
            "undo redo | fullscreen preview | "
            "blocks fontfamily fontsize | "
            "bold italic underline strikethrough | "
            "forecolor backcolor | "
            "alignleft aligncenter alignright alignjustify | "
            "bullist numlist outdent indent | "
            "link image | "
            "table | "
            "code searchreplace | "
            "charmap emoticons | help"
        ),
        "font_family_formats": (
            "Arial=arial,helvetica,sans-serif;"
            "Georgia=georgia,'times new roman',serif;"
            "Courier New='courier new',courier,monospace;"
            "Tahoma=tahoma,sans-serif;"
            "Trebuchet MS='trebuchet ms',helvetica,sans-serif;"
            "Verdana=verdana,sans-serif"
        ),
        "font_size_formats": "10pt 11pt 12pt 13pt 14pt 16pt 18pt 20pt 24pt 28pt 32pt 36pt",
        "content_style": "body { font-family: Arial, sans-serif; font-size: 14px; max-width: 640px; margin: 0 auto; padding: 8px; }",
        "table_default_styles": {"width": "100%", "border-collapse": "collapse"},
        "table_default_attributes": {
            "border": "0",
            "cellpadding": "0",
            "cellspacing": "0",
        },
        "quickbars_selection_toolbar": "bold italic underline | forecolor | link | blocks",
        "autoresize_overflow_padding": 10,
        "extended_valid_elements": "svg[*],defs[*],pattern[*],desc[*],metadata[*],g[*],mask[*],path[*],line[*],marker[*],rect[*],circle[*],ellipse[*],polygon[*],polyline[*],linearGradient[*],radialGradient[*],stop[*],image[*],view[*],text[*],textPath[*],title[*],tspan[*],glyph[*],symbol[*],switch[*],use[*]",
    },
    "WYSIWYG_EDITOR": WYSIWYGEditor.TINY_MCE,
    "CONTEXT_TREE_MAX_DEPTH": 3,
}


class AppSettings:
    """
    A settings object that allows the app settings to be accessed as
    properties. For example:
        from app_name.settings import app_settings
        print(app_settings.DEFAULT_NAME)
        
    Based on Django Rest Framework settings.py
    """
    def __init__(self, user_settings=None, defaults=None):
        if user_settings:
            self._user_settings = user_settings
        self.defaults = defaults or DEFAULTS
        self._cached_attrs = set()

    def __getattr__(self, attr):
        if attr not in self.defaults:
            raise AttributeError("Invalid App setting: '%s'" % attr)

        try:
            # Check if present in user settings
            val = self.user_settings[attr]
        except KeyError:
            # Fall back to defaults
            val = self.defaults[attr]

        # Cache the result
        self._cached_attrs.add(attr)
        setattr(self, attr, val)

        if attr == 'TINY_MCE_INIT':
            val['color_map'] = self.TINY_MCE_COLOR_MAP

        return val

    @property
    def user_settings(self):
        if not hasattr(self, '_user_settings'):
            self._user_settings = getattr(settings, 'EMAIL_EDITOR', {})
        return self._user_settings

    def reload(self):
        for attr in self._cached_attrs:
            delattr(self, attr)
        self._cached_attrs.clear()


app_settings = AppSettings(None, DEFAULTS)


def reload_app_settings(*args, **kwargs):
    setting = kwargs['setting']
    if setting == 'EMAIL_EDITOR':
        app_settings.reload()


setting_changed.connect(reload_app_settings)
