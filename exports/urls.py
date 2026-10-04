from django.urls import path

from exports import views

app_name = "exports"

urlpatterns = [
    path(
        "versions/<uuid:version_id>/exports/",
        views.ExportListCreateView.as_view(),
        name="export-list",
    ),
    path("exports/<uuid:pk>/download/", views.ExportDownloadView.as_view(), name="export-download"),
]
