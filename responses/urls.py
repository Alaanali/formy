from django.urls import path

from responses import views

app_name = "responses"

urlpatterns = [
    path(
        "versions/<uuid:version_id>/submissions/",
        views.StartSubmissionView.as_view(),
        name="submission-start",
    ),
    path("submissions/<uuid:pk>/", views.SubmissionView.as_view(), name="submission-detail"),
    path("submissions/<uuid:pk>/files/", views.UploadView.as_view(), name="submission-upload"),
    path("submissions/<uuid:pk>/submit/", views.SubmitView.as_view(), name="submission-submit"),
]
