import { useState } from 'react';
import { Play, Square, Terminal, Archive } from 'lucide-react';

interface ControlsProps {
  onGenerate: (opts: GenerateOptions) => void;
  onCancel: () => void;
  isRunning: boolean;
  disabled?: boolean;
  mode: 'full' | 'from-data';
  onModeChange: (mode: 'full' | 'from-data') => void;
  selectedDataset: string | null;
}

export interface GenerateOptions {
  limit: number;
  maxChecks: number;
  timeout: number;
  selection: 'fastest' | 'balanced';
}

export function Controls({ onGenerate, onCancel, isRunning, disabled, mode, onModeChange, selectedDataset }: ControlsProps) {
  const [opts, setOpts] = useState<GenerateOptions>({
    limit: 500,
    maxChecks: 10000,
    timeout: 10,
    selection: 'fastest',
  });

  return (
    <div className="card" style={{borderRadius: '6px'}}>
      <div className="px-3 py-2 border-b border-[rgba(204,0,0,0.3)] flex items-center justify-between">
        <div className="flex items-center gap-1.5">
          <Terminal className="w-4 h-4 text-[#FF3366]" />
          <span className="cyber-text text-xs text-[#cccccc]">⛧ RITUAL PARAMETERS</span>
          <div className="flex items-center gap-1 ml-2">
            <button
              onClick={() => onModeChange('full')}
              className={`cyber-text text-[9px] px-2 py-0.5 rounded-sm border transition-all ${
                mode === 'full'
                  ? 'bg-[rgba(204,0,0,0.2)] border-[rgba(255,51,102,0.5)] text-[#FF3366]'
                  : 'bg-transparent border-[rgba(204,0,0,0.1)] text-[#555555] hover:border-[rgba(255,51,102,0.3)]'
              }`}
            >
              FULL
            </button>
            <button
              onClick={() => onModeChange('from-data')}
              className={`cyber-text text-[9px] px-2 py-0.5 rounded-sm border transition-all flex items-center gap-1 ${
                mode === 'from-data'
                  ? 'bg-[rgba(204,0,0,0.2)] border-[rgba(255,51,102,0.5)] text-[#FF3366]'
                  : 'bg-transparent border-[rgba(204,0,0,0.1)] text-[#555555] hover:border-[rgba(255,51,102,0.3)]'
              }`}
            >
              <Archive className="w-3 h-3" />
              DATA
            </button>
          </div>
        </div>

        {mode === 'full' && (
          <div className="flex items-center gap-2">
            {isRunning ? (
              <button
                onClick={onCancel}
                className="cyber-text text-[10px] px-3 py-1.5 rounded-sm
                  bg-[rgba(204,0,0,0.2)] border border-[rgba(255,51,102,0.5)]
                  text-[#FF3366] hover:bg-[rgba(255,51,102,0.3)]
                  transition-all btn-glow flex items-center gap-1.5"
              >
                <Square className="w-3 h-3" />
                ABORT
              </button>
            ) : (
              <button
                onClick={() => onGenerate(opts)}
                disabled={disabled}
                className="cyber-text text-[10px] px-4 py-1.5 rounded-sm
                  bg-gradient-to-r from-[#CC0000] to-[#8B0000] border border-[#FF3366]
                  text-white hover:from-[#FF3366] hover:to-[#CC0000]
                  disabled:opacity-30 disabled:cursor-not-allowed
                  transition-all btn-glow flex items-center gap-1.5"
                style={{boxShadow: '0 0 16px rgba(204,0,0,0.25)'}}
              >
                <Play className="w-3 h-3" />
                SUMMON
              </button>
            )}
          </div>
        )}

        {mode === 'from-data' && (
          <div className="flex items-center gap-2">
            {isRunning ? (
              <button
                onClick={onCancel}
                className="cyber-text text-[10px] px-3 py-1.5 rounded-sm
                  bg-[rgba(204,0,0,0.2)] border border-[rgba(255,51,102,0.5)]
                  text-[#FF3366] hover:bg-[rgba(255,51,102,0.3)]
                  transition-all btn-glow flex items-center gap-1.5"
              >
                <Square className="w-3 h-3" />
                ABORT
              </button>
            ) : (
              <button
                onClick={() => onGenerate(opts)}
                disabled={disabled || !selectedDataset}
                className="cyber-text text-[10px] px-4 py-1.5 rounded-sm
                  bg-gradient-to-r from-[#CC0000] to-[#8B0000] border border-[#FF3366]
                  text-white hover:from-[#FF3366] hover:to-[#CC0000]
                  disabled:opacity-30 disabled:cursor-not-allowed
                  transition-all btn-glow flex items-center gap-1.5"
                style={{boxShadow: '0 0 16px rgba(204,0,0,0.25)'}}
              >
                <Play className="w-3 h-3" />
                SUMMON FROM DATA
              </button>
            )}
          </div>
        )}
      </div>

      <div className="p-3 space-y-3">
        {mode === 'from-data' && selectedDataset && (
          <div className="flex items-center gap-2 px-2 py-1.5 rounded-sm bg-[rgba(204,0,0,0.1)] border border-[rgba(255,51,102,0.2)]">
            <Archive className="w-3 h-3 text-[#FF3366]" />
            <span className="mono text-[11px] text-[#FF3366]">{selectedDataset}</span>
          </div>
        )}
        {mode === 'from-data' && !selectedDataset && (
          <div className="px-2 py-1.5 rounded-sm bg-[rgba(204,0,0,0.05)] border border-[rgba(204,0,0,0.1)]">
            <span className="mono text-[10px] text-[#666666]">Select a dataset from PROXY-DATA panel →</span>
          </div>
        )}
        <div className={`grid gap-3 ${mode === 'full' ? 'grid-cols-2 sm:grid-cols-4' : 'grid-cols-2'}`}>
          <label className="flex flex-col gap-1">
            <span className="mono text-[8px] text-[#999999] uppercase tracking-wider">
              ⛧ proxy_limit
            </span>
            <input
              type="number" min={1} max={10000}
              value={opts.limit}
              onChange={e => setOpts({ ...opts, limit: Number(e.target.value) })}
              disabled={isRunning}
              className="mono text-xs px-2 py-1.5 rounded-sm
                bg-black/70 border border-[rgba(204,0,0,0.3)]
                text-[#cccccc] focus:border-[rgba(255,51,102,0.6)]
                disabled:opacity-40 transition-all"
            />
          </label>

          {mode === 'full' && (
            <label className="flex flex-col gap-1">
              <span className="mono text-[8px] text-[#999999] uppercase tracking-wider">
                ⛧ max_checks
              </span>
              <input
                type="number" min={0} max={100000}
                value={opts.maxChecks}
                onChange={e => setOpts({ ...opts, maxChecks: Number(e.target.value) })}
                disabled={isRunning}
                className="mono text-xs px-2 py-1.5 rounded-sm
                  bg-black/70 border border-[rgba(204,0,0,0.3)]
                  text-[#cccccc] focus:border-[rgba(255,51,102,0.6)]
                  disabled:opacity-40 transition-all"
              />
            </label>
          )}

          {mode === 'full' && (
            <label className="flex flex-col gap-1">
              <span className="mono text-[8px] text-[#999999] uppercase tracking-wider">
                ⛧ timeout_sec
              </span>
              <input
                type="number" min={1} max={60} step={0.5}
                value={opts.timeout}
                onChange={e => setOpts({ ...opts, timeout: Number(e.target.value) })}
                disabled={isRunning}
                className="mono text-xs px-2 py-1.5 rounded-sm
                  bg-black/70 border border-[rgba(204,0,0,0.3)]
                  text-[#cccccc] focus:border-[rgba(255,51,102,0.6)]
                  disabled:opacity-40 transition-all"
              />
            </label>
          )}

          <label className="flex flex-col gap-1">
            <span className="mono text-[8px] text-[#999999] uppercase tracking-wider">
              ⛧ strategy
            </span>
            <select
              value={opts.selection}
              onChange={e => setOpts({ ...opts, selection: e.target.value as 'fastest' | 'balanced' })}
              disabled={isRunning}
              className="mono text-xs px-2 py-1.5 rounded-sm
                bg-black/70 border border-[rgba(204,0,0,0.3)]
                text-[#cccccc] focus:border-[rgba(255,51,102,0.6)]
                disabled:opacity-40 transition-all appearance-none cursor-pointer"
            >
              <option value="fastest">FASTEST</option>
              <option value="balanced">BALANCED</option>
            </select>
          </label>
        </div>
      </div>
    </div>
  );
}
