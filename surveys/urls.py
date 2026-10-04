from django.urls import path

from surveys import views

app_name = "surveys"

urlpatterns = [
    path("organizations/", views.OrganizationListView.as_view(), name="organization-list"),
    path(
        "organizations/<uuid:organization_id>/surveys/",
        views.SurveyListCreateView.as_view(),
        name="survey-list",
    ),
    path("surveys/<uuid:pk>/", views.SurveyDetailView.as_view(), name="survey-detail"),
    path(
        "o/<slug:org_slug>/surveys/<slug:slug>/",
        views.SurveyBySlugView.as_view(),
        name="survey-by-slug",
    ),
    path(
        "surveys/<uuid:survey_id>/access/",
        views.SurveyAccessListCreateView.as_view(),
        name="access-list",
    ),
    path("access/<uuid:pk>/", views.SurveyAccessDetailView.as_view(), name="access-detail"),
    path(
        "surveys/<uuid:survey_id>/versions/",
        views.SurveyVersionListCreateView.as_view(),
        name="version-list",
    ),
    path("versions/<uuid:pk>/", views.SurveyVersionDetailView.as_view(), name="version-detail"),
    path(
        "versions/<uuid:version_id>/sections/",
        views.SectionListCreateView.as_view(),
        name="section-list",
    ),
    path("sections/<uuid:pk>/", views.SectionDetailView.as_view(), name="section-detail"),
    path(
        "versions/<uuid:version_id>/publish/",
        views.PublishView.as_view(),
        name="version-publish",
    ),
]
