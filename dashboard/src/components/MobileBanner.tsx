export function MobileBanner() {
  return (
    <div style={{
      minHeight: '100vh',
      background: '#0D0D0D',
      display: 'flex',
      flexDirection: 'column',
      alignItems: 'center',
      justifyContent: 'center',
      padding: 24,
      textAlign: 'center',
      gap: 16,
    }}>
      <h1 style={{ color: '#E8E8E8', fontSize: 28, fontWeight: 600, margin: 0 }}>MIRROR</h1>
      <p style={{ color: '#F5F0E8', maxWidth: 320, lineHeight: 1.6, margin: 0 }}>
        Open the Chrome extension for the full experience
      </p>
      <a
        href="https://chrome.google.com/webstore"
        target="_blank"
        rel="noopener noreferrer"
        style={{ color: '#00CED1', fontSize: 14 }}
      >
        Get the extension
      </a>
    </div>
  )
}
