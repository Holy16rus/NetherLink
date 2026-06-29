import { useState, useEffect } from 'react';
import { Archive, Loader2 } from 'lucide-react';

export interface ProxyDataEntry {
  name: string;
  live: number;
  checked: number;
  candidates: number;
  sources: number;
  timestamp: string;
}

interface ProxyDataPanelProps {
  selected: string[];
  onToggle: (dataset: string) => void;
  disabled?: boolean;
}

const API = '/api';

export function ProxyDataPanel({ selected, onToggle, disabled }: ProxyDataPanelProps) {
  const [entries, setEntries] = useState<ProxyDataEntry[]>([]);
  const [loading, setLoading] = useState(false);

  const fetchEntries = () => {
    setLoading(true);
    fetch(`${API}/proxy-data`)
      .then(r => r.json())
      .then(d => setEntries(d.entries || []))
      .catch(() => {})
      .finally(() => setLoading(false));
  };

  useEffect(() => { fetchEntries(); }, []);

  const formatTs = (ts: string) => {
    try {
      const d = new Date(ts);
      return d.toLocaleString('ru-RU', {
        day: '2-digit', month: '2-digit',
        hour: '2-digit', minute: '2-digit',
      });
    } catch { return ts; }
  };

  const toggleAll = () => {
    if (selected.length === entries.length) {
      // deselect all
      entries.forEach(e => {
        if (selected.includes(e.name)) onToggle(e.name);
      });
    } else {
      // select all
      entries.forEach(e => {
        if (!selected.includes(e.name)) onToggle(e.name);
      });
    }
  };

  const allSelected = entries.length > 0 && selected.length === entries.length;

  return (
    <div className="card" style={{borderRadius: '8px', display: 'flex', flexDirection: 'column', maxHeight: '364px'}}>
      <div className="px-3 py-2 border-b border-[rgba(204,0,0,0.3)] flex items-center justify-between">
        <div className="flex items-center gap-1.5">
          <Archive className="w-3.5 h-3.5 text-[#FF3366]" />
          <span className="cyber-text text-xs text-[#cccccc]">⛧ PROXY-DATA</span>
          {selected.length > 0 && (
            <span className="mono text-[9px] text-[#FF3366] ml-1">({selected.length})</span>
          )}
        </div>
        <div className="flex items-center gap-1">
          <button
            onClick={toggleAll}
            disabled={loading || entries.length === 0}
            className="cyber-text text-[9px] px-2 py-1 rounded-sm
              bg-[rgba(204,0,0,0.1)] border border-[rgba(255,51,102,0.3)]
              text-[#FF3366] hover:bg-[rgba(255,51,102,0.2)]
              disabled:opacity-30 transition-all"
          >
            {allSelected ? '✕ ALL' : '✓ ALL'}
          </button>
          <button
            onClick={fetchEntries}
            disabled={loading}
            className="cyber-text text-[9px] px-2 py-1 rounded-sm
              bg-[rgba(204,0,0,0.1)] border border-[rgba(255,51,102,0.3)]
              text-[#FF3366] hover:bg-[rgba(255,51,102,0.2)]
              disabled:opacity-30 transition-all"
          >
            ↻
          </button>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto divide-y divide-[rgba(204,0,0,0.08)]" style={{minHeight: 0}}>
        {loading && entries.length === 0 && (
          <div className="px-3 py-6 text-center mono text-[11px] text-[#666666]">
            <Loader2 className="w-4 h-4 mx-auto mb-1 animate-spin text-[#FF3366]" />
            {'>'} Loading...
          </div>
        )}
        {!loading && entries.length === 0 && (
          <div className="px-3 py-6 text-center mono text-[11px] text-[#666666]">
            <div className="mb-1 text-[#CC0000] text-lg">💀</div>
            {'>'} No saved datasets<br/>
            {'>'} Run a full generation first
          </div>
        )}
        {entries.map((entry) => {
          const isSel = selected.includes(entry.name);
          return (
            <div
              key={entry.name}
              onClick={() => !disabled && onToggle(entry.name)}
              className={`px-3 py-2 flex items-center gap-2 cursor-pointer transition-colors ${
                isSel
                  ? 'bg-[rgba(204,0,0,0.1)] hover:bg-[rgba(204,0,0,0.15)]'
                  : 'hover:bg-[rgba(204,0,0,0.04)]'
              } ${disabled ? 'opacity-40 cursor-not-allowed' : ''}`}
            >
              <input
                type="checkbox"
                checked={isSel}
                onChange={() => {}}
                disabled={disabled}
                className="w-3 h-3 accent-[#FF3366] cursor-pointer shrink-0 rounded"
              />
              <div className="flex-1 min-w-0">
                <div className={`mono text-[11px] truncate ${isSel ? 'text-[#FF3366]' : 'text-[#cccccc]'}`}>
                  {entry.name}
                </div>
                <div className="flex items-center gap-2 mt-0.5">
                  <span className="mono text-[9px] text-[#FF3366]">{entry.live} live</span>
                  <span className="mono text-[9px] text-[#666666]">
                    {formatTs(entry.timestamp)}
                  </span>
                  <span className="mono text-[9px] text-[#555555]">
                    {entry.checked} chk / {entry.sources} src
                  </span>
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
