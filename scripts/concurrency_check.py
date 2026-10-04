import json
import os
import threading
import urllib.error
import urllib.request

from _bootstrap import field_by_key, published_version, setup_django

# Overridable so `make PORT=... e2e` reaches the right server.
BASE = os.environ.get("API_BASE", "http://127.0.0.1:8000")
CONCURRENT = 40

succeeded: list[int] = []
rejected: list[str] = []
lock = threading.Lock()


def call(method, path, body=None, headers=None):
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(
        BASE + path,
        data=data,
        headers={"Content-Type": "application/json", **(headers or {})},
        method=method,
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read() or b"{}")


def one_respondent(version_id, country, nps, index):
    try:
        started = call("POST", f"/api/v1/public/versions/{version_id}/submissions/")
        call(
            "POST",
            f"/api/v1/public/submissions/{started['id']}/submit/",
            {"answers": {country: "eg", nps: 9}},
            {"X-Resume-Token": started["resume_token"]},
        )
        with lock:
            succeeded.append(index)
    except urllib.error.HTTPError as exc:
        with lock:
            rejected.append(f"{exc.code}")
    except Exception as exc:  # noqa: BLE001
        with lock:
            rejected.append(str(exc))


def main() -> int:
    setup_django()
    from analytics.models import FieldAggregate, SurveyStat

    version = published_version()
    country = field_by_key(version, "country")
    nps = field_by_key(version, "nps")

    # SurveyStat is created lazily on the first submission, so a freshly
    # seeded version has none yet.
    stat = SurveyStat.objects.filter(survey_version=version).first()
    before_completed = stat.completed_count if stat else 0
    bucket = FieldAggregate.objects.filter(
        survey_version=version, field_id=country, bucket="eg"
    ).first()
    before_bucket = bucket.answered_count if bucket else 0

    threads = [
        threading.Thread(target=one_respondent, args=(str(version.id), country, nps, i))
        for i in range(CONCURRENT)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    landed = len(succeeded)
    # .filter().first() rather than .get(): on a version with no prior
    # responses these rows may not exist yet, and the point is to diagnose
    # that clearly rather than die with DoesNotExist.
    stat = SurveyStat.objects.filter(survey_version=version).first()
    bucket = FieldAggregate.objects.filter(
        survey_version=version, field_id=country, bucket="eg"
    ).first()
    if stat is None or bucket is None:
        print("No rollup rows exist. Did any submission actually land?")
        return 1
    # Counted BEFORE fetching, because the duplicate-totals-row regression
    # this guards against would make .get() raise MultipleObjectsReturned
    # and the diagnostic below would never print.
    totals_rows = FieldAggregate.objects.filter(
        survey_version=version, field_id=country, bucket__isnull=True
    ).count()
    totals = (
        FieldAggregate.objects.filter(
            survey_version=version, field_id=country, bucket__isnull=True
        ).first()
        if totals_rows
        else None
    )

    print(f"{landed}/{CONCURRENT} submissions landed ({len(rejected)} rejected)")
    if rejected:
        print(f"  rejections: {sorted(set(rejected))}  (429 means the throttle worked)")
    print()
    print(f"  completed    {before_completed} -> {stat.completed_count}   expected +{landed}")
    print(f"  bucket 'eg'  {before_bucket} -> {bucket.answered_count}   expected +{landed}")
    print(f"  totals rows  {totals_rows}   expected 1")
    print()

    problems = []
    # Without a floor every comparison becomes x == x + 0 and the script
    # reports success having landed nothing -- which is what happens when
    # the server is down, or when a second run hits the hourly throttle.
    # The regression this exists to detect would pass identically.
    MINIMUM = CONCURRENT // 2
    if landed < MINIMUM:
        problems.append(
            f"only {landed} of {CONCURRENT} submissions landed, below the "
            f"{MINIMUM} needed for the result to mean anything "
            "(is the server up? try `make run-load` for raised throttles)"
        )
    if stat.completed_count != before_completed + landed:
        problems.append("completed counter lost increments")
    if bucket.answered_count != before_bucket + landed:
        problems.append("bucket counter lost increments")
    if totals_rows != 1:
        # Postgres treats NULLs as distinct in a unique index, so without
        # nulls_distinct=False each submission would insert its own totals
        # row instead of incrementing the shared one.
        problems.append(f"totals row duplicated ({totals_rows} rows)")
    if totals is None:
        problems.append("no totals row was created")
    elif totals.eligible_count != stat.completed_count:
        problems.append("eligible count diverged from completions")

    if problems:
        print("FAILED:")
        for problem in problems:
            print(f"  - {problem}")
        return 1

    print("PASS: no increments lost under concurrency")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
