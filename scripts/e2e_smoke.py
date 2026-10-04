import http.cookiejar
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
import uuid

from _bootstrap import setup_django

# Overridable so `make PORT=... e2e` reaches the right server.
BASE = os.environ.get("API_BASE", "http://127.0.0.1:8000")
RESULTS: list[tuple[bool, str, object, object, str]] = []


class Client:
    """A single API consumer: staff with a token, or an anonymous respondent."""

    def __init__(self):
        self.jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar))
        self.headers: dict[str, str] = {}

    def call(self, method, path, body=None, headers=None, raw=False):
        url = BASE + path
        data = json.dumps(body).encode() if body is not None else None
        merged = {
            "Accept": "application/json",
            "Referer": url,
            **self.headers,
            **(headers or {}),
        }
        if data:
            merged["Content-Type"] = "application/json"

        request = urllib.request.Request(url, data=data, headers=merged, method=method)
        try:
            with self.opener.open(request, timeout=30) as response:
                payload = response.read()
                # Returned as-is: dict() would make header lookups
                # case-sensitive and silently weaken them.
                return response.status, (payload if raw else _decode(payload)), response.headers
        except urllib.error.HTTPError as exc:
            payload = exc.read()
            return exc.code, (payload if raw else _decode(payload)), exc.headers

    def raw_post(self, path, body: bytes, content_type: str):
        """A multipart POST, for the file-upload phase."""
        request = urllib.request.Request(
            BASE + path,
            data=body,
            headers={"Accept": "application/json", "Content-Type": content_type, **self.headers},
            method="POST",
        )
        try:
            with self.opener.open(request, timeout=30) as response:
                return response.status, _decode(response.read()), response.headers
        except urllib.error.HTTPError as exc:
            return exc.code, _decode(exc.read()), exc.headers

    def login(self, username, password):
        """What a real client does: trade credentials for a token, then send
        it on everything afterwards."""
        code, body, _ = self.call(
            "POST", "/api/v1/auth/token/", {"username": username, "password": password}
        )
        if code == 200:
            self.headers["Authorization"] = f"Token {body['token']}"
        return code


def _decode(payload):
    try:
        return json.loads(payload)
    except Exception:
        return payload[:200].decode(errors="replace")


#: Compared against by the summary, so a block skipped by a guard cannot
#: shrink the total and still read as "all checks passed".
EXPECTED_CHECKS = 87

#: Kept as a constant so the download leg can assert a byte-for-byte return.
PDF_BYTES = b"%PDF-1.4 e2e"


def _get(payload, key, default=""):
    """Read a key from a response body that may not be a dict at all."""
    return payload.get(key, default) if isinstance(payload, dict) else default


def check(name, got, expect, detail=""):
    ok = got in expect if isinstance(expect, tuple) else got == expect
    RESULTS.append((ok, name, got, expect, str(detail)))
    label = "PASS" if ok else "FAIL"
    suffix = f" :: {detail}" if detail else ""
    print(f"{label}  {str(got):<6} {name}{suffix}")
    return ok


def skip(name, reason):
    """A check that could not run. Counted as a failure: a skipped assertion
    proves nothing and must not read as a pass."""
    RESULTS.append((False, name, "SKIPPED", "to run", reason))
    print(f"SKIP  {'-':<6} {name} :: {reason}")


def _check_file_download(staff, respondent, file_id, plaintext: bytes) -> None:
    """Staff can fetch an uploaded file, and only with the PII capability."""
    path = f"/api/v1/files/{file_id}/download/"
    code, body, headers = staff.call("GET", path, raw=True)
    check("GET download the file as a PII holder", code, 200)
    check("  download returns the plaintext", body == plaintext, True, len(body))
    check(
        "  download is a neutral attachment",
        headers.get("Content-Type") == "application/octet-stream"
        and headers.get("X-Content-Type-Options") == "nosniff"
        and "attachment" in (headers.get("Content-Disposition") or ""),
        True,
    )

    # The respondent who uploaded it has no staff token, and a file is PII.
    code, _, _ = respondent.call("GET", path)
    check("GET download without a token is refused", code, 401)


def _analyst_user_id() -> int:
    """The seeded analyst's primary key."""
    from django.contrib.auth import get_user_model

    return get_user_model().objects.get(username="demo-analyst").pk


def reset_rate_limits() -> None:
    """Clear only the throttle counters, so the walk is repeatable."""
    from django.core.cache import cache

    # DRF stores one key per (scope, ident); the idents are unknown here, so
    # delete through the client by pattern where the backend allows it and
    # fall back to a full clear only if it does not.
    try:
        client = cache._cache.get_client()  # noqa: SLF001 - no public API for this
        prefix = cache.key_prefix
        for key in client.scan_iter(match=f"*throttle_*{prefix}*") or []:
            client.delete(key)
        for key in client.scan_iter(match="*throttle_*") or []:
            client.delete(key)
    except Exception:  # noqa: BLE001 - locmem and other backends
        cache.clear()


def main() -> int:  # noqa: PLR0915 - a linear walk reads better than helpers
    setup_django()
    reset_rate_limits()

    staff = Client()

    # --- authentication ------------------------------------------------------
    check("POST /auth/token/", staff.login("demo-admin", "demo-password"), 200)
    code, me, _ = staff.call("GET", "/api/v1/auth/whoami/")
    check("GET /auth/whoami/", code, 200, me.get("username", ""))

    wrong = Client()
    code, _, _ = wrong.call(
        "POST", "/api/v1/auth/token/", {"username": "demo-admin", "password": "wrong"}
    )
    check("POST /auth/token/ with a wrong password", code, 400)

    # --- documentation -------------------------------------------------------
    for path in ("/api/v1/schema/", "/api/v1/docs/", "/api/v1/redoc/"):
        code, _, _ = staff.call("GET", path, headers={"Accept": "text/html,*/*"}, raw=True)
        check(f"GET {path}", code, 200)

    # --- organizations and surveys -------------------------------------------
    code, orgs, _ = staff.call("GET", "/api/v1/organizations/")
    check("GET /organizations/", code, 200, f"{len(orgs)} org(s)")
    org_id = orgs[0]["id"]
    check("  reports the caller's role", orgs[0].get("role"), "admin")

    code, listing, _ = staff.call("GET", f"/api/v1/organizations/{org_id}/surveys/")
    check("GET /organizations/{id}/surveys/", code, 200, f"{len(listing)} survey(s)")
    # Picked by slug, not position. The listing has no ORDER BY, and every
    # run leaks one e2e-* survey into the org (its deletion is asserted to be
    # refused), so an index would start targeting a two-field throwaway on
    # the second run and report spurious encryption failures.
    seeded = next((row for row in listing if row["slug"] == "demo"), None)
    if seeded is None:
        print("\nNo survey with slug 'demo'. Run `make seed` first.")
        return 1
    seeded_survey = seeded["id"]

    slug = f"e2e-{uuid.uuid4().hex[:8]}"
    code, created, _ = staff.call(
        "POST", f"/api/v1/organizations/{org_id}/surveys/", {"name": "E2E", "slug": slug}
    )
    check("POST create survey", code, 201)
    survey_id = created["id"]

    code, _, _ = staff.call("GET", f"/api/v1/surveys/{survey_id}/")
    check("GET survey detail", code, 200)

    code, renamed, _ = staff.call(
        "PATCH", f"/api/v1/surveys/{survey_id}/", {"name": "E2E (renamed)"}
    )
    check("PATCH survey", code, 200, renamed.get("name", ""))

    code, clash, _ = staff.call(
        "POST", f"/api/v1/organizations/{org_id}/surveys/", {"name": "Clash", "slug": slug}
    )
    check("POST duplicate slug is a field error, not a 500", code, 400, str(clash)[:48])

    # --- builder --------------------------------------------------------------
    code, version, _ = staff.call("POST", f"/api/v1/surveys/{survey_id}/versions/")
    check("POST create version", code, 201, f"v{version.get('version_number')}")
    version_id = version["id"]

    q_country, q_city = str(uuid.uuid7()), str(uuid.uuid7())

    code, section, _ = staff.call(
        "POST",
        f"/api/v1/versions/{version_id}/sections/",
        {
            "key": "s1",
            "title": "Origin",
            "order": 1,
            "content": {
                q_country: {
                    "type": "dropdown",
                    "key": "country",
                    "label": "Country",
                    "required": True,
                    "options": [
                        {"value": "sa", "label": "Saudi Arabia"},
                        {"value": "eg", "label": "Egypt"},
                    ],
                }
            },
        },
    )
    check("POST create section", code, 201)
    section_id = section["id"]

    code, dupe, _ = staff.call(
        "POST",
        f"/api/v1/versions/{version_id}/sections/",
        {"key": "s1", "title": "Clash", "order": 9},
    )
    check("POST duplicate section key is a field error", code, 400, str(dupe)[:40])

    # A section gated on an answer from the previous one, with options that
    # are themselves filtered by that answer.
    q_cv = str(uuid.uuid7())
    code, _, _ = staff.call(
        "POST",
        f"/api/v1/versions/{version_id}/sections/",
        {
            "key": "s3",
            "title": "Attachment",
            "order": 3,
            "content": {
                q_cv: {"type": "file", "key": "cv", "label": "Your CV"},
            },
        },
    )
    check("POST create a file field", code, 201)

    code, _, _ = staff.call(
        "POST",
        f"/api/v1/versions/{version_id}/sections/",
        {
            "key": "s2",
            "title": "City",
            "order": 2,
            "content": {
                q_city: {
                    "type": "dropdown",
                    "key": "city",
                    "label": "City",
                    # Cross-section: the dependency is stated on the field,
                    # and because it is this section's only field, the whole
                    # section disappears with it.
                    "visible": {"all": [{"field": q_country, "op": "eq", "value": "sa"}]},
                    "options": [
                        {
                            "value": "riyadh",
                            "label": "Riyadh",
                            "when": {"all": [{"field": q_country, "op": "eq", "value": "sa"}]},
                        }
                    ],
                }
            },
        },
    )
    check("POST create cross-section conditional", code, 201)

    code, sections, _ = staff.call("GET", f"/api/v1/versions/{version_id}/sections/")
    check("GET sections", code, 200, f"{len(sections)}")

    code, _, _ = staff.call("PATCH", f"/api/v1/sections/{section_id}/", {"title": "Origin v2"})
    check("PATCH section while draft", code, 200)

    # --- publish ---------------------------------------------------------------
    code, published, _ = staff.call("POST", f"/api/v1/versions/{version_id}/publish/")
    order = published.get("schema", {}).get("eval_order", [])
    check("POST publish", code, 200, f"eval_order has {len(order)} fields")
    check("  dependency ordered", order.index(q_country) < order.index(q_city), True)

    code, _, _ = staff.call("PATCH", f"/api/v1/sections/{section_id}/", {"title": "sneaky"})
    check("PATCH section after publish is refused", code, 400)

    code, schema_body, _ = staff.call("GET", f"/api/v1/versions/{version_id}/")
    check("GET version schema", code, 200)
    check(
        "  returns the frozen document",
        bool(_get(schema_body, "schema", {}).get("fields")),
        True,
    )

    # --- publish rejects an invalid draft ---------------------------------------
    code, draft2, _ = staff.call("POST", f"/api/v1/surveys/{survey_id}/versions/")
    check("POST derive next draft", code, 201, f"v{draft2.get('version_number')}")
    staff.call(
        "POST",
        f"/api/v1/versions/{draft2['id']}/sections/",
        {"key": "bad", "title": "Bad", "order": 9, "content": {"not-a-uuid": {"type": "text"}}},
    )
    code, errors, _ = staff.call("POST", f"/api/v1/versions/{draft2['id']}/publish/")
    check("POST publish invalid draft is refused", code, 400, str(errors.get("errors"))[:55])

    # --- respondent journey ------------------------------------------------------
    respondent = Client()
    code, started, _ = respondent.call("POST", f"/api/v1/public/versions/{version_id}/submissions/")
    check("POST start submission (anonymous)", code, 201)
    submission_id = started["id"]
    respondent.headers["X-Resume-Token"] = started["resume_token"]
    url = f"/api/v1/public/submissions/{submission_id}/"

    code, state, _ = respondent.call("GET", url)
    check("GET submission state", code, 200)
    check("  dependent field starts hidden", state["visible"][q_city], False)
    check("  resume token is never echoed", "resume_token" not in state, True)

    code, state, _ = respondent.call("PATCH", url, {"answers": {q_country: "sa"}})
    check("PATCH autosave", code, 200)
    check("  dependent field becomes visible", state["visible"][q_city], True)
    check("  options filtered by the earlier answer", state["options"][q_city], ["riyadh"])

    code, rejected, _ = respondent.call("PATCH", url, {"answers": {q_country: "fr"}})
    check("PATCH undeclared option is refused", code, 400, str(rejected.get("errors"))[:40])

    code, _, _ = respondent.call("PATCH", url, {"answers": {q_city: "riyadh"}})
    check("PATCH dependent field", code, 200)

    # File answers are two-phase: upload, then answer with the returned id.
    boundary = "----e2e"
    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="field_id"\r\n\r\n{q_cv}\r\n'
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="cv.pdf"\r\n'
        f"Content-Type: application/pdf\r\n\r\n{PDF_BYTES.decode()}\r\n"
        f"--{boundary}--\r\n"
    ).encode()

    code, uploaded, _ = respondent.raw_post(
        f"/api/v1/public/submissions/{submission_id}/files/",
        body,
        f"multipart/form-data; boundary={boundary}",
    )
    check("POST upload a file", code, 201, _get(uploaded, "original_name"))
    # Only on a successful upload: "storage_key not in body" is true of every
    # error response too, so an unconditional check would pass for a 400.
    if code == 201:
        check("  storage key is not exposed", "storage_key" in uploaded, False)
        code, _, _ = respondent.call("PATCH", url, {"answers": {q_cv: uploaded["id"]}})
        check("PATCH answer with the upload id", code, 200)
        _check_file_download(staff, respondent, uploaded["id"], PDF_BYTES)
    else:
        skip("  storage key is not exposed", "upload did not succeed")
        skip("PATCH answer with the upload id", "upload did not succeed")
        for name in (
            "GET download the file as a PII holder",
            "  download returns the plaintext",
            "  download is a neutral attachment",
            "GET download without a token is refused",
        ):
            skip(name, "upload did not succeed")

    code, refused, _ = respondent.call("PATCH", url, {"answers": {q_cv: str(uuid.uuid7())}})
    check(
        "PATCH an upload id that does not exist is refused",
        code,
        400,
        str(refused.get("errors", ""))[:45],
    )

    code, done, _ = respondent.call("POST", f"{url}submit/", {"answers": {}})
    check("POST submit", code, 200, done.get("status", ""))

    code, _, _ = respondent.call("GET", url)
    check("GET after submit is refused (token cleared)", code, 403)

    # --- respondent authentication negatives --------------------------------------
    stranger = Client()
    code, _, response_headers = stranger.call("GET", url)
    check("GET submission with no token", code, 403)
    check(
        "  does not advertise the staff auth scheme", "WWW-Authenticate" in response_headers, False
    )

    stranger.headers["X-Resume-Token"] = "not-the-token"
    code, _, _ = stranger.call("GET", url)
    check("GET submission with a wrong token", code, 403)

    # --- analytics -------------------------------------------------------------------
    # A second respondent who answers "eg", so the city section never opens
    # for them. Without this the eligibility check cannot fail: one
    # respondent who DID see the field gives eligible=1 whether the
    # denominator is correct or naive.
    second = Client()
    _, other, _ = second.call("POST", f"/api/v1/public/versions/{version_id}/submissions/")
    second.headers["X-Resume-Token"] = other["resume_token"]
    second.call(
        "PATCH",
        f"/api/v1/public/submissions/{other['id']}/",
        {"answers": {q_country: "eg"}},
    )
    second.call("POST", f"/api/v1/public/submissions/{other['id']}/submit/", {"answers": {}})

    code, results, _ = staff.call("GET", f"/api/v1/versions/{version_id}/results/")
    check("GET version results", code, 200, f"started={results['funnel']['started']}")
    check("  funnel counts both respondents", results["funnel"]["completed"], 2)
    city = next(f for f in results["fields"] if f["field_id"] == q_city)
    # Two completions, but only one was ever shown the city question. A naive
    # denominator would report 2 here.
    check("  eligible excludes respondents never shown the field", city["eligible"], 1)
    check("  the other respondent still counted overall", city["answered"], 1)

    code, seeded_results, _ = staff.call("GET", f"/api/v1/surveys/{seeded_survey}/results/")
    check(
        "GET survey results",
        code,
        200,
        f"{seeded_results['funnel']['completed']} completed",
    )
    encrypted = [f for f in seeded_results["fields"] if not f["distribution_available"]]
    check(
        "  encrypted field explains its missing distribution",
        len(encrypted),
        1,
        encrypted[0]["reason"][:40] if encrypted else "",
    )

    code, submissions, _ = staff.call("GET", f"/api/v1/versions/{version_id}/submissions/")
    check("GET submission list", code, 200, f"{len(submissions)}")
    check("  no resume token leaked to staff", "resume_token" in json.dumps(submissions), False)

    code, versions, _ = staff.call("GET", f"/api/v1/surveys/{seeded_survey}/versions/")
    # Highest PUBLISHED version. The list comes back ascending, so [0] is v1
    # forever and would silently retarget a stale version -- or a draft --
    # the moment the demo survey gains a second one.
    published_versions = [v for v in versions if v["status"] == "published"]
    if not published_versions:
        print("\nSeeded survey has no published version.")
        return 1
    seeded_version = max(published_versions, key=lambda v: v["version_number"])["id"]
    code, seeded_subs, _ = staff.call("GET", f"/api/v1/versions/{seeded_version}/submissions/")
    check("GET seeded submission list", code, 200, f"{len(seeded_subs)}")

    # Create our own response on the seeded survey that definitely answers
    # the encrypted field, rather than hoping one of the existing rows does.
    # Other harness runs add submissions to this version answering only a
    # field or two, so sampling the list tests whichever response happened
    # to land last.
    code, seeded_schema, _ = staff.call("GET", f"/api/v1/versions/{seeded_version}/")
    fields = seeded_schema["schema"]["fields"]
    by_key = {d.get("key"): fid for fid, d in fields.items()}

    pii_respondent = Client()
    _, pii_started, _ = pii_respondent.call(
        "POST", f"/api/v1/public/versions/{seeded_version}/submissions/"
    )
    pii_respondent.headers["X-Resume-Token"] = pii_started["resume_token"]
    pii_respondent.call(
        "POST",
        f"/api/v1/public/submissions/{pii_started['id']}/submit/",
        {
            "answers": {
                by_key["country"]: "eg",
                by_key["nps"]: 9,
                by_key["national_id"]: "4242424242",
            }
        },
    )

    code, answers, _ = staff.call("GET", f"/api/v1/submissions/{pii_started['id']}/answers/")
    check("GET one response (decrypted for a PII holder)", code, 200)
    check(
        "  national id came back in clear",
        answers["answers"].get(by_key["national_id"]),
        "4242424242",
    )

    # --- exports -----------------------------------------------------------------------
    code, export, _ = staff.call("POST", f"/api/v1/versions/{seeded_version}/exports/")
    check("POST request export", code, 201, export.get("status", ""))
    check("  include_pii follows the requester's capability", export.get("include_pii"), True)

    import time

    row = None
    for _ in range(40):
        code, exports, _ = staff.call("GET", f"/api/v1/versions/{seeded_version}/exports/")
        row = next((e for e in exports if e["id"] == export["id"]), None)
        if row and row["status"] in ("ready", "failed"):
            break
        time.sleep(1)

    if row and row["status"] == "ready":
        check(
            "export processed by the celery worker",
            row["status"],
            "ready",
            f"rows={row.get('row_count')}",
        )
        code, csv_bytes, headers = staff.call(
            "GET", f"/api/v1/exports/{export['id']}/download/", raw=True
        )
        check("GET download export", code, 200, headers.get("Content-Type", ""))
        text = csv_bytes.decode()
        check(
            "  csv has a header and rows",
            len(text.strip().splitlines()) >= 2,
            True,
            f"{len(text.strip().splitlines())} lines",
        )
        check(
            "  decrypted values present in a PII export", bool(re.search(r"\b\d{10}\b", text)), True
        )
    else:
        check(
            "export processed by the celery worker",
            row["status"] if row else "pending",
            "ready",
            "is `make worker` running?",
        )
        skip("GET download export", "export never became ready")
        skip("  csv has a header and rows", "export never became ready")
        skip("  decrypted values present in a PII export", "export never became ready")

    # --- authorisation ----------------------------------------------------------------
    analyst = Client()
    check("POST /auth/token/ as demo-analyst", analyst.login("demo-analyst", "demo-password"), 200)

    code, _, _ = analyst.call("GET", f"/api/v1/versions/{seeded_version}/results/")
    check("analyst reads results of a granted survey", code, 200)

    code, _, _ = analyst.call("GET", f"/api/v1/surveys/{survey_id}/")
    check("analyst cannot see an ungranted survey (404, not 403)", code, 404)

    # --- grants -------------------------------------------------------------
    # demo-admin is an org ADMIN, which holds ACCESS_GRANT but not
    # MEMBER_MANAGE, so this exercises both sides of the owner/admin split.
    code, listed, _ = staff.call("GET", f"/api/v1/surveys/{survey_id}/access/")
    check("GET grants on a survey", code, 200)

    code, refused, _ = staff.call(
        "POST",
        f"/api/v1/surveys/{survey_id}/access/",
        {"user": 999_999_999, "role": "analyst"},
    )
    check("POST grant to a user that does not exist is refused", code, 400)

    analyst_id = _analyst_user_id()
    code, granted, _ = staff.call(
        "POST",
        f"/api/v1/surveys/{survey_id}/access/",
        {"user": analyst_id, "role": "analyst"},
    )
    check("POST grant the analyst access", code, 201)

    code, _, _ = analyst.call("GET", f"/api/v1/surveys/{survey_id}/")
    check("  the grant makes the survey visible", code, 200)

    if code == 200:
        code, _, _ = staff.call("DELETE", f"/api/v1/access/{_get(granted, 'id')}/")
        check("DELETE revoke the grant", code, 204)
        code, _, _ = analyst.call("GET", f"/api/v1/surveys/{survey_id}/")
        check("  revoking restores the 404", code, 404)
    else:
        skip("DELETE revoke the grant", "the grant did not take effect")
        skip("  revoking restores the 404", "the grant did not take effect")

    # MEMBER_MANAGE separates owner from admin, and nothing else does.
    code, _, _ = staff.call("GET", f"/api/v1/organizations/{org_id}/members/")
    check("an admin cannot manage members (owner only)", code, 403)

    owner = Client()
    check("POST /auth/token/ as demo-owner", owner.login("demo-owner", "demo-password"), 200)
    code, members, _ = owner.call("GET", f"/api/v1/organizations/{org_id}/members/")
    check("an owner can manage members", code, 200, f"{len(members)} member(s)")

    mine = next((m for m in members if m.get("role") == "owner"), None) if code == 200 else None
    if mine:
        code, _, _ = owner.call("DELETE", f"/api/v1/members/{mine['id']}/")
        check("the only owner cannot remove themselves", code, 400)
    else:
        skip("the only owner cannot remove themselves", "owner membership not listed")

    code, _, _ = analyst.call(
        "POST", f"/api/v1/organizations/{org_id}/surveys/", {"name": "no", "slug": "no"}
    )
    check("analyst cannot create a survey", code, 403)

    anonymous = Client()
    code, _, _ = anonymous.call("GET", "/api/v1/organizations/")
    check("anonymous blocked from the staff API", code, (401, 403))

    code, _, _ = staff.call("GET", f"/api/v1/surveys/{uuid.uuid7()}/")
    check("unknown survey id is 404", code, 404)

    # --- deletion ----------------------------------------------------------------------
    code, _, _ = staff.call("DELETE", f"/api/v1/sections/{section_id}/")
    check("DELETE section of a published version is refused", code, 400)

    code, refused, _ = staff.call("DELETE", f"/api/v1/surveys/{survey_id}/")
    check(
        "DELETE survey holding responses is refused", code, 409, str(refused.get("errors", {}))[:45]
    )

    code, disposable, _ = staff.call(
        "POST",
        f"/api/v1/organizations/{org_id}/surveys/",
        {"name": "Disposable", "slug": f"disposable-{uuid.uuid4().hex[:8]}"},
    )
    code, _, _ = staff.call("DELETE", f"/api/v1/surveys/{disposable['id']}/")
    check("DELETE survey with no responses succeeds", code, 204)

    # --- token revocation ----------------------------------------------------------------
    code, _, _ = staff.call("POST", "/api/v1/auth/token/revoke/")
    check("POST /auth/token/revoke/", code, 204)
    code, _, _ = staff.call("GET", "/api/v1/auth/whoami/")
    check("revoked token stops working immediately", code, 401)

    # --- summary ---------------------------------------------------------------------------
    return summarise()


def summarise() -> int:
    failures = [r for r in RESULTS if not r[0]]
    print()
    print("=" * 72)
    print(f"{len(RESULTS) - len(failures)}/{len(RESULTS)} checks passed")

    # A guard that skips a block must not shrink the total into looking
    # clean. The expected count is pinned so a short run is itself a failure.
    short = len(RESULTS) < EXPECTED_CHECKS
    if short:
        print(
            f"INCOMPLETE: {len(RESULTS)} checks ran, {EXPECTED_CHECKS} expected. "
            "The walk did not finish."
        )

    if failures:
        print("\nFAILURES:")
        for _, name, got, expect, detail in failures:
            print(f"  {name}: got {got!r}, expected {expect!r} {detail}")
    return 1 if failures or short else 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception as crash:  # noqa: BLE001
        # One broken endpoint used to take the summary down with it, so a
        # single failure read as a total outage. Report what did run.
        import traceback

        print(f"\nWALK ABORTED: {type(crash).__name__}: {crash}")
        traceback.print_exc()
        summarise()
        raise SystemExit(1) from crash
