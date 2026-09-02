export function Skeleton({ w = '100%', h = 14, r = 8, style }) {
  return (
    <span
      className="skeleton"
      style={{ display: 'block', width: w, height: h, borderRadius: r, ...style }}
    />
  )
}

export function SkeletonRows({ count = 6, h = 52, gap = 8 }) {
  return (
    <div style={{ display: 'grid', gap }}>
      {Array.from({ length: count }).map((_, i) => (
        <Skeleton key={i} h={h} r={12} />
      ))}
    </div>
  )
}
