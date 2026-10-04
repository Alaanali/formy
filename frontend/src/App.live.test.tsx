/**
 * Integration against the REAL backend. No mocks anywhere.
 *
 * The unit suite proves the components behave correctly given a response
 * shape. This proves the shape is right: that the API client, the types, the
 * evaluator and the components agree with what Django actually sends. Those
 * are exactly the assumptions a mock cannot test, because the mock is
 * written from the same assumptions.
 *
 *   make run && make worker   (in ../sumbission)
 *   pnpm dev
 *   pnpm test:live
 */

import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { cleanup, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { LoginPage } from "@/auth/LoginPage";
import { AuthProvider } from "@/auth/AuthContext";
import { ResultsPage } from "@/staff/ResultsPage";
import { SurveysPage } from "@/staff/SurveysPage";
import { OrganizationsPage } from "@/staff/OrganizationsPage";
import { SurveyRunner } from "@/respondent/SurveyRunner";
import { auth, respondent, setStoredToken, staff } from "@/lib/api";
import { resolveVisibility, resolveRequired, visibleOptions } from "@/lib/logic";
import type { Organization, SurveyVersionWithSchema } from "@/lib/types";
import { renderAt } from "@/test/render";

let organization: Organization;
let version: SurveyVersionWithSchema;
let fieldByKey: Record<string, string>;

beforeAll(async () => {
  const token = await auth.login("demo-admin", "demo-password");
  setStoredToken(token.token);

  const organizations = await staff.organizations();
  organization = organizations.find((o) => o.slug === "demo-org") ?? organizations[0];

  const surveys = await staff.surveys(organization.id);
  const demo = surveys.find((s) => s.slug === "demo") ?? surveys[0];

  const versions = await staff.versions(demo.id);
  const published = versions
    .filter((v) => v.status === "published")
    .sort((a, b) => b.version_number - a.version_number)[0];

  version = await staff.version(published.id);
  fieldByKey = Object.fromEntries(
    Object.entries(version.schema.fields).map(([id, d]) => [d.key ?? id, id]),
  );
});

afterAll(() => {
  cleanup();
  setStoredToken(null);
});

describe("the API client agrees with what Django sends", () => {
  it("returns a schema shaped as the types declare", () => {
    expect(version.schema.eval_order.length).toBeGreaterThan(0);
    expect(Object.keys(version.schema.fields).length).toBeGreaterThan(0);
    expect(version.schema.sections.every((s) => typeof s.title === "string")).toBe(true);
  });

  it("orders eval_order by dependency, as publish computed it", () => {
    const order = version.schema.eval_order;
    const country = fieldByKey.country;
    const city = fieldByKey.city;

    // city's section is gated on country, so country must come first.
    expect(order.indexOf(country)).toBeLessThan(order.indexOf(city));
  });
});

describe("the client evaluator agrees with the live server", () => {
  it("resolves the same visibility the server does", async () => {
    const started = await respondent.start(version.id);

    const answers = { [fieldByKey.country]: "sa" };
    const serverState = await respondent.save(started.id, started.resume_token, answers);

    // The whole reason the client may evaluate locally.
    const local = resolveVisibility(version.schema, serverState.answers);
    expect(local).toEqual(serverState.visible);
  });

  it("resolves the same requiredness", async () => {
    const started = await respondent.start(version.id);
    const serverState = await respondent.save(started.id, started.resume_token, {
      [fieldByKey.country]: "sa",
      [fieldByKey.age]: 30,
    });

    const visible = resolveVisibility(version.schema, serverState.answers);
    const local = resolveRequired(version.schema, serverState.answers, visible);
    expect(local).toEqual(serverState.required);
  });

  it("filters options the same way", async () => {
    const started = await respondent.start(version.id);
    const serverState = await respondent.save(started.id, started.resume_token, {
      [fieldByKey.country]: "sa",
    });

    const visible = resolveVisibility(version.schema, serverState.answers);
    for (const [fieldId, expected] of Object.entries(serverState.options)) {
      const local = visibleOptions(
        version.schema.fields[fieldId],
        version.schema,
        serverState.answers,
        visible,
      ).map((o) => o.value);
      expect(local, `options for ${fieldId}`).toEqual(expected);
    }
  });
});

describe("the respondent flow against the live server", () => {
  it("renders, saves and submits a real survey", async () => {
    const user = userEvent.setup();
    const started = await respondent.start(version.id);

    renderAt(
      `/s/${started.id}?t=${encodeURIComponent(started.resume_token)}`,
      "/s/:submissionId",
      <SurveyRunner />,
    );

    const heading = await screen.findByRole("heading", { level: 1 });
    expect(heading).toHaveTextContent(/about you/i);

    // Answer the real first question.
    const country = await screen.findByLabelText(/country/i);
    await user.selectOptions(country, "sa");

    // The conditional section appears without a round trip.
    await waitFor(() =>
      expect(screen.getByText(/step 1 of 3/i)).toBeInTheDocument(),
    );

    // And the server agrees, once the autosave lands.
    await waitFor(
      async () => {
        const state = await respondent.state(started.id, started.resume_token);
        expect(state.answers[fieldByKey.country]).toBe("sa");
      },
      { timeout: 5000 },
    );
  });

  it("refuses an answer the logic has filtered away", async () => {
    const started = await respondent.start(version.id);
    await respondent.save(started.id, started.resume_token, {
      [fieldByKey.country]: "sa",
    });

    // Cairo is only offered when the country is Egypt.
    await expect(
      respondent.save(started.id, started.resume_token, {
        [fieldByKey.city]: "cairo",
      }),
    ).rejects.toThrow();
  });

  it("encrypts a sensitive answer and never echoes it back", async () => {
    const started = await respondent.start(version.id);
    await respondent.save(started.id, started.resume_token, {
      [fieldByKey.national_id]: "7777777777",
    });

    const state = await respondent.state(started.id, started.resume_token);
    expect(state.answers[fieldByKey.national_id]).toBeNull();
  });
});

describe("the staff flow against the live server", () => {
  it("lists real organizations", async () => {
    renderAt("/", "/", <AuthProvider><OrganizationsPage /></AuthProvider>);

    expect(await screen.findByText(/demo research/i)).toBeInTheDocument();
    cleanup();
  });

  it("lists real surveys for an organization", async () => {
    renderAt(
      `/organizations/${organization.id}/surveys`,
      "/organizations/:organizationId/surveys",
      <SurveysPage />,
    );

    expect(await screen.findByText(/customer experience/i)).toBeInTheDocument();
    cleanup();
  });

  it("renders real results with eligible-based percentages", async () => {
    renderAt(
      `/versions/${version.id}/results`,
      "/versions/:versionId/results",
      <ResultsPage />,
    );

    await screen.findByRole("heading", { name: /results/i });

    // The funnel tiles come from the live rollups.
    const started = await screen.findByText("Started");
    expect(started).toBeInTheDocument();

    // The encrypted field states why it has no distribution rather than
    // being silently absent. Matched on the explanation specifically: the
    // word "encrypted" also appears in the badge beside it.
    expect(
      await screen.findByText(/cannot be aggregated/i),
    ).toBeInTheDocument();
    cleanup();
  });

  it("reports eligible counts that differ from total submissions", async () => {
    const results = await staff.results(version.id);
    const city = results.fields.find((f) => f.field_id === fieldByKey.city);

    // Only Saudi respondents are ever shown the city question, so its
    // eligible count must be below the completed count.
    expect(city).toBeDefined();
    expect(city!.eligible).toBeLessThan(results.funnel.completed);
  });

  it("marks the encrypted field as having no distribution", async () => {
    const results = await staff.results(version.id);
    const nationalId = results.fields.find(
      (f) => f.field_id === fieldByKey.national_id,
    );

    expect(nationalId!.distribution_available).toBe(false);
    expect(nationalId!.answered).toBeGreaterThan(0);
  });
});

describe("authentication against the live server", () => {
  it("rejects a wrong password with the backend's own message", async () => {
    const user = userEvent.setup();
    setStoredToken(null);

    renderAt("/", "/", <AuthProvider><LoginPage /></AuthProvider>);

    await user.type(await screen.findByLabelText(/username/i), "demo-admin");
    await user.type(screen.getByLabelText(/password/i), "definitely-wrong");
    await user.click(screen.getByRole("button", { name: /sign in/i }));

    expect(await screen.findByRole("alert")).toHaveTextContent(/invalid credentials/i);
    cleanup();
  });

  it("signs in and reaches a protected endpoint", async () => {
    const user = userEvent.setup();
    setStoredToken(null);

    const { container } = renderAt("/", "/", <AuthProvider><LoginPage /></AuthProvider>);

    await user.type(await screen.findByLabelText(/username/i), "demo-admin");
    await user.type(screen.getByLabelText(/password/i), "demo-password");
    await user.click(within(container).getByRole("button", { name: /sign in/i }));

    await waitFor(async () => {
      const me = await auth.whoami();
      expect(me.username).toBe("demo-admin");
    });
    cleanup();
  });
});
