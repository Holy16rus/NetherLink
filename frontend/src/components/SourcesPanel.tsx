import { useState } from 'react';
import { Plus, X, Save, Database, Trash2, CheckSquare, Square } from 'lucide-react';
import { ProxySource } from '../types';

interface SourcesPanelProps {
  sources: ProxySource[];
  onUpdate: (sources: ProxySource[]) => void;
  onSave: () => void;
}

export function SourcesPanel({ sources, onUpdate, onSave }: SourcesPanelProps) {
  const [newUrl, setNewUrl] = useState('');

  const add = () => {
    const url = newUrl.trim();
    if (!url || sources.some(s => s.url === url)) return;
    onUpdate([...sources, { url, enabled: true }]);
    setNewUrl('');
  };

  const remove = (i: number) => onUpdate(sources.filter((_, idx) => idx !== i));
  const toggle = (i: number) => onUpdate(sources.map((s, idx) => idx === i ? { ...s, enabled: !s.enabled } : s));
  const removeAll = () => onUpdate([]);
  const selectAll = () => onUpdate(sources.map(s => ({ ...s, enabled: true })));
  const deselectAll = () => onUpdate(sources.map(s => ({ ...s, enabled: false })));

  return (
    <div className="card" style={{borderRadius: '8px', display: 'flex', flexDirection: 'column', maxHeight: '364px'}}>
      <div className="px-3 py-2 border-b border-[rgba(204,0,0,0.3)] flex items-center justify-between">
        <div className="flex items-center gap-1.5">
          <Database className="w-3.5 h-3.5 text-[#FF3366]" />
          <span className="cyber-text text-xs text-[#cccccc]">⛧ SOURCES</span>
        </div>
        <div className="flex items-center gap-1">
          <button
            onClick={selectAll}
            disabled={sources.length === 0}
            title="Выбрать всё"
            className="cyber-text text-[9px] px-2 py-1 rounded-sm
              bg-[rgba(204,0,0,0.1)] border border-[rgba(255,51,102,0.3)]
              text-[#FF3366] hover:bg-[rgba(255,51,102,0.2)]
              disabled:opacity-30 disabled:cursor-not-allowed
              transition-all flex items-center gap-1"
          >
            <CheckSquare className="w-3 h-3" />
          </button>
          <button
            onClick={deselectAll}
            disabled={sources.length === 0}
            title="Убрать всё"
            className="cyber-text text-[9px] px-2 py-1 rounded-sm
              bg-[rgba(204,0,0,0.1)] border border-[rgba(255,51,102,0.3)]
              text-[#999999] hover:bg-[rgba(255,51,102,0.2)]
              disabled:opacity-30 disabled:cursor-not-allowed
              transition-all flex items-center gap-1"
          >
            <Square className="w-3 h-3" />
          </button>
          <button
            onClick={removeAll}
            disabled={sources.length === 0}
            title="Удалить всё"
            className="cyber-text text-[9px] px-2 py-1 rounded-sm
              bg-[rgba(204,0,0,0.1)] border border-[rgba(255,51,102,0.3)]
              text-[#FF3366] hover:bg-[rgba(255,51,102,0.2)]
              disabled:opacity-30 disabled:cursor-not-allowed
              transition-all flex items-center gap-1"
          >
            <Trash2 className="w-3 h-3" />
          </button>
          <button
            onClick={onSave}
            className="cyber-text text-[9px] px-2 py-1 rounded-sm ml-1
              bg-[rgba(204,0,0,0.15)] border border-[rgba(255,51,102,0.4)]
              text-[#FF3366] hover:bg-[rgba(255,51,102,0.25)]
              transition-all btn-glow flex items-center gap-1"
          >
            <Save className="w-3 h-3" />
            SAVE
          </button>
        </div>
      </div>

      <div className="px-3 py-2 border-b border-[rgba(204,0,0,0.2)] flex gap-1.5">
        <input
          type="url"
          value={newUrl}
          onChange={e => setNewUrl(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && add()}
          placeholder="https://github.com/..."
          className="flex-1 mono text-[11px] px-2 py-1.5 rounded-sm
            bg-black/70 border border-[rgba(204,0,0,0.3)]
            text-[#cccccc] placeholder:text-[#666666]
            focus:border-[rgba(255,51,102,0.6)] transition-all"
        />
        <button
          onClick={add}
          className="cyber-text text-xs px-2 py-1.5 rounded-sm shrink-0
            bg-gradient-to-r from-[#CC0000] to-[#8B0000] border border-[#FF3366]
            text-white hover:from-[#FF3366] hover:to-[#CC0000]
            transition-all btn-glow"
        >
          <Plus className="w-3.5 h-3.5" />
        </button>
      </div>

      <div className="flex-1 overflow-y-auto divide-y divide-[rgba(204,0,0,0.08)]" style={{minHeight: 0}}>
        {sources.length === 0 && (
          <div className="px-3 py-6 text-center mono text-[11px] text-[#666666]">
            <div className="mb-1 text-[#CC0000] text-lg">💀</div>
            {'>'} No sources<br/>
            {'>'} Add URL above
          </div>
        )}
        {sources.map((source, i) => (
          <div
            key={i}
            className="px-3 py-2 flex items-center gap-2 group hover:bg-[rgba(204,0,0,0.06)] transition-colors"
          >
            <input
              type="checkbox"
              checked={source.enabled}
              onChange={() => toggle(i)}
              className="w-3 h-3 accent-[#FF3366] cursor-pointer shrink-0 rounded"
            />
            <span className={`flex-1 mono text-[11px] truncate transition-colors ${
              source.enabled ? 'text-[#cccccc]' : 'text-[#555555] line-through'
            }`}>
              {source.url}
            </span>
            <button
              onClick={() => remove(i)}
              className="shrink-0 p-0.5 rounded text-[#666666] hover:text-[#FF3366] hover:bg-[rgba(255,51,102,0.15)]
                opacity-0 group-hover:opacity-100 transition-all"
            >
              <X className="w-3 h-3" />
            </button>
          </div>
        ))}
      </div>
    </div>
  );
}