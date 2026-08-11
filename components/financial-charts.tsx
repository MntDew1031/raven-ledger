"use client";

import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Pie,
  PieChart,
  ResponsiveContainer,
  Sankey,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { cashFlowData, netWorthHistory, sankeyData } from "@/lib/demo-data";
import { currency } from "@/lib/format";

const tooltipStyle = {
  background: "var(--panel)",
  border: "1px solid var(--line)",
  borderRadius: 12,
  boxShadow: "0 10px 30px rgba(24, 29, 25, .08)",
  color: "var(--ink)",
  fontSize: 12,
};

type NetWorthPoint = { month: string; value: number };
type CashFlowPoint = { month: string; income: number; spending: number };
type SankeyData = {
  nodes: { name: string }[];
  links: { source: number; target: number; value: number }[];
};

export function NetWorthChart({
  data = netWorthHistory,
}: {
  data?: NetWorthPoint[];
}) {
  if (!data.length) {
    return (
      <div className="chart-box">
        <div className="chart-empty">
          Net worth history begins when you add or sync an account.
        </div>
      </div>
    );
  }

  return (
    <div className="chart-box">
      <ResponsiveContainer width="100%" height="100%" minWidth={0}>
        <AreaChart data={data} margin={{ left: 8, right: 12, top: 8 }}>
          <defs>
            <linearGradient id="netWorthFill" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="#4f7b61" stopOpacity={0.32} />
              <stop offset="100%" stopColor="#4f7b61" stopOpacity={0} />
            </linearGradient>
          </defs>
          <CartesianGrid vertical={false} stroke="var(--line)" />
          <XAxis
            axisLine={false}
            dataKey="month"
            tick={{ fill: "var(--muted)", fontSize: 11 }}
            tickLine={false}
          />
          <YAxis
            axisLine={false}
            domain={["auto", "auto"]}
            tick={{ fill: "var(--muted)", fontSize: 11 }}
            tickFormatter={(value) =>
              `${Number(value) < 0 ? "-" : ""}$${Math.abs(Number(value) / 1000).toFixed(0)}k`
            }
            tickLine={false}
            width={42}
          />
          <Tooltip
            contentStyle={tooltipStyle}
            formatter={(value) => currency(Number(value))}
          />
          <Area
            dataKey="value"
            fill="url(#netWorthFill)"
            stroke="var(--green)"
            strokeWidth={3}
            type="monotone"
          />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}

export function CashFlowChart({
  data = cashFlowData,
}: {
  data?: CashFlowPoint[];
}) {
  if (!data.length) {
    return (
      <div className="cashflow-chart">
        <div className="chart-empty">
          Cash-flow reporting starts after transactions are imported.
        </div>
      </div>
    );
  }

  return (
    <div className="cashflow-chart">
      <ResponsiveContainer width="100%" height="100%" minWidth={0}>
        <BarChart data={data} barGap={4}>
          <CartesianGrid vertical={false} stroke="var(--line)" />
          <XAxis
            axisLine={false}
            dataKey="month"
            tick={{ fill: "var(--muted)", fontSize: 11 }}
            tickLine={false}
          />
          <YAxis hide />
          <Tooltip
            contentStyle={tooltipStyle}
            formatter={(value) => currency(Number(value))}
          />
          <Bar dataKey="income" fill="#8bb89b" radius={[5, 5, 0, 0]} />
          <Bar dataKey="spending" fill="#dd8b7f" radius={[5, 5, 0, 0]} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

export function SpendingSankey({
  data = sankeyData,
  emptyMessage = "Your spending flow appears after transactions are categorized.",
}: {
  data?: SankeyData;
  emptyMessage?: string;
}) {
  if (!data.links.length) {
    return (
      <div className="sankey-chart">
        <div className="chart-empty">{emptyMessage}</div>
      </div>
    );
  }

  return (
    <div className="sankey-chart" aria-label="Income flow Sankey diagram">
      <ResponsiveContainer width="100%" height="100%" minWidth={0}>
        <Sankey
          data={data}
          link={{ stroke: "var(--muted)", strokeOpacity: 0.16 }}
          node={{ fill: "var(--green)", stroke: "none" }}
          nodePadding={24}
          nodeWidth={12}
        >
          <Tooltip
            contentStyle={tooltipStyle}
            formatter={(value) => currency(Number(value))}
          />
        </Sankey>
      </ResponsiveContainer>
    </div>
  );
}

export function SpendingDonut({
  data = [],
}: {
  data?: { name: string; value: number; color: string }[];
}) {
  if (!data.length) {
    return (
      <div className="donut-chart">
        <div className="chart-empty">
          Categorized spending will appear here.
        </div>
      </div>
    );
  }
  return (
    <div className="donut-chart">
      <ResponsiveContainer width="100%" height="100%" minWidth={0}>
        <PieChart>
          <Pie
            cx="50%"
            cy="50%"
            data={data}
            dataKey="value"
            innerRadius={66}
            outerRadius={95}
            paddingAngle={3}
          >
            {data.map((item) => (
              <Cell fill={item.color} key={item.name} />
            ))}
          </Pie>
          <Tooltip
            contentStyle={tooltipStyle}
            formatter={(value) => currency(Number(value))}
          />
        </PieChart>
      </ResponsiveContainer>
    </div>
  );
}
