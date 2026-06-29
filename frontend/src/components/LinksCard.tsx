import { useState } from 'react';
import { Copy, Download, Link2 } from 'lucide-react';

export function LinksCard() {
  const subUrl = `${window.location.protocol}//${window.location.host}/sub`;
  const [copied, setCopied] = useState(false);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(subUrl);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {}
  };

  return (
    <div className="card" style={{borderRadius: '6px'}}>
      <div className="px-3 py-2 border-b border-[rgba(204,0,0,0.3)] flex items-center gap-1.5">
        <Link2 className="w-3.5 h-3.5 text-[#FF3366]" />
        <span className="cyber-text text-xs text-[#cccccc]">⛧ ENDPOINTS</span>
      </div>

      <div className="divide-y divide-[rgba(204,0,0,0.2)]">
        <div className="px-3 py-2 flex items-center gap-2">
          <Copy className="w-3.5 h-3.5 text-[#999999] shrink-0" />
          <div className="flex-1 min-w-0">
            <div className="mono text-[8px] text-[#666666] mb-0.5 uppercase">
              SUB URL
            </div>
            <div className="mono text-[11px] text-[#cccccc] truncate">
              {subUrl}
            </div>
          </div>
          <button
            onClick={copy}
            className="cyber-text text-[9px] px-2 py-1 rounded-sm shrink-0
              bg-[rgba(204,0,0,0.15)] border border-[rgba(255,51,102,0.4)]
              text-[#FF3366] hover:bg-[rgba(255,51,102,0.25)]
              transition-all btn-glow"
          >
            {copied ? '✓' : 'COPY'}
          </button>
        </div>

        <div className="px-3 py-2 flex items-center gap-2">
          <Download className="w-3.5 h-3.5 text-[#999999] shrink-0" />
          <div className="flex-1 min-w-0">
            <div className="mono text-[8px] text-[#666666] mb-0.5 uppercase">
              CONFIG YAML
            </div>
            <div className="mono text-[11px] text-[#cccccc]">
              /api/download
            </div>
          </div>
          <a
            href="/api/download"
            target="_blank"
            className="cyber-text text-[9px] px-2 py-1 rounded-sm shrink-0 no-underline
              bg-gradient-to-r from-[#CC0000] to-[#8B0000] border border-[#FF3366]
              text-white hover:from-[#FF3366] hover:to-[#CC0000]
              transition-all btn-glow inline-block"
          >
            GET
          </a>
        </div>
      </div>
    </div>
  );
}