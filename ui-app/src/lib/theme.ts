export type Theme = "light" | "dark"

const KEY = "nathanbot-theme"

/** Stored theme, else OS preference. */
export function getTheme(): Theme {
  const stored = localStorage.getItem(KEY)
  if (stored === "light" || stored === "dark") return stored
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light"
}

/** Toggle the `dark` class on <html> (shadcn dark variant) and persist. */
export function applyTheme(theme: Theme) {
  document.documentElement.classList.toggle("dark", theme === "dark")
  localStorage.setItem(KEY, theme)
}
