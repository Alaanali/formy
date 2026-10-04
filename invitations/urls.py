from django.urls import path

from invitations import views

app_name = "invitations"

urlpatterns = [
    path(
        "versions/<uuid:version_id>/invitations/",
        views.InvitationBatchListCreateView.as_view(),
        name="invitation-list",
    ),
    path(
        "public/invitations/<str:token>/redeem/",
        views.RedeemInvitationView.as_view(),
        name="invitation-redeem",
    ),
]
