import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def setup_django(settings: str = "formy.settings.dev") -> None:
    sys.path.insert(0, str(ROOT))
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", settings)
    import django

    django.setup()


DEMO_SLUG = "demo"


def published_version(slug: str = DEMO_SLUG):
    """The newest published version of the seeded demo survey."""
    from surveys.models import SurveyVersion

    version = (
        SurveyVersion.objects.published()
        .filter(survey__slug=slug)
        .order_by("-published_at", "-version_number")
        .select_related("survey")
        .first()
    )
    if version is None:
        raise SystemExit(f"No published version of the {slug!r} survey. Run `make seed` first.")
    return version


def field_by_key(version, key: str) -> str:
    """Field ids are builder-minted UUIDs, so scripts look them up by the
    `key` the seed command sets."""
    for field_id, definition in version.schema["fields"].items():
        if definition.get("key") == key:
            return field_id
    raise SystemExit(f"No field with key {key!r} in version {version.id}.")
