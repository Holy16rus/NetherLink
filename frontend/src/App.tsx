import { useState, useEffect, useCallback, useRef } from 'react';
import { Download, Shield } from 'lucide-react';

import { StatusHeader } from './components/StatusHeader';
import { MetricsPanel, ProgressBar } from './components/MetricCard';
import { Controls, GenerateOptions } from './components/Controls';
import { SourcesPanel } from './components/SourcesPanel';
import { ProxyDataPanel } from './components/ProxyDataPanel';
import { LinksCard } from './components/LinksCard';
import { LogViewer, LogEntry } from './components/LogViewer';
import { useSSE } from './hooks/useSSE';

import { ProxySource, Metrics, EngineStatus } from './types';

const API = '/api';
let _logId = 0;

const EMPTY_METRICS: Metrics = {
  total_sources: 0, current_source: 0,
  candidates: 0,    deduped: 0,
  checking_progress: 0, checking_total: 0,
  live: 0,          checker_rated: 0, checker_filtered: 0,
  geo_checked: 0,   selected: 0,
  countries: 0,
};

export default function App() {
  const [sources,   setSources]   = useState<ProxySource[]>([]);
  const [metrics,   setMetrics]   = useState<Metrics>(EMPTY_METRICS);
  const [status,    setStatus]    = useState<EngineStatus>('idle');
  const [statusMsg, setStatusMsg] = useState('Ожидание');
  const [logs,      setLogs]      = useState<LogEntry[]>([]);
  const [isRunning, setIsRunning] = useState(false);
  const [mode,       setMode]      = useState<'full' | 'from-data'>('full');
  const [selectedDatasets, setSelectedDatasets] = useState<string[]>([]);

  const statusRef = useRef(EMPTY_METRICS);
  statusRef.current = metrics;

  // Fetch config
  useEffect(() => {
    fetch(`${API}/config`)
      .then((r) => r.json())
      .then((cfg) => setSources(cfg.sources || []))
      .catch(() => {});
  }, []);

  // SSE handlers
  const handleStatus = useCallback((data: Record<string, unknown>) => {
    const s = data.status as EngineStatus;
    setStatus(s);
    setStatusMsg((data.message as string) || '');
    setIsRunning(s === 'running');
    // Clear reconnecting state when we receive a real status
    setReconnecting(false);
  }, []);

  const handleMetrics = useCallback((data: Record<string, unknown>) => {
    setMetrics((prev) => ({ ...prev, ...data }));
  }, []);

  const handleLog = useCallback((data: Record<string, unknown>) => {
    setLogs((prev) => {
      const entry: LogEntry = {
        id: ++_logId,
        text: (data.text as string) || '',
        level: data.level as string,
        time: Date.now() / 1000,
      };
      const next = [...prev, entry];
      return next.slice(-200);
    });
  }, []);

  const [reconnecting, setReconnecting] = useState(false);

  useSSE(`${API}/stream`, {
    status: handleStatus,
    metrics: handleMetrics,
    log: handleLog,
    __open: () => {
      if (reconnecting) {
        setReconnecting(false);
        // Восстановили соединение — запрашиваем текущий статус
        fetch(`${API}/status`)
          .then(r => r.json())
          .then(s => {
            const st = s.status as EngineStatus;
            setStatus(st);
            setStatusMsg('');
            setIsRunning(st === 'running');
            if (s.metrics) setMetrics(prev => ({ ...prev, ...s.metrics }));
          })
          .catch(() => {});
      }
    },
    __error: () => {
      setReconnecting(true);
      setStatus('error');
      setStatusMsg('Соединение оборвано, переподключаюсь...');
    },
  });

  const startGenerate = async (opts: GenerateOptions) => {
    setLogs([]);
    setMetrics(EMPTY_METRICS);

    if (mode === 'from-data' && selectedDatasets.length > 0) {
      try {
        const resp = await fetch(`${API}/generate-from-data`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            datasets: selectedDatasets,
            limit: opts.limit,
            selection: opts.selection,
            prefer_socks5: true,
          }),
        });
        if (!resp.ok) {
          const err = await resp.json();
          setStatus('error');
          setStatusMsg(err.detail || 'Ошибка запуска');
        }
      } catch (e) {
        setStatus('error');
        setStatusMsg(String(e));
      }
      return;
    }

    try {
      await fetch(`${API}/config`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ sources }),
      });

      const resp = await fetch(`${API}/generate`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          limit: opts.limit,
          max_checks: opts.maxChecks,
          timeout: opts.timeout,
          selection: opts.selection,
          prefer_socks5: true,
        }),
      });
      if (!resp.ok) {
        const err = await resp.json();
        setStatus('error');
        setStatusMsg(err.detail || 'Ошибка запуска');
      }
    } catch (e) {
      setStatus('error');
      setStatusMsg(String(e));
    }
  };

  const cancelGenerate = async () => {
    await fetch(`${API}/cancel`, { method: 'POST' });
  };

  const saveSources = async () => {
    await fetch(`${API}/config`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ sources }),
    });
  };

  return (
    <div className="min-h-screen">
      <div className="grid-overlay" />
      <main className="relative z-[2] max-w-7xl mx-auto px-3 sm:px-4 pt-12 pb-8">
        <div className="space-y-3">
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-3 items-stretch">
            <StatusHeader status={status} message={statusMsg} reconnecting={reconnecting} />
            <LinksCard />
          </div>

          <Controls
            onGenerate={startGenerate}
            onCancel={cancelGenerate}
            isRunning={isRunning}
            mode={mode}
            onModeChange={setMode}
            selectedDataset={selectedDatasets.length > 0 ? selectedDatasets.join(', ') : null}
          /> 

          <div className="grid grid-cols-1 lg:grid-cols-3 gap-3">
            <div className="lg:col-span-2 space-y-3">
              <div className="card p-4">
                <div className="flex items-center justify-between mb-3">
                  <h2 className="font-display text-sm font-semibold flex items-center gap-2 m-0">
                    <Shield className="w-3.5 h-3.5 text-accent" />
                    Soul Collection
                  </h2>
                  <a href="/api/download"
                    className="btn-holy flex items-center gap-1 px-2.5 py-1 rounded text-[10px] no-underline"
                    target="_blank"
                  >
                    <Download className="w-3 h-3" />
                    Extract
                  </a>
                </div>
                <MetricsPanel metrics={metrics as unknown as Record<string, number>} />
                {metrics.checking_total > 0 && (
                  <div className="mt-3">
                    <ProgressBar current={metrics.checking_progress} total={metrics.checking_total} />
                  </div>
                )}
              </div>

              <LogViewer logs={logs} />
            </div>

            <div className="lg:col-span-1 min-h-0 space-y-3">
              {mode === 'full' ? (
                <SourcesPanel
                  sources={sources}
                  onUpdate={setSources}
                  onSave={saveSources}
                />
              ) : (
                <ProxyDataPanel
                  selected={selectedDatasets}
                  onToggle={(dataset) => {
                    setSelectedDatasets(prev =>
                      prev.includes(dataset)
                        ? prev.filter(d => d !== dataset)
                        : [...prev, dataset]
                    );
                    setMode('from-data');
                  }}
                  disabled={isRunning}
                />
              )}
            </div>
          </div>
        </div>
      </main>

      <footer className="relative z-[2] text-center py-4 text-[var(--color-text-dim)] text-[10px] mt-4"
        style={{fontFamily: 'var(--font-mono)'}}>
        <div className="mb-1 text-[#CC0000] text-sm">⛧</div>
        root@abyss:~# <span className="text-accent">summon_proxy()</span>
        <br />
        <span style={{opacity: 0.5}}>Connection to Heaven... FAILED</span>
      </footer>
    </div>
  );
}
