/**
 * The respondent flow end to end against a stand-in backend: conditional
 * logic reacting live, autosave, per-field errors from the server, and the
 * required check that gates each step.
 */

import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { SurveyRunner } from "./SurveyRunner";
import {
  FIELD,
  SUBMISSION_ID,
  TOKEN,
  reset,
  resetAnswers,
  saved,
  server,
  uploadsEnabled,
  wasSubmitted,
} from "@/test/server";
import { renderAt } from "@/test/render";

beforeAll(() => server.listen());
afterEach(() => server.resetHandlers());
afterAll(() => server.close());
beforeEach(() => {
  reset();
  resetAnswers();
});

function open(token = TOKEN) {
  return renderAt(`/s/${SUBMISSION_ID}?t=${token}`, "/s/:submissionId", <SurveyRunner />);
}

describe("loading", () => {
  it("shows the first section", async () => {
    open();
    expect(await screen.findByRole("heading", { level: 1 })).toHaveTextContent("About you");
  });

  it("refuses a wrong resume token with a plain explanation", async () => {
    open("wrong-token");
    expect(await screen.findByText(/no longer valid/i)).toBeInTheDocument();
  });
});

describe("conditional logic", () => {
  it("reveals a dependent section once its condition is met", async () => {
    const user = userEvent.setup();
    open();
    await screen.findByRole("heading", { level: 1 });

    // Step 1 of 3 while the Saudi-only section is hidden.
    expect(screen.getByText(/step 1 of 2/i)).toBeInTheDocument();

    await user.selectOptions(screen.getByLabelText(/country/i), "sa");

    // The extra section appears immediately, without waiting for a save.
    await waitFor(() => expect(screen.getByText(/step 1 of 3/i)).toBeInTheDocument());
  });

  it("hides it again when the answer changes back", async () => {
    const user = userEvent.setup();
    open();
    await screen.findByRole("heading", { level: 1 });

    await user.selectOptions(screen.getByLabelText(/country/i), "sa");
    await waitFor(() => expect(screen.getByText(/step 1 of 3/i)).toBeInTheDocument());

    await user.selectOptions(screen.getByLabelText(/country/i), "eg");
    await waitFor(() => expect(screen.getByText(/step 1 of 2/i)).toBeInTheDocument());
  });
});

describe("required fields", () => {
  it("blocks the step and names how many answers are outstanding", async () => {
    const user = userEvent.setup();
    open();
    await screen.findByRole("heading", { level: 1 });

    await user.click(screen.getByRole("button", { name: /continue/i }));

    expect(await screen.findByText(/still needs an answer/i)).toBeInTheDocument();
    expect(screen.getByText(/this question needs an answer/i)).toBeInTheDocument();
  });

  it("advances once the required answer is given", async () => {
    const user = userEvent.setup();
    open();
    await screen.findByRole("heading", { level: 1 });

    await user.selectOptions(screen.getByLabelText(/country/i), "eg");
    await user.click(screen.getByRole("button", { name: /continue/i }));

    await waitFor(() => expect(screen.getByText(/step 2 of 2/i)).toBeInTheDocument());
  });
});

describe("autosave", () => {
  it("sends the answer without being asked to", async () => {
    const user = userEvent.setup();
    open();
    await screen.findByRole("heading", { level: 1 });

    await user.selectOptions(screen.getByLabelText(/country/i), "sa");

    await waitFor(() => expect(saved.length).toBeGreaterThan(0), { timeout: 3000 });
    expect(saved[0]).toEqual({ [FIELD.country]: "sa" });
  });

  it("never sends an answer to a field the logic hides", async () => {
    const user = userEvent.setup();
    open();
    await screen.findByRole("heading", { level: 1 });

    await user.selectOptions(screen.getByLabelText(/country/i), "sa");
    await waitFor(() => expect(saved.length).toBeGreaterThan(0), { timeout: 3000 });

    // The server would discard such an answer anyway; sending it would only
    // muddy what the client is claiming.
    const everySent = saved.flatMap((batch) => Object.keys(batch));
    expect(everySent).not.toContain(FIELD.district);
  });

  it("shows a server validation error against the field it belongs to", async () => {
    const user = userEvent.setup();
    open();
    await screen.findByRole("heading", { level: 1 });

    await user.type(screen.getByLabelText(/age/i), "999");

    expect(await screen.findByText(/at most 120/i)).toBeInTheDocument();
  });
});

describe("submission", () => {
  it("submits on the last step and shows the completion page", async () => {
    const user = userEvent.setup();
    open();
    await screen.findByRole("heading", { level: 1 });

    await user.selectOptions(screen.getByLabelText(/country/i), "eg");
    await user.click(screen.getByRole("button", { name: /continue/i }));
    await waitFor(() => expect(screen.getByText(/step 2 of 2/i)).toBeInTheDocument());

    await user.click(screen.getByRole("button", { name: /submit/i }));

    // Assert the submission actually reached the server rather than a
    // render side effect: the click awaits a flush and then the submit, so
    // waiting on the DOM alone races two round trips.
    await waitFor(() => expect(wasSubmitted()).toBe(true), { timeout: 3000 });
    await waitFor(() =>
      expect(screen.getByText(/elsewhere|thank you/i)).toBeInTheDocument(),
    );
  });
});

describe("accessibility", () => {
  it("exposes progress to assistive technology", async () => {
    open();
    expect(await screen.findByRole("progressbar")).toBeInTheDocument();
  });
});


describe("file answers", () => {
  it("uploads on selection and answers with the returned id", async () => {
    const user = userEvent.setup();
    uploadsEnabled();
    open();
    await screen.findByRole("heading", { level: 1 });

    const file = new File(["%PDF-1.4"], "cv.pdf", { type: "application/pdf" });
    await user.upload(screen.getByLabelText(/attachment/i), file);

    // Uploaded immediately, not held until submit: the id becomes the
    // answer, so the file survives a closed tab and a retried submit.
    await waitFor(() => expect(screen.getByText("cv.pdf")).toBeInTheDocument());
    await waitFor(
      () => expect(saved.some((batch) => FIELD.attachment in batch)).toBe(true),
      { timeout: 3000 },
    );
  });

  it("shows the server's reason when an upload is refused", async () => {
    const user = userEvent.setup();
    uploadsEnabled({ reject: "application/pdf files are not accepted." });
    open();
    await screen.findByRole("heading", { level: 1 });

    const file = new File(["x"], "virus.pdf", { type: "application/pdf" });
    await user.upload(screen.getByLabelText(/attachment/i), file);

    // The backend states exactly why -- wrong type, too large, wrong field
    // -- and that is more useful than a generic failure.
    expect(await screen.findByText(/are not accepted/i)).toBeInTheDocument();
  });
})
