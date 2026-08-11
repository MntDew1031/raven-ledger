import type { Metadata, Viewport } from "next";
import { Fraunces, Inter } from "next/font/google";
import "./globals.css";

/**
 * Raven had no typeface of its own.
 *
 * The stylesheet asked for `"Avenir Next", Inter, sans-serif` and loaded
 * neither, so the whole application rendered in Avenir Next on a Mac and in
 * whatever the device happened to default to everywhere else — Roboto on
 * Android, Segoe on Windows. An identity that only exists on the designer's
 * own machine is not an identity.
 *
 * Both are self-hosted at build time by `next/font`, which matters twice over:
 * nothing is fetched from Google at runtime, so the strict CSP holds and no
 * visitor's address is handed to a third party.
 */
const display = Fraunces({
  subsets: ["latin"],
  display: "swap",
  variable: "--font-display",
  // Fraunces is variable on optical size, weight and "softness". Money wants
  // the low-contrast, softer end: engraved enough to have a voice, not so
  // sharp it starts to look like a wedding invitation. Axes may only be named
  // on the variable cut, so weight stays continuous rather than listed.
  axes: ["SOFT", "opsz"],
});

const body = Inter({
  subsets: ["latin"],
  display: "swap",
  variable: "--font-body",
});

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  // Without this, env(safe-area-inset-*) evaluates to zero and the mobile tab
  // bar sits underneath the home indicator — the safe-area padding in the
  // stylesheet was correct all along and simply had nothing to read.
  viewportFit: "cover",
  // Tints the browser and status bar to match the app's own surface, so an
  // installed Raven has no stripe of foreign colour at the top.
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#fbfaf7" },
    { media: "(prefers-color-scheme: dark)", color: "#0c0b10" },
  ],
};

export const metadata: Metadata = {
  title: {
    default: "Raven Ledger",
    template: "%s · Raven Ledger",
  },
  description:
    "A private, self-hosted household finance platform for budgeting, cash flow, accounts, and net worth.",
  icons: {
    icon: [
      { url: "/favicon.svg?v=black-feather", type: "image/svg+xml" },
      {
        url: "/icon-192.png?v=black-feather",
        sizes: "192x192",
        type: "image/png",
      },
    ],
    // The versioned URL matters on iOS, which otherwise keeps a prior home
    // screen icon long after the asset itself has changed.
    apple: "/apple-touch-icon.png?v=black-feather",
  },
  appleWebApp: {
    // iOS reads this rather than the manifest's `display`. Without it,
    // "Add to Home Screen" still opens inside Safari with its chrome.
    capable: true,
    title: "Raven",
    // The status bar sits over the app's own background, which is what lets
    // the header's colour run to the top of the screen.
    statusBarStyle: "black-translucent",
  },
  other: {
    // Next emits the modern `mobile-web-app-capable`, which only iOS 17.4 and
    // later honour. The Apple-prefixed name is what older iOS reads, and
    // without it "Add to Home Screen" opens inside Safari with its chrome —
    // which is the whole thing this is for.
    "apple-mobile-web-app-capable": "yes",
  },
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  const appearanceScript = `
    (() => {
      try {
        const preference = localStorage.getItem("raven-theme") || "system";
        const resolved = preference === "system"
          ? (matchMedia("(prefers-color-scheme: dark)").matches ? "midnight" : "light")
          : (preference === "aurora" ? "midnight" : preference);
        document.documentElement.dataset.theme = resolved;
        document.documentElement.dataset.themePreference =
          preference === "aurora" ? "midnight" : preference;
        document.documentElement.dataset.accent = "plum";
        document.documentElement.dataset.density =
          localStorage.getItem("raven-density") || "comfortable";
        document.documentElement.dataset.buttonStyle = "solid";
      } catch {}
    })();
  `;
  return (
    <html
      className={`${display.variable} ${body.variable}`}
      lang="en"
      suppressHydrationWarning
    >
      <head>
        <script dangerouslySetInnerHTML={{ __html: appearanceScript }} />
      </head>
      <body>{children}</body>
    </html>
  );
}
