import { EngineStatus } from '../types';

const statusConfig: Record<EngineStatus, { label: string; color: string }> = {
  idle:      { label: '⛧ AWAITING RITUAL',      color: 'text-[#666666]' },
  running:   { label: '⚠ SUMMONING IN PROGRESS', color: 'text-[#FF3366]' },
  done:      { label: '✓ SOULS COLLECTED',       color: 'text-[#00ff66]' },
  error:     { label: '✗ RITUAL FAILED',         color: 'text-[#FF0033]' },
  cancelled: { label: '⊗ SUMMONING ABORTED',     color: 'text-[#666666]' },
};

export function StatusHeader({ status, message, reconnecting }: {
  status: EngineStatus;
  message?: string;
  reconnecting?: boolean;
}) {
  const cfg = statusConfig[status] ?? statusConfig.idle;
  const label = reconnecting ? '↻ RECONNECTING...' : cfg.label;
  const color = reconnecting ? 'text-[#FFAA00]' : cfg.color;
  const msg   = reconnecting ? (message || 'Ожидание соединения') : message;

  return (
    <div className="card flex items-center" style={{borderRadius: '6px', minHeight: '100%'}}>
      <div className="flex items-center justify-between px-3 py-2 w-full">
        <div className="flex items-center gap-2">
          <span className="mono text-[0.6rem] text-[#666666] select-none">root@abyss:~#</span>
          <span className={`mono text-[0.7rem] font-semibold ${color}`}>{label}</span>
        </div>
        {msg && (
          <span className="mono text-[0.6rem] text-[#FFAA00] max-w-md truncate hidden sm:block">
            → {msg}
          </span>
        )}
      </div>
    </div>
  );
}
