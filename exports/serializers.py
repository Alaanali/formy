from rest_framework import serializers

from exports.models import Export


class ExportSerializer(serializers.ModelSerializer):
    class Meta:
        model = Export
        fields = [
            "id",
            "survey_version",
            "status",
            "include_pii",
            "row_count",
            "error",
            "created_at",
            "completed_at",
        ]
        read_only_fields = fields
