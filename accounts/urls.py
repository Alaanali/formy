from django.urls import path

from accounts import views

app_name = "accounts"

urlpatterns = [
    path("auth/token/", views.ObtainTokenView.as_view(), name="obtain-token"),
    path("auth/token/revoke/", views.RevokeTokenView.as_view(), name="revoke-token"),
    path("auth/whoami/", views.WhoAmIView.as_view(), name="whoami"),
]
