import random
import uuid

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

from accounts.models import Membership, Organization
from responses.services import save_answers, start_submission
from surveys.models import Section, Survey, SurveyAccess, SurveyVersion
from surveys.publish import publish

User = get_user_model()


class Command(BaseCommand):
    help = "Seed a published demo survey with optional responses."

    def add_arguments(self, parser):
        parser.add_argument("--responses", type=int, default=0)
        parser.add_argument("--slug", type=str, default="demo")

    def _user(self, username: str, **defaults):
        user, created = User.objects.get_or_create(username=username, defaults=defaults)
        if created:
            user.set_password("demo-password")
            user.save()
        return user

    def handle(self, *args, **options):
        org, _ = Organization.objects.get_or_create(
            slug="demo-org", defaults={"name": "Demo Research"}
        )

        # Django's is_superuser is a master key: ModelBackend.has_perm
        # returns True for every permission, which bypasses the capability
        # model entirely. Keeping it on a separate identity is what lets the
        # three org roles below actually demonstrate the difference between
        # themselves -- a superuser demo-admin made RBAC look like a no-op.
        root, created = User.objects.get_or_create(
            username="demo-root",
            defaults={"email": "root@example.com", "is_staff": True, "is_superuser": True},
        )
        if created:
            root.set_password("demo-password")
            root.save()

        owner = self._user("demo-owner")
        Membership.objects.get_or_create(
            user=owner, organization=org, defaults={"role": Membership.OrgRole.OWNER}
        )

        admin = self._user("demo-admin", email="demo@example.com")
        Membership.objects.get_or_create(
            user=admin, organization=org, defaults={"role": Membership.OrgRole.ADMIN}
        )

        analyst = self._user("demo-analyst")
        Membership.objects.get_or_create(
            user=analyst, organization=org, defaults={"role": Membership.OrgRole.MEMBER}
        )

        survey, _ = Survey.objects.get_or_create(
            organization=org,
            slug=options["slug"],
            defaults={"name": "Customer Experience 2026", "created_by": admin},
        )
        SurveyAccess.objects.get_or_create(
            user=analyst, survey=survey, defaults={"role": SurveyAccess.SurveyRole.ANALYST}
        )

        if survey.versions.published().exists():
            version = survey.versions.published().order_by("-version_number").first()
            self.stdout.write(f"Already published: {version.id}")
        else:
            version = self._build(survey, admin)

        if options["responses"]:
            self._respond(version, options["responses"])

        self.stdout.write(self.style.SUCCESS(f"Published version: {version.id}"))
        self.stdout.write(f"Survey: {survey.id}")
        self.stdout.write(
            "Users (password: demo-password)\n"
            "  demo-owner    org owner: manages members and grants survey access\n"
            "  demo-admin    org admin: every survey, but cannot manage members\n"
            "  demo-analyst  member with an analyst grant on this survey only\n"
            "  demo-root     Django superuser, for /admin/ only"
        )
        self.stdout.write("Get a token: POST /api/v1/auth/token/ {username, password}")

    def _build(self, survey, admin) -> SurveyVersion:
        country, age, nps, city, reasons, national_id, comments = (
            str(uuid.uuid7()) for _ in range(7)
        )
        draft = SurveyVersion.objects.create_draft(survey, created_by=admin)

        Section.objects.create(
            version=draft,
            key="about",
            title="About you",
            order=1,
            content={
                country: {
                    "type": "dropdown",
                    "key": "country",
                    "label": "Country",
                    "required": True,
                    "options": [
                        {"value": "sa", "label": "Saudi Arabia"},
                        {"value": "eg", "label": "Egypt"},
                        {"value": "ae", "label": "United Arab Emirates"},
                    ],
                },
                age: {
                    "type": "number",
                    "key": "age",
                    "label": "Age",
                    "min": 16,
                    "max": 100,
                },
                national_id: {
                    "type": "text",
                    "key": "national_id",
                    "label": "National ID",
                    "sensitive": True,
                },
            },
        )
        Section.objects.create(
            version=draft,
            key="location",
            title="Where you are",
            order=2,
            content={
                city: {
                    "type": "dropdown",
                    "key": "city",
                    "label": "City",
                    # Depends on an answer in the previous section, which is
                    # what makes the whole section disappear for anyone who
                    # did not pick Saudi Arabia: a section renders only while
                    # one of its fields is visible.
                    "visible": {"all": [{"field": country, "op": "eq", "value": "sa"}]},
                    "required": {"any": [{"field": age, "op": "gte", "value": 21}]},
                    "options": [
                        # Options filtered by an answer in another section.
                        {
                            "value": "riyadh",
                            "label": "Riyadh",
                            "when": {"all": [{"field": country, "op": "eq", "value": "sa"}]},
                        },
                        {
                            "value": "jeddah",
                            "label": "Jeddah",
                            "when": {"all": [{"field": country, "op": "eq", "value": "sa"}]},
                        },
                    ],
                }
            },
        )
        Section.objects.create(
            version=draft,
            key="feedback",
            title="Your feedback",
            order=3,
            content={
                nps: {
                    "type": "number",
                    "key": "nps",
                    "label": "How likely are you to recommend us?",
                    "min": 0,
                    "max": 10,
                    "required": True,
                },
                reasons: {
                    "type": "checkbox",
                    "key": "reasons",
                    "label": "What drove that score?",
                    # Only asked of detractors.
                    "visible": {"all": [{"field": nps, "op": "lte", "value": 6}]},
                    "options": [
                        {"value": "price", "label": "Price"},
                        {"value": "support", "label": "Support"},
                        {"value": "speed", "label": "Speed"},
                    ],
                },
                comments: {
                    "type": "textarea",
                    "key": "comments",
                    "label": "Anything else?",
                    "max_length": 500,
                },
            },
        )

        version = publish(draft)
        self.stdout.write("Built and published a 3-section survey.")
        return version

    def _respond(self, version, count):
        fields = version.schema["fields"]
        by_key = {f.get("key"): fid for fid, f in fields.items()}

        for _ in range(count):
            submission = start_submission(version)
            country = random.choice(["sa", "eg", "ae"])
            score = random.randint(0, 10)

            answers = {
                by_key["country"]: country,
                by_key["age"]: random.randint(18, 70),
                by_key["national_id"]: f"{random.randint(10**9, 10**10 - 1)}",
                by_key["nps"]: score,
            }
            if country == "sa":
                answers[by_key["city"]] = random.choice(["riyadh", "jeddah"])
            if score <= 6:
                answers[by_key["reasons"]] = random.sample(
                    ["price", "support", "speed"], k=random.randint(1, 2)
                )

            save_answers(submission, answers, complete=True)

        self.stdout.write(f"Created {count} completed responses.")
