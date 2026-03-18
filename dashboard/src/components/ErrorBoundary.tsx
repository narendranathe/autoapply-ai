import { Component } from 'react'
import type { ReactNode, ErrorInfo } from 'react'

interface Props { children: ReactNode }
interface State { hasError: boolean; error: Error | null }

export class ErrorBoundary extends Component<Props, State> {
  state: State = { hasError: false, error: null }

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error }
  }

  componentDidCatch(_error: Error, _info: ErrorInfo) {}

  render() {
    if (this.state.hasError) {
      return (
        <div style={{ minHeight: '100vh', background: '#0D0D0D', display: 'flex', alignItems: 'center', justifyContent: 'center', flexDirection: 'column', gap: 16, color: '#F5F0E8' }}>
          <h2 style={{ margin: 0 }}>Something went wrong</h2>
          <button
            onClick={() => { this.setState({ hasError: false, error: null }); window.location.reload() }}
            style={{ background: '#00CED1', color: '#0D0D0D', border: 'none', padding: '8px 20px', borderRadius: 6, cursor: 'pointer', fontWeight: 600 }}
          >
            Reload
          </button>
        </div>
      )
    }
    return this.props.children
  }
}
