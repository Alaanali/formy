import { useEffect, useState } from "react";

type Choice = "system" | "light" | "dark";
const KEY = "survey-theme";

function stored(): Choice {
  try {
    const value = localStorage.getItem(KEY);
    return value === "light" || value === "dark" ? value : "system";
  } catch {
    // A private window or blocked site data. Follow the OS instead.
    return "system";
  }
}

function apply(choice: Choice) {
  const root = document.documentElement;
  if (choice === "system") root.removeAttribute("data-theme");
  else root.setAttribute("data-theme", choice);
}

/** Three states, not two: "system" has to stay reachable, or someone who
 *  clicks once can never get back to following their OS. */
export function ThemeToggle() {
  const [choice, setChoice] = useState<Choice>(stored);

  useEffect(() => {
    apply(choice);
    try {
      if (choice === "system") localStorage.removeItem(KEY);
      else localStorage.setItem(KEY, choice);
    } catch {
      // Not worth failing a render over.
    }
  }, [choice]);

  const next: Record<Choice, Choice> = { system: "light", light: "dark", dark: "system" };
  const label: Record<Choice, string> = {
    system: "Theme: follow system",
    light: "Theme: light",
    dark: "Theme: dark",
  };

  return (
    <button
      type="button"
      onClick={() => setChoice(next[choice])}
      title={label[choice]}
      aria-label={label[choice]}
      className="rounded-lg p-1.5 text-muted transition-colors hover:bg-line-soft hover:text-ink"
    >
      <Icon choice={choice} />
    </button>
  );
}

function Icon({ choice }: { choice: Choice }) {
  const common = { width: 16, height: 16, viewBox: "0 0 16 16", "aria-hidden": true } as const;

  if (choice === "dark") {
    return (
      <svg {...common} fill="currentColor">
        <path d="M6.2 1.4A6.6 6.6 0 0 0 8 14.6a6.6 6.6 0 0 0 6.2-4.3 5.2 5.2 0 0 1-8-5.9 6.7 6.7 0 0 1 0-3Z" />
      </svg>
    );
  }
  if (choice === "light") {
    return (
      <svg {...common} fill="currentColor">
        <circle cx="8" cy="8" r="3.2" />
        <path d="M8 .8v2M8 13.2v2M.8 8h2M13.2 8h2M2.9 2.9l1.4 1.4M11.7 11.7l1.4 1.4M13.1 2.9l-1.4 1.4M4.3 11.7l-1.4 1.4" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" />
      </svg>
    );
  }
  return (
    <svg {...common} fill="none" stroke="currentColor" strokeWidth="1.3">
      <rect x="1.2" y="2.6" width="13.6" height="9" rx="1.4" />
      <path d="M5.5 13.4h5" strokeLinecap="round" />
    </svg>
  );
}
