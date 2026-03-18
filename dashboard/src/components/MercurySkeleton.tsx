interface Props {
  width?: string | number
  height?: string | number
  borderRadius?: string | number
  className?: string
}

export function MercurySkeleton({ width = '100%', height = 20, borderRadius = 6, className = '' }: Props) {
  return (
    <div
      className={className}
      style={{
        width,
        height,
        borderRadius,
        background: 'linear-gradient(90deg, rgba(0,206,209,0.08) 25%, rgba(0,206,209,0.18) 50%, rgba(0,206,209,0.08) 75%)',
        backgroundSize: '200% 100%',
        animation: 'mercuryShimmer 1.5s infinite',
      }}
    />
  )
}
