import pytest
from django.core.management import call_command
from rest_framework.test import APIClient

pytestmark = pytest.mark.django_db


@pytest.fixture
def schema():
    import io

    from drf_spectacular.renderers import OpenApiYamlRenderer  # noqa: F401

    buffer = io.StringIO()
    call_command("spectacular", "--format", "openapi-json", stdout=buffer)
    import json

    return json.loads(buffer.getvalue())


def test_schema_generates_without_errors(capsys):
    """A warning here means an endpoint is published with a guessed or
    missing shape, which is worse than no documentation."""
    import io

    call_command("spectacular", "--fail-on-warn", stdout=io.StringIO())


def test_schema_is_versioned_and_titled(schema):
    assert schema["info"]["version"] == "1.0.0"
    assert schema["info"]["title"] == "Formy"


def test_every_path_is_under_the_version_prefix(schema):
    """Versioning in the path rather than a header, so a deployed client is
    pinned to a contract and a v2 can run alongside v1."""
    assert all(path.startswith("/api/v1/") for path in schema["paths"])


def test_respondent_endpoints_document_the_resume_token_header(schema):
    operation = schema["paths"]["/api/v1/public/submissions/{id}/"]["get"]
    headers = [p["name"] for p in operation.get("parameters", [])]

    assert "X-Resume-Token" in headers


def test_results_response_is_typed(schema):
    """Free-form JSON would leave a consumer guessing at the shape."""
    operation = schema["paths"]["/api/v1/versions/{version_id}/results/"]["get"]
    ref = operation["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]

    assert ref.endswith("/Results")
    properties = schema["components"]["schemas"]["FieldResult"]["properties"]
    assert "eligible" in properties
    assert "distribution_available" in properties


def test_status_enums_are_named_not_hashed(schema):
    """Machine-generated names like Status526Enum would leak into client
    code generated from this document."""
    names = set(schema["components"]["schemas"])

    assert "SurveyVersionStatusEnum" in names
    assert "SubmissionStatusEnum" in names
    assert not any(
        name.startswith("Status") and name[6].isdigit() for name in names if len(name) > 6
    )


def test_docs_endpoints_are_served(client):
    assert client.get("/api/v1/schema/").status_code == 200
    assert client.get("/api/v1/docs/").status_code == 200
    assert client.get("/api/v1/redoc/").status_code == 200


def test_unknown_api_version_is_rejected():
    """ALLOWED_VERSIONS is the guard that makes a future v2 additive."""
    from django.conf import settings

    assert settings.REST_FRAMEWORK["ALLOWED_VERSIONS"] == ["v1"]
    assert APIClient().get("/api/v2/organizations/").status_code == 404
