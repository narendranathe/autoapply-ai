import React, { useEffect, useState } from "react";
import type { Message, PageContext } from "../shared/types";
import { restoreClerkUserId } from "../shared/api";
import { initClerk } from "../shared/clerkConfig";
import ApplyMode from "./pages/ApplyMode";
import JobScout from "./pages/JobScout";

const LOGO = (
  <svg width="22" height="22" viewBox="0 0 24 24" fill="none">
    <path d="M12 2L3 7v10l9 5 9-5V7L12 2z" fill="#7c3aed" opacity="0.9" />
    <path d="M12 2L3 7l9 5 9-5-9-5z" fill="#a78bfa" />
    <path d="M3 17l9 5V12L3 7v10z" fill="#6d28d9" />
    <path d="M21 17l-9 5V12l9-5v10z" fill="#8b5cf6" />
  </svg>
);

const MODE_LABEL: Record<string, string> = {
  apply: "Apply Mode",
  scout: "Job Scout",
  idle: "Ready",
};

const MODE_COLOR: Record<string, string> = {
  apply: "#10b981",
  scout: "#f59e0b",
  idle: "#475569",
};

export default function App() {
  const [context, setContext] = useState<PageContext | null>(null);

  useEffect(() => {
    restoreClerkUserId().catch(console.error);
    initClerk().catch(console.error);
  }, []);

  useEffect(() => {
    chrome.runtime.sendMessage<Message>({ type: "GET_CONTEXT" }, (response: Message) => {
      if (response?.type === "CONTEXT_RESPONSE" && response.payload) {
        setContext(response.payload);
      }
    });
    const listener = (message: Message) => {
      if (message.type === "PAGE_CONTEXT_UPDATE") {
        setContext(message.payload);
      }
    };
    chrome.runtime.onMessage.addListener(listener);
    return () => chrome.runtime.onMessage.removeListener(listener);
  }, []);

  const mode = context?.mode ?? "idle";
  const modeLabel = MODE_LABEL[mode] ?? "Idle";
  const modeColor = MODE_COLOR[mode] ?? MODE_COLOR.idle;

  return (
    <div style={{
      display: "flex",
      flexDirection: "column",
      height: "100vh",
      background: "#0a0a14",
      color: "#e2e8f0",
      fontFamily: "'Inter', system-ui, -apple-system, sans-serif",
      fontSize: 13,
    }}>
      {/* Header */}
      <div style={{
        display: "flex",
        alignItems: "center",
        gap: 10,
        padding: "10px 14px",
        background: "linear-gradient(135deg, #0f0f1e 0%, #13111f 100%)",
        borderBottom: "1px solid #1f1f38",
        flexShrink: 0,
      }}>
        {LOGO}
        <span style={{ fontWeight: 700, fontSize: 14, color: "#c4b5fd", letterSpacing: "-0.01em" }}>
          AutoApply AI
        </span>
        <div style={{
          marginLeft: "auto",
          display: "flex",
          alignItems: "center",
          gap: 5,
          background: "#1a1a2e",
          borderRadius: 99,
          padding: "3px 10px",
          border: "1px solid #252540",
        }}>
          <div style={{ width: 6, height: 6, borderRadius: "50%", background: modeColor }} />
          <span style={{ fontSize: 11, color: "#94a3b8", fontWeight: 500 }}>{modeLabel}</span>
        </div>
      </div>

      {/* Body */}
      {!context || context.mode === "idle" ? (
        <IdleState />
      ) : context.mode === "apply" ? (
        <ApplyMode context={context} />
      ) : (
        <JobScout context={context} />
      )}
    </div>
  );
}

function IdleState() {
  return (
    <div style={{
      flex: 1,
      display: "flex",
      flexDirection: "column",
      alignItems: "center",
      justifyContent: "center",
      gap: 16,
      padding: "32px 24px",
      textAlign: "center",
    }}>
      {/* Animated icon */}
      <div style={{
        width: 64,
        height: 64,
        borderRadius: 16,
        background: "linear-gradient(135deg, #1e1335 0%, #1a1a2e 100%)",
        border: "1px solid #2d1b69",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        fontSize: 28,
      }}>
        🎯
      </div>
      <div>
        <div style={{ fontWeight: 600, fontSize: 15, color: "#f1f5f9", marginBottom: 8 }}>
          No active job page
        </div>
        <div style={{ fontSize: 12, color: "#64748b", lineHeight: 1.6 }}>
          Navigate to a job listing on Greenhouse,<br />
          Lever, Workday, LinkedIn, iCIMS, Taleo,<br />
          or 6 more ATS platforms — auto-activates.
        </div>
      </div>
      <div style={{
        display: "flex",
        flexDirection: "column",
        gap: 6,
        width: "100%",
        maxWidth: 200,
      }}>
        {["Greenhouse", "Lever", "Workday", "LinkedIn", "Indeed", "Ashby", "SmartRecruiters", "iCIMS", "Taleo", "BambooHR", "Jobvite"].map((site) => (
          <div key={site} style={{
            display: "flex",
            alignItems: "center",
            gap: 8,
            padding: "6px 12px",
            background: "#12121e",
            border: "1px solid #1f1f38",
            borderRadius: 8,
            fontSize: 12,
            color: "#64748b",
          }}>
            <div style={{ width: 6, height: 6, borderRadius: "50%", background: "#374151" }} />
            {site}
          </div>
        ))}
      </div>
    </div>
  );
}
