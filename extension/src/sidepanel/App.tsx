import React, { useEffect, useState } from "react";
import type { Message, PageContext } from "../shared/types";
import ApplyMode from "./pages/ApplyMode";
import JobScout from "./pages/JobScout";

const S = {
  root: {
    display: "flex",
    flexDirection: "column" as const,
    height: "100vh",
    background: "#0f0f1a",
    color: "#e2e8f0",
  },
  header: {
    padding: "12px 16px",
    borderBottom: "1px solid #1e1e3a",
    display: "flex",
    alignItems: "center",
    gap: 10,
    background: "#13131f",
  },
  logo: { fontSize: 20 },
  title: { fontWeight: 700, fontSize: 15, color: "#a78bfa" },
  badge: {
    marginLeft: "auto",
    fontSize: 11,
    background: "#1e1e3a",
    color: "#6b7280",
    padding: "2px 8px",
    borderRadius: 99,
  },
  idle: {
    flex: 1,
    display: "flex",
    flexDirection: "column" as const,
    alignItems: "center",
    justifyContent: "center",
    gap: 12,
    color: "#4b5563",
    padding: 24,
    textAlign: "center" as const,
  },
  idleIcon: { fontSize: 40 },
  idleText: { fontSize: 14, lineHeight: 1.5 },
};

export default function App() {
  const [context, setContext] = useState<PageContext | null>(null);

  // Ask background for current context on mount
  useEffect(() => {
    chrome.runtime.sendMessage<Message>({ type: "GET_CONTEXT" }, (response: Message) => {
      if (response?.type === "CONTEXT_RESPONSE" && response.payload) {
        setContext(response.payload);
      }
    });

    // Listen for live context updates
    const listener = (message: Message) => {
      if (message.type === "PAGE_CONTEXT_UPDATE") {
        setContext(message.payload);
      }
    };
    chrome.runtime.onMessage.addListener(listener);
    return () => chrome.runtime.onMessage.removeListener(listener);
  }, []);

  const modeLabel =
    context?.mode === "apply"
      ? "Apply Mode"
      : context?.mode === "scout"
      ? "Job Scout"
      : "Idle";

  return (
    <div style={S.root}>
      {/* Header */}
      <div style={S.header}>
        <span style={S.logo}>🎯</span>
        <span style={S.title}>AutoApply AI</span>
        <span style={S.badge}>{modeLabel}</span>
      </div>

      {/* Body */}
      {!context || context.mode === "idle" ? (
        <div style={S.idle}>
          <span style={S.idleIcon}>📄</span>
          <span style={S.idleText}>
            Navigate to a job listing or application page
            <br />
            and AutoApply AI will activate automatically.
          </span>
        </div>
      ) : context.mode === "apply" ? (
        <ApplyMode context={context} />
      ) : (
        <JobScout context={context} />
      )}
    </div>
  );
}
