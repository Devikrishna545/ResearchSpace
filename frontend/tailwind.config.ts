import type { Config } from "tailwindcss";
import typography from "@tailwindcss/typography";

const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./features/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}", "./lib/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        white: "rgb(var(--color-surface) / <alpha-value>)",
        paper: "rgb(var(--color-paper) / <alpha-value>)",
        linen: "rgb(var(--color-linen) / <alpha-value>)",
        ink: "rgb(var(--color-ink) / <alpha-value>)",
        muted: "rgb(var(--color-muted) / <alpha-value>)",
        line: "rgb(var(--color-line) / <alpha-value>)",
        indigo: {
          DEFAULT: "rgb(var(--color-indigo) / <alpha-value>)",
          soft: "rgb(var(--color-indigo-soft) / <alpha-value>)",
          deep: "rgb(var(--color-indigo-deep) / <alpha-value>)"
        },
        emerald: {
          50: "rgb(var(--color-success-bg) / <alpha-value>)",
          200: "rgb(var(--color-success-line) / <alpha-value>)",
          700: "rgb(var(--color-success-ink) / <alpha-value>)"
        },
        sage: "rgb(var(--color-sage) / <alpha-value>)",
        amber: {
          DEFAULT: "rgb(var(--color-amber) / <alpha-value>)",
          50: "rgb(var(--color-warning-bg) / <alpha-value>)",
          300: "rgb(var(--color-warning-line) / <alpha-value>)"
        },
        rose: "rgb(var(--color-rose) / <alpha-value>)"
      },
      fontFamily: {
        sans: ["var(--font-ui)", "Inter", "ui-sans-serif", "system-ui"],
        serif: ["var(--font-serif)", "Georgia", "ui-serif", "serif"]
      },
      boxShadow: { soft: "0 18px 50px rgba(var(--shadow-rgb), 0.15)", card: "0 8px 26px rgba(var(--shadow-rgb), 0.1)" },
      borderRadius: { "2xl": "1.25rem", "3xl": "1.75rem" }
    }
  },
  plugins: [typography]
};
export default config;
