import type { MetadataRoute } from "next";

/**
 * Installable as an app.
 *
 * Alex only uses Raven on his phone, through the browser. Installed to the
 * home screen it launches without Safari's chrome — which is worth more than
 * it sounds, because that chrome is what was eating the bottom navigation and
 * forcing the safe-area work in 1.35.0 and 1.37.0.
 *
 * `standalone` rather than `fullscreen`: the status bar should stay, since a
 * finance app is something you check while doing something else and hiding the
 * clock and battery to gain 20px is a bad trade.
 */
export default function manifest(): MetadataRoute.Manifest {
  return {
    name: "Raven Ledger",
    short_name: "Raven",
    description:
      "A private household ledger: budgets, cash flow, accounts and net worth, on your own hardware.",
    start_url: "/",
    display: "standalone",
    orientation: "portrait",
    background_color: "#171c18",
    // Tints the status bar. The dark surface rather than the accent, so the
    // bar reads as part of the app rather than a stripe above it.
    theme_color: "#171c18",
    categories: ["finance", "productivity"],
    icons: [
      {
        src: "/icon-192.png?v=black-feather",
        sizes: "192x192",
        type: "image/png",
        purpose: "any",
      },
      {
        src: "/icon-512.png?v=black-feather",
        sizes: "512x512",
        type: "image/png",
        purpose: "any",
      },
      // Launchers crop to their own shape; these have the background running
      // to the edges so nothing important is lost to the crop.
      {
        src: "/icon-maskable-192.png?v=black-feather",
        sizes: "192x192",
        type: "image/png",
        purpose: "maskable",
      },
      {
        src: "/icon-maskable-512.png?v=black-feather",
        sizes: "512x512",
        type: "image/png",
        purpose: "maskable",
      },
    ],
    shortcuts: [
      { name: "Add a transaction", url: "/transactions?add=1" },
      { name: "Budget", url: "/budgets" },
      { name: "Ask Raven", url: "/assistant" },
    ],
  };
}
