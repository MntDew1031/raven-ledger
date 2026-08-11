export type ThemePreference =
  | "system"
  | "light"
  | "parchment"
  | "dark"
  | "midnight"
  | "aurora";
export type AccentPreference =
  | "obsidian"
  | "green"
  | "orange"
  | "red"
  | "blue"
  | "plum";
export type DensityPreference = "comfortable" | "compact";

export type UserProfile = {
  id: string;
  email: string;
  display_name: string;
  avatar_url: string | null;
  avatar_size: number | null;
  theme: ThemePreference;
  accent: AccentPreference;
  density: DensityPreference;
  button_style: "iris" | "solid" | "flat" | "duotone" | "restrained";
  start_page: "/" | "/accounts" | "/transactions" | "/budgets" | "/reports";
  mfa_enabled: boolean;
};

export function resolveThemePreference(
  preference: ThemePreference,
  systemDark: boolean,
) {
  if (preference === "system") return systemDark ? "midnight" : "light";
  // Aurora was retired when the appearance system stopped letting decorative
  // colour compete with Raven's financial colour language. Preserve old
  // profiles by moving them to the closest atmospheric successor.
  if (preference === "aurora") return "midnight";
  return preference;
}

export function applyAppearance(
  profile: Pick<UserProfile, "theme" | "accent" | "density" | "button_style">,
) {
  const systemDark = window.matchMedia("(prefers-color-scheme: dark)").matches;
  const resolvedTheme = resolveThemePreference(profile.theme, systemDark);
  const savedTheme = profile.theme === "aurora" ? "midnight" : profile.theme;
  document.documentElement.dataset.theme = resolvedTheme;
  document.documentElement.dataset.themePreference = savedTheme;
  // Atmosphere is personal; meaning is shared. Plum is Raven's permanent
  // interaction colour, while green/red/orange remain financial signals.
  document.documentElement.dataset.accent = "plum";
  document.documentElement.dataset.density = profile.density;
  document.documentElement.dataset.buttonStyle = "solid";
  localStorage.setItem("raven-theme", savedTheme);
  localStorage.setItem("raven-accent", "plum");
  localStorage.setItem("raven-density", profile.density);
  localStorage.setItem("raven-button-style", "solid");
}
