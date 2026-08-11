type Props = {
  label: string;
  value: string;
  delta: string;
  tone: "green" | "red" | "orange" | "neutral";
};

export function MetricCard({ label, value, delta, tone }: Props) {
  return (
    <article className={`metric-card ${tone}`}>
      <span>{label}</span>
      <strong>{value}</strong>
      <small>{delta}</small>
    </article>
  );
}
