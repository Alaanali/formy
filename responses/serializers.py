from rest_framework import serializers

from responses.models import Submission, SubmissionFile


class SubmissionStateSerializer(serializers.Serializer):
    """What a respondent's client needs to render the next step."""

    id = serializers.UUIDField(read_only=True)
    survey = serializers.CharField(read_only=True)
    status = serializers.CharField(read_only=True)
    started_at = serializers.DateTimeField(read_only=True)
    last_activity_at = serializers.DateTimeField(read_only=True)
    submitted_at = serializers.DateTimeField(read_only=True, allow_null=True)
    resume_expires_at = serializers.DateTimeField(read_only=True, allow_null=True)

    schema = serializers.JSONField(read_only=True)
    answers = serializers.JSONField(read_only=True)
    visible = serializers.JSONField(read_only=True)
    required = serializers.JSONField(read_only=True)
    options = serializers.JSONField(read_only=True)


class StartSubmissionSerializer(serializers.ModelSerializer):
    """Returned once, at creation. The only place the resume token appears."""

    class Meta:
        model = Submission
        fields = ["id", "status", "resume_token", "resume_expires_at", "started_at"]
        read_only_fields = fields


class AnswerBatchSerializer(serializers.Serializer):
    answers = serializers.DictField(allow_empty=True)


class SubmissionSummarySerializer(serializers.ModelSerializer):
    """Staff-facing row. Carries no answers and no resume token."""

    class Meta:
        model = Submission
        fields = ["id", "status", "started_at", "submitted_at", "last_activity_at"]
        read_only_fields = fields


class UploadSerializer(serializers.Serializer):
    """Phase one of a file answer."""

    field_id = serializers.UUIDField(help_text="The file-type field this upload answers.")
    file = serializers.FileField()


class SubmissionFileSerializer(serializers.ModelSerializer):
    """What comes back from an upload."""

    class Meta:
        model = SubmissionFile
        fields = ["id", "field_id", "original_name", "content_type", "size_bytes"]
        read_only_fields = fields
