import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: "#1a1f2e",
        parchment: "#f7f4ee",
        brass: "#b3873f",
        court: "#233043",
      },
      fontFamily: {
        serif: ["Georgia", "Cambria", "Times New Roman", "serif"],
        sans: ["ui-sans-serif", "system-ui", "Segoe UI", "sans-serif"],
      },
    },
  },
  plugins: [],
};

export default config;
