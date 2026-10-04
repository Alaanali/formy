from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.authtoken.models import Token
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from accounts.serializers import TokenRequestSerializer, TokenSerializer


class ObtainTokenView(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    # Unauthenticated and credential-guessing by nature, so it is rate
    # limited harder than anything else.
    throttle_scope = "auth"

    @extend_schema(
        tags=["auth"],
        request=TokenRequestSerializer,
        responses={200: TokenSerializer, 400: OpenApiResponse(description="Invalid credentials.")},
        summary="Exchange credentials for an API token",
        description="Send the token as `Authorization: Token <value>` on later requests.",
    )
    def post(self, request):
        serializer = TokenRequestSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)

        user = serializer.validated_data["user"]
        token, _ = Token.objects.get_or_create(user=user)
        return Response(
            {"token": token.key, "user_id": str(user.pk), "username": user.get_username()}
        )


class RevokeTokenView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["auth"],
        request=None,
        responses={204: OpenApiResponse(description="Token revoked.")},
        summary="Revoke the caller's token",
        description=(
            "Takes effect immediately. Being able to revoke without waiting "
            "for an expiry is the main reason this is a token rather than a "
            "self-contained JWT."
        ),
    )
    def post(self, request):
        Token.objects.filter(user=request.user).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class WhoAmIView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["auth"],
        responses={200: TokenSerializer},
        summary="Identify the authenticated caller",
    )
    def get(self, request):
        return Response({"user_id": str(request.user.pk), "username": request.user.get_username()})
