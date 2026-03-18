interface Props {
  message: string
  onRetry?: () => void
}

export function ErrorCard({ message, onRetry }: Props) {
  return (
    <div style={{
      borderLeft: '3px solid #FF6B35',
      padding: '12px 16px',
      background: 'rgba(255,107,53,0.08)',
      borderRadius: '0 6px 6px 0',
      color: '#F5F0E8',
    }}>
      <p style={{ margin: 0, fontSize: 14 }}>{message}</p>
      {onRetry && (
        <button
          onClick={onRetry}
          style={{ marginTop: 8, background: 'transparent', border: '1px solid #FF6B35', color: '#FF6B35', padding: '4px 12px', borderRadius: 4, cursor: 'pointer', fontSize: 13 }}
        >
          Retry
        </button>
      )}
    </div>
  )
}
