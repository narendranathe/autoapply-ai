import { colors } from "../lib/tokens";

export function MobileBanner() {
  return (
    <div
      className="flex flex-col items-center justify-center min-h-screen p-8 text-center"
      style={{ background: colors.obsidian }}
    >
      <h1
        className="text-2xl mb-4"
        style={{ color: colors.mercury, fontWeight: 700 }}
      >
        AutoApply
      </h1>
      <p className="text-sm mb-6" style={{ color: colors.muted }}>
        Open the Chrome extension for the full experience
      </p>
      <a
        href="https://chrome.google.com/webstore"
        target="_blank"
        rel="noreferrer"
        className="inline-block px-5 py-2.5 rounded-lg text-sm font-semibold no-underline"
        style={{
          background: colors.teal,
          color: colors.obsidian,
        }}
      >
        Get the extension
      </a>
    </div>
  );
}
