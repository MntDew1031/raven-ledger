/**
 * Making a bank descriptor readable.
 *
 * Feeds arrive as "SQ *BLUE BOTTLE COFFEE", "ZZQ8871 POS PURCHASE",
 * "AMZN Mktp US*2K4L9" and "TRADER JOE'S #219". Every screen in Raven shows
 * those verbatim, which makes a list of transactions read like a terminal log.
 *
 * **This is display only. The raw descriptor is never modified.** It is bank
 * data, it is what the household would see on a statement, and — more
 * practically — the matching that drives rules, merchant memory and duplicate
 * detection all key off the stored string. Cleaning it in the database would
 * silently change what those match against.
 *
 * The rules are deliberately conservative, because a wrong "tidy" name is
 * worse than an untidy right one: if a descriptor cannot be improved with
 * confidence, it is returned unchanged.
 */

// Processor and channel prefixes that carry no meaning for a person reading a
// list. `SQ *` is Square, `TST*` is Toast, `SP ` is Shopify, and so on.
const PREFIXES = [
  /^sq\s*\*\s*/i,
  /^tst\s*\*\s*/i,
  /^sp\s+/i,
  /^py\s*\*\s*/i,
  /^pp\s*\*\s*/i,
  /^paypal\s*\*\s*/i,
  /^chkcard\s+/i,
  /^pos\s+debit\s+/i,
  /^debit\s+card\s+purchase\s+/i,
  /^purchase\s+authorized\s+on\s+\d+\/\d+\s*/i,
  /^recurring\s+payment\s+authorized\s+on\s+\d+\/\d+\s*/i,
];

// Trailing noise: store numbers, order references, terminal ids, cities and
// state codes that the feed appends.
const SUFFIXES = [
  /\s+#\s*\d+$/,                       // TRADER JOE'S #219
  /\s+\*?\d{3,}$/,                     // ... 4429
  /\s*\*[a-z0-9]{4,}$/i,               // AMZN Mktp US*2K4L9
  /\s+[a-z]{2}\s*$/i,                  // trailing state code
  /\s+\d{3}-\d{3}-\d{4}$/,             // phone numbers
  /\s+(?:llc|inc|corp|co|ltd)\.?$/i,   // company suffixes
];

// Words that should never be title-cased into something silly.
const KEEP_UPPER = new Set([
  "usa", "us", "uk", "atm", "dmv", "irs", "hoa", "hvac", "llc", "inc",
  "amc", "cvs", "hbo", "ups", "usps", "att", "tv", "nyc", "la", "sf",
]);

const KEEP_LOWER = new Set(["and", "of", "the", "for", "at", "on", "in", "to"]);

/** A descriptor with no letters at all is a reference, not a name. */
function isOpaque(value: string): boolean {
  return !/[a-z]{3}/i.test(value);
}

function titleCase(value: string): string {
  const words = value.toLowerCase().split(/\s+/).filter(Boolean);
  return words
    .map((word, index) => {
      const bare = word.replace(/[^a-z0-9']/gi, "");
      if (KEEP_UPPER.has(bare)) return bare.toUpperCase();
      if (index > 0 && KEEP_LOWER.has(bare)) return bare;
      // Hyphenated and slashed names get each part capitalised.
      return word.replace(/([a-z])([a-z']*)/gi, (_, head: string, tail: string) =>
        head.toUpperCase() + tail,
      );
    })
    .join(" ");
}

/**
 * A readable name for a merchant, or the original if it cannot be improved.
 *
 * Returns the input untouched when the descriptor is opaque (`ZZQ8871 POS
 * PURCHASE`) or when cleaning would leave too little to identify it — showing
 * "Purchase" in place of a reference number would be worse than the reference.
 */
export function prettyMerchant(raw: string | null | undefined): string {
  const original = (raw ?? "").trim();
  if (!original) return "";

  // An already-mixed-case name from a good feed is left alone: "Blue Bottle
  // Coffee" does not need help, and title-casing it risks breaking a brand
  // that capitalises deliberately, like "eBay" or "iCloud".
  if (/[a-z]/.test(original) && /[A-Z]/.test(original)) {
    let tidy = original;
    for (const suffix of SUFFIXES) tidy = tidy.replace(suffix, "");
    tidy = tidy.trim();
    return tidy.length >= 3 ? tidy : original;
  }

  let value = original;
  for (const prefix of PREFIXES) value = value.replace(prefix, "");
  for (const suffix of SUFFIXES) value = value.replace(suffix, "");
  value = value.replace(/\s{2,}/g, " ").trim();

  // Too little left, or nothing pronounceable: the original is more use.
  if (value.length < 3 || isOpaque(value)) return original;

  return titleCase(value);
}
