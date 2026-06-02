import type { Config } from "tailwindcss";

// UI theme tokens — preserve exactly (PLAN.md §2 / ADR theme).
const config: Config = {
  content: [
    "./app/**/*.{js,ts,jsx,tsx,mdx}",
    "./components/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      colors: {
        bg: "#0a0b0d",
        card: "#12141a",
        border: "#21262d",
        muted: "#8b949e",
        text: "#e4e6ea",
        green: "#00d4a1",
        red: "#ff4757",
        yellow: "#ffd32a",
        blue: "#4a90e2",
      },
    },
  },
  plugins: [],
};
export default config;
