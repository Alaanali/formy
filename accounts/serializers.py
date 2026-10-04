from django.contrib.auth import authenticate
from rest_framework import serializers

from accounts.models import Membership


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


class MembershipSerializer(serializers.ModelSerializer):
    class Meta:
        model = Membership
        fields = ["id", "user", "organization", "role", "created_at"]
        read_only_fields = ["id", "organization", "created_at"]

    def validate_role(self, role):
        """An organization must keep at least one owner."""
        instance = self.instance
        leaving_owner = (
            instance is not None
            and instance.role == Membership.OrgRole.OWNER
            and role != Membership.OrgRole.OWNER
        )
        if leaving_owner and is_last_owner(instance):
            raise serializers.ValidationError(
                "This is the organization's only owner. Promote another owner first."
            )
        return role


def is_last_owner(membership: Membership) -> bool:
    return (
        not Membership.objects.filter(
            organization_id=membership.organization_id, role=Membership.OrgRole.OWNER
        )
        .exclude(pk=membership.pk)
        .exists()
    )
