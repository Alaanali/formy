/**
 * The property worth testing here is credential separation: a respondent's
 * resume token and a staff token are two different authorities, and mixing
 * them would let a signed-in operator act as the respondent.
 */

import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it } from "vitest";
import { HttpResponse, http } from "msw";
import { setupServer } from "msw/node";

import { ApiError, auth, getStoredToken, respondent, setStoredToken, staff } from "./api";

const seen: Array<{ url: string; auth: string | null; resume: string | null }> = [];

const server = setupServer(
  http.all("/api/v1/*", ({ request }) => {
    seen.push({
      url: new URL(request.url).pathname,
      auth: request.headers.get("Authorization"),
      resume: request.headers.get("X-Resume-Token"),
    });
    return HttpResponse.json({ ok: true });
  }),
);

beforeAll(() => server.listen());
afterEach(() => server.resetHandlers());
afterAll(() => server.close());
beforeEach(() => {
  seen.length = 0;
  setStoredToken(null);
});

describe("credential separation", () => {
  it("sends the staff token on staff calls", async () => {
    setStoredToken("staff-token");
    await staff.organizations();

    expect(seen[0].auth).toBe("Token staff-token");
  });

  it("sends only the resume token on respondent calls", async () => {
    setStoredToken("staff-token");
    await respondent.state("sub-1", "resume-token");

    // Sending both would let a signed-in operator silently act as the
    // respondent whose draft this is.
    expect(seen[0].resume).toBe("resume-token");
    expect(seen[0].auth).toBeNull();
  });

  it("starts a submission with no credentials at all", async () => {
    setStoredToken("staff-token");
    await respondent.start("version-1");

    expect(seen[0].auth).toBeNull();
    expect(seen[0].resume).toBeNull();
  });

  it("does not attach a token to the login call", async () => {
    setStoredToken("stale-token");
    await auth.login("alice", "pw");

    expect(seen[0].auth).toBeNull();
  });
});

describe("token storage", () => {
  it("round-trips through storage", () => {
    setStoredToken("abc");
    expect(getStoredToken()).toBe("abc");
    setStoredToken(null);
    expect(getStoredToken()).toBeNull();
  });

  it("treats unavailable storage as signed out rather than crashing", () => {
    const original = Object.getOwnPropertyDescriptor(window, "localStorage");
    Object.defineProperty(window, "localStorage", {
      configurable: true,
      get() {
        throw new Error("blocked");
      },
    });

    // Private browsing and blocked site data both do this, and the app must
    // still boot.
    expect(() => getStoredToken()).not.toThrow();
    expect(getStoredToken()).toBeNull();

    if (original) Object.defineProperty(window, "localStorage", original);
  });
});

describe("error handling", () => {
  it("exposes per-field messages from a validation failure", async () => {
    server.use(
      http.post("/api/v1/organizations/o1/surveys/", () =>
        HttpResponse.json({ slug: ["Already taken."] }, { status: 400 }),
      ),
    );

    await expect(staff.createSurvey("o1", { name: "x", slug: "y" })).rejects.toSatisfy(
      (error: unknown) =>
        error instanceof ApiError && error.forField("slug") === "Already taken.",
    );
  });

  it("unwraps the backend's `errors` envelope", async () => {
    server.use(
      http.post("/api/v1/versions/v1/publish/", () =>
        HttpResponse.json({ errors: ["Field id is not a valid UUID."] }, { status: 400 }),
      ),
    );

    try {
      await staff.publish("v1");
      expect.unreachable("should have thrown");
    } catch (error) {
      expect(error).toBeInstanceOf(ApiError);
      expect((error as ApiError).status).toBe(400);
    }
  });

  it("summarises a general error", async () => {
    server.use(
      http.delete("/api/v1/surveys/s1/", () =>
        HttpResponse.json(
          { errors: { __all__: ["Cannot delete: responses exist."] } },
          { status: 409 },
        ),
      ),
    );

    try {
      await staff.deleteSurvey("s1");
      expect.unreachable("should have thrown");
    } catch (error) {
      expect((error as ApiError).summary).toContain("Cannot delete");
    }
  });

  it("does not choke on a non-JSON error body", async () => {
    server.use(
      http.get("/api/v1/organizations/", () =>
        HttpResponse.text("<html>500</html>", { status: 500 }),
      ),
    );

    await expect(staff.organizations()).rejects.toBeInstanceOf(ApiError);
  });

  it("returns undefined for a 204 rather than failing to parse", async () => {
    server.use(
      http.post("/api/v1/auth/token/revoke/", () => new HttpResponse(null, { status: 204 })),
    );

    await expect(auth.revoke()).resolves.toBeUndefined();
  });
});
