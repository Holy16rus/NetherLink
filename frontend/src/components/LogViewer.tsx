import { useEffect, useRef } from 'react';
import { Terminal } from 'lucide-react';

export interface LogEntry {
  id: number;
  text: string;
  level?: string;
  time: number;
}

const levelStyle: Record<string, string> = {
  error: 'text-[#FF3366]',
  warn:  'text-[#FFA500]',
  info:  'text-[#00ff66]',
};

export function LogViewer({ logs }: { logs: LogEntry[] }) {
  const containerRef = useRef<HTMLDivElement>(null);
  const autoScrollRef = useRef(true);
  const bottomRef = useRef<HTMLDivElement>(null);

  const onScroll = () => {
    const el = containerRef.current;
    if (!el) return;
    autoScrollRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < 40;
  };

  useEffect(() => {
    if (autoScrollRef.current) {
      bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
    }
  }, [logs.length]);

  return (
    <div className="card flex flex-col" style={{borderRadius: '6px', maxHeight: '280px'}}>
      <div className="px-3 py-2 border-b border-[rgba(204,0,0,0.3)] flex items-center justify-between shrink-0">
        <div className="flex items-center gap-1.5">
          <Terminal className="w-3.5 h-3.5 text-[#FF3366]" />
          <span className="cyber-text text-xs text-[#cccccc]">⛧ LOGS</span>
        </div>
        <span className="mono text-[9px] text-[#666666]">
          [{logs.length}]
        </span>
      </div>

      <div
        ref={containerRef}
        onScroll={onScroll}
        className="terminal flex-1 min-h-0 px-3 py-2 overflow-y-auto text-xs leading-relaxed"
      >
        {logs.length === 0 ? (
          <div className="text-[#666666] text-center py-10 mono">
            <div className="mb-2 text-[#CC0000] text-lg">💀</div>
            &gt; Awaiting souls...
          </div>
        ) : (
          logs.map(log => (
            <div key={log.id} className="flex gap-2 font-['Source_Code_Pro',monospace] hover:bg-[rgba(204,0,0,0.05)] px-2 py-0.5 -mx-2 rounded transition-colors">
              <span className="text-[#666666] shrink-0 select-none tabular-nums text-[10px]">
                [{new Date(log.time * 1000).toLocaleTimeString()}]
              </span>
              <span className={levelStyle[log.level ?? 'info'] ?? levelStyle.info}>
                {log.text}
              </span>
            </div>
          ))
        )}
        <div ref={bottomRef} />
      </div>

      <div className="terminal px-3 py-1.5 border-t border-[rgba(204,0,0,0.3)] flex items-center gap-2 shrink-0">
        <span className="text-[#FF3366] mono text-[11px]">root@abyss:~#</span>
        <span className="text-[#00ff66] mono text-[11px] animate-pulse">█</span>
      </div>
    </div>
  );
}
