import { Link } from 'react-router-dom'

export default function NotFound() {
  return (
    <div style={{ minHeight: '100vh', background: '#0D0D0D', display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: 16, color: '#F5F0E8' }}>
      <h1 style={{ margin: 0, fontSize: 48, fontWeight: 600, color: '#E8E8E8' }}>404</h1>
      <p style={{ margin: 0, color: '#F5F0E8' }}>Page not found</p>
      <Link to="/" style={{ color: '#00CED1', textDecoration: 'none', fontSize: 14 }}>Back to Mirror</Link>
    </div>
  )
}
