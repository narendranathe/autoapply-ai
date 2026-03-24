import React, { useEffect, useState } from "react";
import type { Message, PageContext } from "../shared/types";
import { restoreClerkUserId } from "../shared/api";
import { initClerk } from "../shared/clerkConfig";
import ApplyMode from "./pages/ApplyMode";
import JobScout from "./pages/JobScout";

const LOGO = (
  <svg width="20" height="20" viewBox="0 0 24 24" fill="none">
    <path d="M12 2L3 7v10l9 5 9-5V7L12 2z" fill="#009688" opacity="0.9" />
    <path d="M12 2L3 7l9 5 9-5-9-5z" fill="#00c4b4" />
    <path d="M3 17l9 5V12L3 7v10z" fill="#00897b" />
    <path d="M21 17l-9 5V12l9-5v10z" fill="#00b8a9" />
  </svg>
);

const MODE_LABEL: Record<string, string> = {
  apply: "Apply Mode",
  scout: "Job Scout",
  idle: "Ready",
};

const MODE_COLOR: Record<string, string> = {
  apply: "#00c4b4",
  scout: "#8b5cf6",
  idle: "#5a6278",
};

const MODE_BG: Record<string, string> = {
  apply: "rgba(0,196,180,0.1)",
  scout: "rgba(139,92,246,0.1)",
  idle: "rgba(90,98,120,0.1)",
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
  const modeLabel = MODE_LABEL[mode] ?? "Ready";
  const modeColor = MODE_COLOR[mode] ?? MODE_COLOR.idle;
  const modeBg = MODE_BG[mode] ?? MODE_BG.idle;

  return (
    <div style={{
      display: "flex",
      flexDirection: "column",
      height: "100vh",
      background: "#0a0b0d",
      color: "#e0e4ef",
      fontFamily: "system-ui, -apple-system, sans-serif",
      fontSize: 13,
      WebkitFontSmoothing: "antialiased",
    }}>
      {/* Header */}
      <div style={{
        display: "flex",
        alignItems: "center",
        gap: 8,
        padding: "0 14px",
        height: 52,
        background: "rgba(10,11,13,0.97)",
        borderBottom: "1px solid rgba(255,255,255,0.06)",
        flexShrink: 0,
        backdropFilter: "blur(12px)",
      }}>
        {LOGO}
        <span style={{
          fontWeight: 700,
          fontSize: 14,
          color: "#e0e4ef",
          letterSpacing: "-0.01em",
        }}>
          AutoApply<span style={{ color: "#00c4b4" }}> AI</span>
        </span>
        <div style={{
          marginLeft: "auto",
          display: "flex",
          alignItems: "center",
          gap: 5,
          background: modeBg,
          borderRadius: 99,
          padding: "3px 10px 3px 7px",
          border: `1px solid ${modeColor}22`,
        }}>
          <div style={{
            width: 6,
            height: 6,
            borderRadius: "50%",
            background: modeColor,
            boxShadow: `0 0 6px ${modeColor}`,
          }} />
          <span style={{ fontSize: 11, color: modeColor, fontWeight: 600 }}>{modeLabel}</span>
        </div>
      </div>

      {/* Body */}
      <div style={{ flex: 1, overflow: "hidden", display: "flex", flexDirection: "column" }}>
        {!context || context.mode === "idle" ? (
          <IdleState />
        ) : context.mode === "apply" ? (
          <ApplyMode context={context} />
        ) : (
          <JobScout context={context} />
        )}
      </div>
    </div>
  );
}

function IdleState() {
  const platforms = ["Greenhouse", "Lever", "Workday", "LinkedIn", "Indeed", "Ashby", "SmartRecruiters", "iCIMS", "Taleo", "BambooHR", "Jobvite"];
  return (
    <div style={{
      flex: 1,
      display: "flex",
      flexDirection: "column",
      alignItems: "center",
      justifyContent: "center",
      gap: 20,
      padding: "32px 20px",
      textAlign: "center",
    }}>
      {/* Icon */}
      <div style={{
        width: 60,
        height: 60,
        borderRadius: 16,
        background: "rgba(0,196,180,0.08)",
        border: "1px solid rgba(0,196,180,0.2)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
      }}>
        <svg width="28" height="28" viewBox="0 0 24 24" fill="none">
          <path d="M12 2L3 7v10l9 5 9-5V7L12 2z" fill="#009688" opacity="0.9" />
          <path d="M12 2L3 7l9 5 9-5-9-5z" fill="#00c4b4" />
          <path d="M3 17l9 5V12L3 7v10z" fill="#00897b" />
          <path d="M21 17l-9 5V12l9-5v10z" fill="#00b8a9" />
        </svg>
      </div>

      <div>
        <div style={{ fontWeight: 700, fontSize: 15, color: "#e0e4ef", marginBottom: 8 }}>
          No active job page
        </div>
        <div style={{ fontSize: 12, color: "#5a6278", lineHeight: 1.6 }}>
          Navigate to a job listing and<br />AutoApply AI auto-activates
        </div>
      </div>

      {/* Platform grid */}
      <div style={{
        display: "grid",
        gridTemplateColumns: "1fr 1fr",
        gap: 5,
        width: "100%",
        maxWidth: 220,
      }}>
        {platforms.map((site, i) => (
          <div key={site} style={{
            display: "flex",
            alignItems: "center",
            gap: 6,
            padding: "5px 10px",
            background: "#111318",
            border: "1px solid rgba(255,255,255,0.06)",
            borderRadius: 7,
            fontSize: 11,
            color: "#8b92a8",
            animation: `fadeUp 200ms ${i * 30}ms both`,
          }}>
            <div style={{ width: 5, height: 5, borderRadius: "50%", background: "#00c4b4", opacity: 0.5 }} />
            {site}
          </div>
        ))}
      </div>
    </div>
  );
}
