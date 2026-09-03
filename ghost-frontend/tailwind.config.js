/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ["./src/**/*.{js,ts,jsx,tsx,mdx}"],
  theme: {
    extend: {
      colors: {
        // Matches the CSS custom properties in dashboard-base-v4.html
        // exactly -- do not introduce parallel color names here, this
        // file should always be re-derived from that mockup's :root
        // block if the palette ever changes there.
        bg: "#090908",
        surface: "#0e0e0c",
        "surface-hi": "#12120f",
        border: {
          DEFAULT: "#25231e",
          light: "#2b2b2b",
        },
        ghost: {
          text: "#ece8de",
          muted: "#706b62",
          dim: "#4d4b47",
        },
        status: {
          red: "#c95849",
          amber: "#c79b46",
          green: "#55bd78",
        },
        hud: {
          DEFAULT: "#5f7a7a",
          bright: "#9fc0c0",
        },
      },
      fontFamily: {
        mono: ["IBM Plex Mono", "monospace"],
        display: ["Inter", "sans-serif"],
        pixel: ["Press Start 2P", "monospace"],
      },
    },
  },
  plugins: [],
};