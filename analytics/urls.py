from django.urls import path

from analytics import views

app_name = "analytics"

urlpatterns = [
    path(
        "surveys/<uuid:survey_id>/results/",
        views.SurveyResultsView.as_view(),
        name="survey-results",
    ),
    path(
        "versions/<uuid:version_id>/results/",
        views.VersionResultsView.as_view(),
        name="version-results",
    ),
    path(
        "versions/<uuid:version_id>/submissions/",
        views.SubmissionListView.as_view(),
        name="submission-list",
    ),
    path(
        "files/<uuid:pk>/download/",
        views.SubmissionFileDownloadView.as_view(),
        name="file-download",
    ),
    path(
        "submissions/<uuid:pk>/answers/",
        views.SubmissionAnswersView.as_view(),
        name="submission-answers",
    ),
]
