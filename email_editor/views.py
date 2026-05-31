import typing

from django.contrib import admin
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import ObjectDoesNotExist
from django.http import HttpResponse, HttpResponseBadRequest, JsonResponse
from django.shortcuts import redirect
from django.template import TemplateSyntaxError
from django.urls import reverse
from django.utils import translation
from django.utils.translation import get_language
from django.views import generic

from email_editor.preview import get_preview_classes
from email_editor.settings import WYSIWYGEditor, app_settings

if typing.TYPE_CHECKING:
    from email_editor.preview import EmailPreview


class EmailTemplatePreviewView(LoginRequiredMixin, generic.TemplateView):
    template_name = "email_editor/email-preview.html"
    preview_cls = None
    editor = None

    def __init__(self, *args, **kwargs):
        self.is_preview_only = app_settings.PREVIEW_ONLY
        super().__init__(*args, **kwargs)

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_staff:
            return redirect(f"{reverse('admin:login')}?next={request.get_full_path()}")

        if request.GET.get("preview_cls"):
            return redirect(
                reverse(
                    "preview-template",
                    kwargs={"preview_cls": request.GET["preview_cls"]},
                )
            )

        preview_cls_str = kwargs.get("preview_cls")
        if preview_cls_str:
            try:
                self.preview_cls = self.get_preview_cls(preview_cls_str)
            except ObjectDoesNotExist:
                return HttpResponseBadRequest("Not found")

        self.editor = request.GET.get("editor")
        self.errors = []

        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        preview_list = get_preview_classes()
        grouped = {}
        for tpl in preview_list:
            cat = tpl["category"] or "General"
            grouped.setdefault(cat, []).append(tpl)
        current_key = self.kwargs.get("preview_cls")
        context["preview_cls_list"] = preview_list
        context["preview_cls_grouped"] = grouped
        context["show_categories"] = len(grouped) > 1
        context["current_key"] = current_key
        context["current_template"] = next(
            (t for t in preview_list if t["key"] == current_key), None
        )
        context.update(admin.site.each_context(self.request))
        context["tiny_mce_settings"] = app_settings.TINY_MCE_INIT
        context["editor_list"] = [e.value for e in WYSIWYGEditor]
        return context

    def get_preview_cls(self, preview_cls_str):
        if not preview_cls_str:
            return None

        tpl = next(
            (t for t in get_preview_classes() if t["key"] == preview_cls_str), None
        )
        if not tpl:
            raise ObjectDoesNotExist()
        return tpl["cls"]

    def get(self, request, *args, **kwargs):
        is_api_response = request.GET.get("api")

        if not self.preview_cls:
            return self.render_to_response(context=self.get_context_data())

        instance = self.preview_cls()     # type: EmailPreview
        try:
            html = instance.render(request)
            subject = instance.subject
        except TemplateSyntaxError as e:
            subject = None
            html = None
            self.errors.append(str(e))

        context = {
            'html': html,
            'subject': subject,
            'errors': self.errors,
            'editor_type': self.editor or app_settings.WYSIWYG_EDITOR
        }

        if not self.is_preview_only:
            try:
                context["context_tree"] = instance.context_tree
                context["raw"] = instance.raw_content
            except Exception:
                context["context_tree"] = None
                context["raw"] = None

        if is_api_response:
            return JsonResponse(context)

        if request.GET.get("raw"):
            response = HttpResponse(html or "", content_type="text/html; charset=utf-8")
            response["Content-Security-Policy"] = (
                "sandbox allow-popups allow-popups-to-escape-sandbox; "
                "default-src * data: blob: 'unsafe-inline'; "
                "script-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
            )
            return response

        # set language
        if instance.language:
            translation.activate(instance.language)
            request.session["_language"] = (
                instance.language
            )  # LANGUAGE_SESSION_KEY removed in Django 5

        raw_url = request.build_absolute_uri(
            reverse(
                "preview-template", kwargs={"preview_cls": self.kwargs["preview_cls"]}
            )
            + "?raw=1"
        )
        return self.render_to_response(
            {
                "language": get_language(),
                "raw_url": raw_url,
                **context,
                **self.get_context_data(),
            }
        )

    def post(self, request, *args, **kwargs):
        if self.is_preview_only:
            return HttpResponseBadRequest('preview only')

        content = request.POST.get('content')
        if not self.preview_cls:
            return self.get(request, *args, **kwargs)

        instance = self.preview_cls()
        instance.write(content)

        return self.get(request, *args, **kwargs)