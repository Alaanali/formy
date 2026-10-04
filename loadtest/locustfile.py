import random
import uuid

from locust import HttpUser, between, constant_pacing, events, task
from locust.exception import StopUser

#: Discovered from the database at startup so the run needs no arguments.
STATE: dict = {"version_id": None, "staff_token": None}

#: Breach any of these and a headless run exits non-zero. The claim under
#: test is that analytics are maintained incrementally rather than computed
#: on read: if it holds, staff latency stays flat while write volume climbs.
THRESHOLDS = {
    # The scalability claim: reading aggregates must not scale with the
    # number of responses already collected.
    "GET results": 500,
    # Unpaginated and sorted, so its cost grows directly with responses
    # collected -- the most likely place for the claim to break.
    "GET submission list": 1500,
    "GET submission state": 600,
    # Autosave is the hot write path. Drift here means index bloat.
    "PATCH autosave": 400,
    "POST start submission": 400,
    "POST submit": 800,
}
MAX_FAILURE_RATIO = 0.01

#: Below this a percentile is one outlier, not a measurement: locust computes
#: p95 as int(n * 0.95), so with n=15 it returns the slowest request.
MIN_SAMPLES = 40


@events.init_command_line_parser.add_listener
def _(parser):
    parser.add_argument("--version-id", type=str, default="", help="Published version UUID")
    parser.add_argument(
        "--staff-user", type=str, default="demo-admin", help="Username for the staff profile"
    )
    parser.add_argument("--staff-password", type=str, default="demo-password")


@events.test_start.add_listener
def discover(environment, **_kwargs):
    """Find a published version so the run is turnkey."""
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from scripts._bootstrap import published_version, setup_django

    setup_django()

    override = getattr(environment.parsed_options, "version_id", "")
    if override:
        from surveys.models import SurveyVersion

        version = SurveyVersion.objects.get(pk=override)
    else:
        version = published_version()

    STATE["version_id"] = str(version.id)
    print(f"Load target: version {version.id} of {version.survey.name}")


class Respondent(HttpUser):
    """Anonymous. The traffic a campaign actually generates."""

    weight = 90
    wait_time = between(1, 4)

    @task
    def complete_a_survey(self):
        version_id = STATE.get("version_id")
        if not version_id:
            return

        started = self.client.post(
            f"/api/v1/public/versions/{version_id}/submissions/",
            name="POST start submission",
        )
        if started.status_code != 201:
            return
        body = started.json()
        headers = {"X-Resume-Token": body["resume_token"]}
        url = f"/api/v1/public/submissions/{body['id']}/"

        state = self.client.get(url, headers=headers, name="GET submission state")
        if state.status_code != 200:
            return
        schema = state.json()["schema"]

        # One section at a time, so the conditional logic is re-resolved on
        # every request. Visibility comes from the server's own payload:
        # sampling blindly from the schema would post answers to hidden
        # fields, which the server accepts and discards, diluting the figure.
        visible = state.json()["visible"]
        options = state.json()["options"]

        for section in sorted(schema.get("sections", []), key=lambda s: s.get("order", 0)):
            answers = {}
            for field_id in section.get("fields", []):
                if not visible.get(field_id):
                    continue
                field = schema["fields"][field_id]
                value = _sample(field, options.get(field_id))
                if value is not None:
                    answers[field_id] = value
            if not answers:
                continue

            saved = self.client.patch(
                url, json={"answers": answers}, headers=headers, name="PATCH autosave"
            )
            if saved.status_code == 200:
                # The next section is driven by what the server now shows.
                visible = saved.json()["visible"]
                options = saved.json()["options"]

        self.client.post(f"{url}submit/", json={"answers": {}}, headers=headers, name="POST submit")


class Analyst(HttpUser):
    """Authenticated."""

    weight = 10
    wait_time = constant_pacing(1.0)

    def on_start(self):
        options = self.environment.parsed_options
        response = self.client.post(
            "/api/v1/auth/token/",
            json={
                "username": options.staff_user,
                "password": options.staff_password,
            },
            name="POST auth token",
        )
        if response.status_code == 200:
            self.client.headers["Authorization"] = f"Token {response.json()['token']}"
            return

        # Unauthenticated, every staff request is a fast 401 that satisfies
        # the latency budget, so the claim under test is never exercised.
        message = (
            f"Analyst could not authenticate ({response.status_code}). "
            "Every staff measurement would be a 401. Check --staff-user, "
            "and note /auth/token/ is throttled: use `make run-load`."
        )
        print(f"\nLOAD SETUP FAILED: {message}")
        self.environment.runner.quit()
        raise StopUser()

    @task(3)
    def read_results(self):
        if STATE.get("version_id"):
            self.client.get(f"/api/v1/versions/{STATE['version_id']}/results/", name="GET results")

    @task(1)
    def list_submissions(self):
        if STATE.get("version_id"):
            self.client.get(
                f"/api/v1/versions/{STATE['version_id']}/submissions/",
                name="GET submission list",
            )


@events.quitting.add_listener
def enforce_thresholds(environment, **_kwargs):
    """Turn the run into a pass or a fail."""
    stats = environment.stats
    problems = []

    ratio = stats.total.fail_ratio
    if ratio > MAX_FAILURE_RATIO:
        problems.append(f"failure ratio {ratio:.1%} exceeds {MAX_FAILURE_RATIO:.0%}")

    for name, budget_ms in THRESHOLDS.items():
        # Locust keys stats by (name, method); every request is named, so one
        # name identifies one logical operation.
        for (stat_name, _method), entry in stats.entries.items():
            if stat_name != name:
                continue
            if entry.num_requests < MIN_SAMPLES:
                # Silently skipping would let an untested path pass.
                problems.append(
                    f"{name}: only {entry.num_requests} samples, "
                    f"{MIN_SAMPLES} needed for a meaningful p95"
                )
                break
            p95 = entry.get_response_time_percentile(0.95)
            if p95 > budget_ms:
                problems.append(f"{name} p95 {p95:.0f}ms exceeds its {budget_ms}ms budget")
            break
        else:
            problems.append(f"{name}: no requests recorded")

    # A run that issued nothing is a failed run. The usual cause is
    # discover() raising: locust logs event-hook exceptions and carries on,
    # so every task returns at its guard and nothing is ever requested.
    if stats.total.num_requests == 0:
        problems.append("no requests were issued; check the target and the database")

    if problems:
        print("\nLOAD RUN FAILED:")
        for problem in problems:
            print(f"  - {problem}")
        environment.process_exit_code = 1
        return

    print("\nAll latency and failure thresholds met.")
    # Deliberately not setting 0: locust checks process_exit_code first, so
    # forcing a zero would make its own runner-error and greenlet-exception
    # checks unreachable, and a crashed task would report a green run.


def _sample(field: dict, allowed: list[str] | None = None):
    """A plausible answer, randomised so respondents take different branches."""
    field_type = field.get("type")

    if field_type in ("dropdown", "radio"):
        values = (
            allowed if allowed is not None else [o["value"] for o in field.get("options") or []]
        )
        return random.choice(values) if values else None
    if field_type == "checkbox":
        values = (
            allowed if allowed is not None else [o["value"] for o in field.get("options") or []]
        )
        return random.sample(values, k=min(2, len(values))) if values else None
    if field_type == "number":
        # `or` rather than a default: the key can be present and null.
        low = field.get("min") or 0
        high = field.get("max") or 100
        return random.randint(int(low), int(high))
    if field_type == "date":
        return "2026-06-15"
    if field_type == "boolean":
        return random.choice([True, False])
    if field_type in ("text", "textarea"):
        return uuid.uuid4().hex[: min(20, field.get("max_length") or 20)]
    return None
