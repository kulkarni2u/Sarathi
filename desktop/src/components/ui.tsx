import { type ReactNode } from "react";
import { Badge } from "@radix-ui/themes";
import { type Tone } from "../mockData";

export function stateTone(value: string): Tone {
  if (["complete", "healthy", "online", "approved", "accepted", "valid", "active", "live"].includes(value)) {
    return value === "active" || value === "live" ? "active" : "healthy";
  }
  if (["warning", "pending", "queued", "waiting", "waiting_human", "dirty", "draft", "degraded"].includes(value)) {
    return value === "draft" ? "draft" : "warning";
  }
  if (["blocked", "offline", "rejected", "failed", "missing"].includes(value)) {
    return "blocked";
  }
  return "draft";
}

export function streamTone(state: string): "live" | "warn" | "bad" {
  if (state === "connected") return "live";
  if (state === "demo" || state === "connecting" || state === "polling") return "warn";
  return "bad";
}

function toneToRadixColor(tone: string): "green" | "blue" | "orange" | "red" | "violet" | "gray" | "indigo" {
  if (["healthy", "complete", "online", "approved", "accepted", "valid"].includes(tone)) return "green";
  if (["active", "live"].includes(tone)) return "indigo";
  if (["warning", "pending", "queued", "waiting", "waiting_human", "dirty", "degraded"].includes(tone)) return "orange";
  if (["blocked", "bad", "offline", "rejected", "failed", "missing"].includes(tone)) return "red";
  if (["draft"].includes(tone)) return "violet";
  return "gray";
}

export function Pill({ children, tone = "draft" }: { children: ReactNode; tone?: Tone | string }) {
  const color = toneToRadixColor(stateTone(tone));
  return <Badge color={color} variant="soft" radius="medium" size="1">{children}</Badge>;
}

export function Field({ label, value }: { label: string; value: string }) {
  return <div className="field"><span>{label}</span><strong>{value}</strong></div>;
}

export function Card({ children, style }: { children: ReactNode; style?: React.CSSProperties }) {
  return <div className="card" style={style}>{children}</div>;
}

export function PanelTitle({ title, badge }: { title: string; badge: string }) {
  return <div className="panel-title"><h2>{title}</h2><Pill tone={stateTone(badge)}>{badge}</Pill></div>;
}

export function StatusLine({ label, value, tone }: { label: string; value: string; tone: "live" | "warn" | "bad" }) {
  return <div className="status-line"><span><i className={`dot ${tone}`} />{label}</span><strong>{value}</strong></div>;
}

export function MessageBubble({ from, target, tag, text, impact }: { from: string; target: string; tag: string; text: string; impact: string }) {
  return <div className="message"><small>{from} to {target} / {tag} / {impact}</small><p>{text}</p></div>;
}
