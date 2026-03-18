export function MobileBanner() {
  return (
    <div
      className="fixed inset-0 z-50 flex flex-col items-center justify-center p-8 text-center"
      style={{ background: "#0D0D0D" }}
    >
      <div style={{ fontSize: 32, marginBottom: 16 }}>
        <span style={{ color: "#00CED1", fontWeight: 600 }}>MIRROR</span>
      </div>
      <p style={{ color: "#E8E8E8", fontSize: 16, fontWeight: 500, marginBottom: 8 }}>
        Desktop experience required
      </p>
      <p style={{ color: "#666666", fontSize: 14, maxWidth: 300 }}>
        For the full career dashboard experience, open MIRROR on a desktop browser. On mobile, use the Chrome extension instead.
      </p>
    </div>
  );
}
