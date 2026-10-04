from rest_framework import serializers


class FunnelSerializer(serializers.Serializer):
    started = serializers.IntegerField()
    completed = serializers.IntegerField()
    abandoned = serializers.IntegerField()
    completion_rate = serializers.FloatField(allow_null=True)
    average_duration_seconds = serializers.IntegerField(allow_null=True)


class BucketSerializer(serializers.Serializer):
    bucket = serializers.CharField(allow_null=True)
    count = serializers.IntegerField()
    share = serializers.FloatField(
        allow_null=True, help_text="Share of respondents who were shown this field."
    )


class NumericSummarySerializer(serializers.Serializer):
    sum = serializers.FloatField()
    min = serializers.FloatField()
    max = serializers.FloatField()
    average = serializers.FloatField()


class FieldResultSerializer(serializers.Serializer):
    field_id = serializers.UUIDField()
    key = serializers.CharField(allow_null=True)
    label = serializers.CharField(allow_null=True)
    type = serializers.CharField()
    eligible = serializers.IntegerField(
        help_text="Respondents the conditional logic actually showed this field to."
    )
    answered = serializers.IntegerField()
    skipped = serializers.IntegerField()
    response_rate = serializers.FloatField(
        allow_null=True,
        help_text="answered / eligible. Never answered / total submissions: for a "
        "conditionally visible field those differ and the latter is wrong.",
    )
    distribution_available = serializers.BooleanField(
        help_text="False for encrypted fields, whose values cannot be aggregated."
    )
    reason = serializers.CharField(required=False)
    buckets = BucketSerializer(many=True, required=False)
    numeric = NumericSummarySerializer(required=False)


class ResultsSerializer(serializers.Serializer):
    survey_version = serializers.UUIDField()
    version_number = serializers.IntegerField()
    funnel = FunnelSerializer()
    fields = FieldResultSerializer(many=True)


class SubmissionAnswersSerializer(serializers.Serializer):
    submission = serializers.DictField()
    answers = serializers.DictField(
        help_text="Keyed by field UUID. Sensitive fields appear as "
        '{"__redacted__": true} unless the caller holds response.view_pii.'
    )
