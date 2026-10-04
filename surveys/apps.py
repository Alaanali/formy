from django.apps import AppConfig


class SurveysConfig(AppConfig):
    name = "surveys"

    def ready(self):
        from surveys.audit import register

        register()
