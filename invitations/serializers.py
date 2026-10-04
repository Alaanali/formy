from rest_framework import serializers

from invitations.models import InvitationBatch


class CreateBatchSerializer(serializers.Serializer):
    recipients = serializers.ListField(
        child=serializers.EmailField(),
        min_length=1,
        max_length=10_000,
        help_text="Addresses are hashed on arrival and never stored.",
    )


class InvitationBatchSerializer(serializers.ModelSerializer):
    class Meta:
        model = InvitationBatch
        fields = [
            "id",
            "survey_version",
            "status",
            "total",
            "sent_count",
            "error",
            "created_at",
            "completed_at",
        ]
        read_only_fields = fields


class RedeemedSerializer(serializers.Serializer):
    """What a respondent gets for their invitation token."""

    id = serializers.UUIDField(read_only=True)
    status = serializers.CharField(read_only=True)
    resume_token = serializers.CharField(read_only=True)
    resume_expires_at = serializers.DateTimeField(read_only=True, allow_null=True)
