from django.apps import AppConfig, apps


class EmailEditorConfig(AppConfig):
    name = 'email_editor'

    def ready(self):
        for app_config in apps.get_app_configs():

            import importlib
            try:
                importlib.import_module(f'{app_config.module.__name__}.preview')
            except ImportError:
                continue

        super().ready()

