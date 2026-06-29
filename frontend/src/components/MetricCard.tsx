interface StatProps {
  value: number;
  label: string;
  highlight?: boolean;
}

function Stat({ value, label, highlight = false }: StatProps) {
  return (
    <div className={`card p-2.5 relative ${highlight ? 'border-[rgba(255,51,102,0.4)]' : ''}`}>
      <div className={`text-lg font-bold mono tabular-nums leading-none mb-1 ${
        highlight ? 'text-accent text-glow' : 'text-[#666666]'
      }`}>
        {value.toLocaleString()}
      </div>
      <div className="mono text-[8px] text-[#666666] uppercase tracking-wider">
        {label}
      </div>
      {highlight && (
        <div className="absolute top-1.5 right-1.5 w-1.5 h-1.5 bg-[#FF3366] rounded-full"
             style={{
               animation: 'pulse-shadow 2s ease-in-out infinite',
               boxShadow: '0 0 6px rgba(255,51,102,0.8)'
             }} />
      )}
    </div>
  );
}

export function MetricsPanel({ metrics }: { metrics: Record<string, number> }) {
  return (
    <div className="grid grid-cols-3 sm:grid-cols-6 gap-2">
      <Stat value={metrics.candidates || 0}      label="CANDIDATES" />
      <Stat value={metrics.deduped || 0}         label="UNIQUE" />
      <Stat value={metrics.live || 0}            label="LIVE" highlight />
      <Stat value={metrics.checker_rated || 0}   label="RATED" highlight />
      <Stat value={metrics.selected || 0}        label="SELECTED" highlight />
      <Stat value={metrics.countries || 0}       label="COUNTRIES" />
    </div>
  );
}

export function ProgressBar({ current, total }: { current: number; total: number }) {
  const pct = total > 0 ? Math.min((current / total) * 100, 100) : 0;

  return (
    <div className="space-y-1.5">
      <div className="flex justify-between mono text-[9px] text-[#999999]">
        <span>⛧ RITUAL_PROGRESS</span>
        <span className="tabular-nums text-[#FF3366]">
          [{current.toLocaleString()} / {total.toLocaleString()}]
        </span>
      </div>
      <div className="relative h-2.5 bg-black/80 border border-[rgba(204,0,0,0.3)] rounded-sm overflow-hidden">
        <div
          className="absolute inset-y-0 left-0 bg-gradient-to-r from-[#CC0000] via-[#FF3366] to-[#CC0000] transition-all duration-300"
          style={{ 
            width: `${pct}%`,
            boxShadow: '0 0 12px rgba(255,51,102,0.6)'
          }}
        />
        <div className="absolute inset-0 bg-[repeating-linear-gradient(90deg,transparent,transparent_5px,rgba(0,0,0,0.4)_5px,rgba(0,0,0,0.4)_10px)]" />
      </div>
    </div>
  );
}
