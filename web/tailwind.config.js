/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,jsx}"],
  theme: {
    extend: {
      fontFamily: {
        sans: [
          "Plus Jakarta Sans",
          "Noto Sans Devanagari",
          "Noto Sans Kannada",
          "system-ui",
          "sans-serif",
        ],
        mono: ["IBM Plex Mono", "ui-monospace", "monospace"],
      },
      colors: {
        // The patient palette. Deep forest teal reads as clinical-calm rather
        // than alarm; the ground is a warm paper white so a 6-inch phone in
        // sunlight does not glare.
        ink: {
          DEFAULT: "#12211d",
          soft: "#41544e",
          faint: "#7d918b",
        },
        paper: {
          DEFAULT: "#f7f5f0",
          card: "#ffffff",
          line: "#e5e1d8",
        },
        forest: {
          50: "#eaf3f0",
          100: "#cde3dc",
          300: "#7cb5a6",
          500: "#2f7d6b",
          600: "#236355",
          700: "#184b40",
          900: "#0f3d36",
        },
        // Tier colours are SEMANTIC and deliberately separate from the brand
        // accent. A tier must never be mistaken for decoration.
        tier: {
          low: "#4b7f6d",
          moderate: "#b4700f",
          high: "#a02a20",
        },
        // The clinician surface. Denser, cooler, lower luminance so tabular
        // data and severity stripes carry the eye instead of the chrome.
        slate: {
          950: "#0d1218",
          900: "#141b23",
          850: "#1b242e",
          800: "#232f3b",
          700: "#33424f",
        },
      },
      boxShadow: {
        card: "0 1px 2px rgba(18,33,29,.04), 0 8px 24px -12px rgba(18,33,29,.18)",
        lift: "0 2px 6px rgba(18,33,29,.06), 0 18px 40px -18px rgba(18,33,29,.28)",
      },
      borderRadius: {
        xl2: "1.25rem",
      },
    },
  },
  plugins: [],
};
