import { Link } from "react-router-dom";
import { colors } from "../lib/tokens";

export default function DashboardNotFound() {
  return (
    <div
      className="flex flex-col items-center justify-center min-h-screen gap-4"
      style={{ background: colors.obsidian }}
    >
      <h1 className="text-5xl font-bold" style={{ color: colors.mercury }}>404</h1>
      <p className="text-sm" style={{ color: colors.muted }}>Page not found</p>
      <Link
        to="/"
        className="text-sm no-underline px-4 py-2 rounded-md"
        style={{ color: colors.teal }}
      >
        Back to Dashboard
      </Link>
    </div>
  );
}
