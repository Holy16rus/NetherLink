export interface ProxySource {
  url: string;
  enabled: boolean;
}

export interface Metrics {
  total_sources: number;
  current_source: number;
  candidates: number;
  deduped: number;
  checking_progress: number;
  checking_total: number;
  live: number;
  checker_rated: number;
  checker_filtered: number;
  geo_checked: number;
  selected: number;
  countries: number;
}

export interface SSEEvent {
  event: string;
  data: Record<string, unknown>;
  time: number;
}

export interface GlobePoint {
  lat: number;
  lon: number;
  country?: string;
  latency_ms?: number;
}

export type EngineStatus = 'idle' | 'running' | 'done' | 'error' | 'cancelled';

export interface StatusData {
  status: EngineStatus;
  message?: string;
  metrics?: Metrics;
}
