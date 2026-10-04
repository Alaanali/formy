from django.contrib.auth import authenticate
from rest_framework import serializers


class TokenRequestSerializer(serializers.Serializer):
    username = serializers.CharField()
    password = serializers.CharField(style={"input_type": "password"}, trim_whitespace=False)

    def validate(self, attrs):
        user = authenticate(
            request=self.context.get("request"),
            username=attrs["username"],
            password=attrs["password"],
        )
        # One message for every failure mode. Distinguishing "no such user"
        # from "wrong password" turns the endpoint into an account oracle.
        if not user:
            raise serializers.ValidationError(
                {"detail": "Invalid credentials."}, code="authorization"
            )
        attrs["user"] = user
        return attrs


class TokenSerializer(serializers.Serializer):
    token = serializers.CharField(read_only=True)
    user_id = serializers.UUIDField(read_only=True)
    username = serializers.CharField(read_only=True)
