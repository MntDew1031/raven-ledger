export function currency(value: number, compact = false) {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    notation: compact ? "compact" : "standard",
    maximumFractionDigits: compact ? 1 : 2,
  }).format(value);
}

export function percent(value: number) {
  return new Intl.NumberFormat("en-US", {
    style: "percent",
    maximumFractionDigits: 1,
  }).format(value);
}

export function monthLabel(value: string) {
  const [year, month] = value.slice(0, 7).split("-").map(Number);

  if (!year || !month || month < 1 || month > 12) {
    return value;
  }

  return new Intl.DateTimeFormat("en-US", { month: "short" }).format(
    new Date(year, month - 1, 15),
  );
}
