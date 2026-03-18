import { FunnelBar } from "../components/FunnelBar";
import { KanbanBoard } from "../components/KanbanBoard";
import { colors } from "../lib/tokens";

export default function Applications() {
  return (
    <div
      style={{
        padding: "28px 32px",
        display: "flex",
        flexDirection: "column",
        height: "100%",
        overflow: "hidden",
      }}
    >
      <h1
        style={{
          fontSize: 22,
          fontWeight: 600,
          color: colors.mercury,
          marginBottom: 0,
          letterSpacing: "-0.3px",
        }}
      >
        Applications
      </h1>

      <FunnelBar />

      <div style={{ flex: 1, overflow: "hidden" }}>
        <KanbanBoard />
      </div>
    </div>
  );
}
