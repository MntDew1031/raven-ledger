"use client";

import { type CSSProperties, useEffect, useState } from "react";
import { GitBranch, ListOrdered } from "lucide-react";
import { Layer, Rectangle, ResponsiveContainer, Sankey, Tooltip } from "recharts";
import { apiFetch } from "@/lib/api";
import { currency } from "@/lib/format";

type Node = { name: string; kind: string; color: string | null };
type Link = { source: number; target: number; value: number };

type CashFlow = {
  total_income: string;
  total_expenses: string;
  net_income: string;
  savings_rate: number;
  nodes: Node[];
  links: Link[];
};

// Raven's semantic colours: green is money kept, red is what leaves, orange is
// the discretionary middle. The diagram inherits that language rather than
// inventing a second one.
const TONE: Record<string, string> = {
  income: "var(--green)",
  hub: "var(--green)",
  savings: "var(--green)",
  group: "var(--red)",
  category: "var(--orange)",
};

// Below this a Sankey is unreadable: the bands collapse into slivers and the
// labels overlap into noise. A ranked list of the same flows is not a
// consolation prize — on a phone it is the better answer.
const SANKEY_MIN_WIDTH = 620;

function flowTone(node: Node) {
  if (node.color) return node.color;
  const name = node.name.toLowerCase();
  if (node.kind === "savings") return "var(--green)";
  if (
    name.includes("want") ||
    name.includes("subscription") ||
    name.includes("fun") ||
    name.includes("discretionary")
  ) {
    return "var(--orange)";
  }
  return TONE[node.kind] || "var(--muted)";
}

function MobileFlowDiagram({ data }: { data: CashFlow }) {
  const income = Number(data.total_income);
  const hub = data.nodes.findIndex((node) => node.kind === "hub");
  const branches = data.links
    .filter((link) => link.source === hub)
    .sort((left, right) => right.value - left.value);

  return (
    <div className="mobile-money-flow">
      <div className="mobile-flow-source">
        <span>Total income</span>
        <strong>{currency(income)}</strong>
      </div>
      <div aria-hidden="true" className="mobile-flow-stem" />
      <div className="mobile-flow-branches">
        {branches.map((link) => {
          const branch = data.nodes[link.target];
          const children = data.links
            .filter((candidate) => candidate.source === link.target)
            .sort((left, right) => right.value - left.value);
          const share = income > 0 ? (link.value / income) * 100 : 0;
          const style = {
            "--flow-color": flowTone(branch),
          } as CSSProperties;

          return (
            <details className="mobile-flow-branch" key={`${branch.kind}-${branch.name}`} style={style}>
              <summary>
                <span className="mobile-flow-title">
                  <i aria-hidden="true" />
                  <span>
                    <strong>{branch.name}</strong>
                    <small>{share.toFixed(1)}% of income</small>
                  </span>
                </span>
                <strong>{currency(link.value)}</strong>
                <span className="mobile-flow-meter" aria-hidden="true">
                  <i style={{ width: `${Math.min(Math.max(share, 1), 100)}%` }} />
                </span>
                {children.length > 0 && (
                  <small className="mobile-flow-disclosure">
                    {children.length} categor{children.length === 1 ? "y" : "ies"}
                  </small>
                )}
              </summary>
              {children.length > 0 && (
                <ul>
                  {children.map((child) => {
                    const category = data.nodes[child.target];
                    return (
                      <li key={`${branch.name}-${category.name}`}>
                        <span>{category.name}</span>
                        <strong>{currency(child.value)}</strong>
                      </li>
                    );
                  })}
                </ul>
              )}
            </details>
          );
        })}
      </div>
      <p className="mobile-flow-hint">Tap a branch to see its categories.</p>
    </div>
  );
}

function SankeyNode(props: {
  x?: number;
  y?: number;
  width?: number;
  height?: number;
  payload?: Node & { value: number };
  containerWidth?: number;
}) {
  const {
    x = 0,
    y = 0,
    width = 0,
    height = 0,
    payload,
    containerWidth = 0,
  } = props;
  if (!payload) return null;
  const toRight = x + width + 6 > containerWidth - 150;
  return (
    <Layer>
      <Rectangle
        x={x}
        y={y}
        width={width}
        height={height}
        fill={flowTone(payload)}
        fillOpacity={0.95}
        radius={[2, 2, 2, 2]}
      />
      {height > 12 && (
        <text
          x={toRight ? x - 8 : x + width + 8}
          y={y + height / 2}
          textAnchor={toRight ? "end" : "start"}
          dominantBaseline="middle"
          className="sankey-label"
        >
          <tspan>{payload.name}</tspan>
          <tspan dx={6} className="sankey-label-value">
            {currency(payload.value)}
          </tspan>
        </text>
      )}
    </Layer>
  );
}

export function CashFlowSankey({ start, end }: { start: string; end: string }) {
  const [data, setData] = useState<CashFlow | null>(null);
  const [error, setError] = useState("");
  // Start narrow. The old default of `true` meant that if measurement ever
  // failed the phone got the full Sankey — the worst outcome — rather than the
  // readable list.
  const [wide, setWide] = useState(false);
  const [shell, setShell] = useState<HTMLElement | null>(null);
  // On a narrow screen the ranked list is the default because it is genuinely
  // easier to read. But it is not what Alex asked for and does not look like
  // it — he reported the diagram as *missing*. So the choice is his, and the
  // control says the diagram exists even when the list is showing.
  const [forceChart, setForceChart] = useState(false);

  useEffect(() => {
    let cancelled = false;
    apiFetch<CashFlow>(`/reports/cash-flow-sankey?start=${start}&end=${end}`)
      .then((result) => {
        if (!cancelled) setData(result);
      })
      .catch((cause: unknown) => {
        if (!cancelled) {
          setError(
            cause instanceof Error ? cause.message : "Could not load cash flow",
          );
        }
      });
    return () => {
      cancelled = true;
    };
  }, [start, end]);

  // Measure the panel, not the window. What matters is how much room this
  // chart actually has — a viewport query gets that wrong inside any narrow
  // column, and reports nothing at all in embedded contexts where innerWidth
  // and matchMedia both come back empty.
  useEffect(() => {
    // A callback ref rather than a `useRef` with `[]` deps: the panel does not
    // exist on first render — the component returns null until its data
    // arrives — so an effect that ran once found nothing to observe and the
    // chart kept its initial width forever. That is why a phone was shown the
    // full diagram instead of the list.
    if (!shell) return;
    const observer = new ResizeObserver(([entry]) => {
      setWide(entry.contentRect.width >= SANKEY_MIN_WIDTH);
    });
    observer.observe(shell);
    return () => observer.disconnect();
  }, [shell]);

  if (error) return <p className="negative">{error}</p>;
  if (!data) return null;

  // Only the income total is needed here — it is the denominator for the
  // share-of-income bars in the narrow fallback.
  const income = Number(data.total_income);
  const empty = data.links.length === 0;

  const names = data.nodes.map((node) => node.name);
  const period = `${new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
  }).format(new Date(`${start}T12:00:00`))} – ${new Intl.DateTimeFormat(
    "en-US",
    { month: "short", day: "numeric", year: "numeric" },
  ).format(new Date(`${end}T12:00:00`))}`;

  return (
    <>
      {/* No summary cards here: the reports page already prints income,
          spending, net and savings rate below. Two identical rows on one
          screen is worse than none. */}
      <section
        aria-label="Where the money went"
        className="panel sankey-panel"
        ref={setShell}
      >
        <div className="settings-card-heading sankey-heading">
          <div>
            <p className="eyebrow">Cash flow</p>
            <h2>Where the money went</h2>
            <p className="subtle sankey-period">{period}</p>
          </div>
          {!empty && !wide && (
            <div
              className="segmented-control sankey-view-toggle"
              aria-label="How to show the cash flow"
            >
              <button
                aria-pressed={!forceChart}
                className={!forceChart ? "active" : ""}
                onClick={() => setForceChart(false)}
                type="button"
              >
                <ListOrdered size={13} /> List
              </button>
              <button
                aria-pressed={forceChart}
                className={forceChart ? "active" : ""}
                onClick={() => setForceChart(true)}
                type="button"
              >
                <GitBranch size={13} /> Diagram
              </button>
            </div>
          )}
        </div>

        {empty ? (
          <p className="subtle">
            No income or spending in this period yet.
          </p>
        ) : wide ? (
          <div className="sankey-canvas">
            <ResponsiveContainer
              height={420}
              width="100%"
            >
              <Sankey
                data={{ nodes: data.nodes, links: data.links }}
                iterations={64}
                link={{ stroke: "var(--muted)", strokeOpacity: 0.16 }}
                margin={{ top: 8, right: 150, bottom: 8, left: 8 }}
                node={<SankeyNode />}
                nodePadding={16}
              >
                <Tooltip
                  formatter={(value) => currency(Number(value))}
                  labelFormatter={() => ""}
                />
              </Sankey>
            </ResponsiveContainer>
          </div>
        ) : forceChart ? (
          <MobileFlowDiagram data={data} />
        ) : (
          // The same flows, ranked. A Sankey squeezed to 375px is a decoration;
          // this still answers "where did it go, biggest first".
          <ul className="sankey-fallback">
            {[...data.links]
              .filter((link) => names[link.source] === "Total income")
              .sort((left, right) => right.value - left.value)
              .map((link) => {
                const share = income > 0 ? (link.value / income) * 100 : 0;
                const name = names[link.target];
                return (
                  <li key={name}>
                    <div>
                      <strong>{name}</strong>
                      <span>{currency(link.value)}</span>
                    </div>
                    <div className="sankey-bar">
                      <span
                        style={{
                          width: `${Math.max(share, 1)}%`,
                          background:
                            flowTone(data.nodes[link.target]),
                        }}
                      />
                    </div>
                    <small>{share.toFixed(1)}% of income</small>
                  </li>
                );
              })}
          </ul>
        )}
      </section>
    </>
  );
}
