import { useEffect, useRef, useState } from 'react';
import { geoGraticule10, geoOrthographic, geoPath } from 'd3-geo';
import { feature, mesh } from 'topojson-client';
import { GlobePoint } from '../types';

type GeoShape = any;
type EarthData = { land: GeoShape; borders: GeoShape; grid: GeoShape };

export function ProxyGlobe({
  liveCount = 0,
  isActive = false,
  points = [],
}: {
  liveCount?: number;
  isActive?: boolean;
  points?: GlobePoint[];
}) {
  const canvasRef    = useRef<HTMLCanvasElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const rotRef       = useRef(20);
  const animRef      = useRef(0);
  const [size, setSize] = useState({ w: 400, h: 400 });
  const [earth, setEarth] = useState<EarthData | null>(null);

  // Load topology once
  useEffect(() => {
    let alive = true;
    Promise.all([
      import('world-atlas/land-50m.json'),
      import('world-atlas/countries-50m.json'),
    ]).then(([lm, cm]) => {
      if (!alive) return;
      const lt = lm.default as any;
      const ct = cm.default as any;
      setEarth({
        land:    feature(lt, lt.objects.land) as GeoShape,
        borders: mesh(ct, ct.objects.countries, (a: any, b: any) => a !== b) as GeoShape,
        grid:    geoGraticule10() as GeoShape,
      });
    });
    return () => { alive = false; };
  }, []);

  // Track container size
  useEffect(() => {
    const update = () => {
      if (!containerRef.current) return;
      const r = containerRef.current.getBoundingClientRect();
      setSize({ w: r.width, h: r.height });
    };
    update();
    const ro = new ResizeObserver(update);
    if (containerRef.current) ro.observe(containerRef.current);
    return () => ro.disconnect();
  }, []);

  // Render loop
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    const dpr = Math.min(window.devicePixelRatio || 1, 1.5);
    canvas.width  = Math.max(1, Math.floor(size.w * dpr));
    canvas.height = Math.max(1, Math.floor(size.h * dpr));
    canvas.style.width  = `${size.w}px`;
    canvas.style.height = `${size.h}px`;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

    const cx = size.w / 2;
    const cy = size.h / 2;
    const R  = Math.min(size.w, size.h) * 0.42;

    const proj = geoOrthographic()
      .translate([cx, cy])
      .scale(R)
      .clipAngle(90)
      .precision(0.5);
    const path = geoPath(proj, ctx);

    const SPEED = isActive ? 0.016 : 0.006;
    let last = 0;

    const draw = (ts: number) => {
      const dt = last ? ts - last : 16;
      last = ts;
      rotRef.current = (rotRef.current + dt * SPEED) % 360;
      proj.rotate([rotRef.current, -8, 0]);

      ctx.clearRect(0, 0, size.w, size.h);

      // Ocean sphere
      const ocean = ctx.createRadialGradient(cx - R * 0.3, cy - R * 0.3, R * 0.05, cx, cy, R);
      ocean.addColorStop(0, '#1e1e22');
      ocean.addColorStop(1, '#0d0d0f');
      ctx.beginPath();
      ctx.arc(cx, cy, R, 0, Math.PI * 2);
      ctx.fillStyle = ocean;
      ctx.fill();

      // Clipped geo content
      ctx.save();
      ctx.beginPath();
      path({ type: 'Sphere' } as GeoShape);
      ctx.clip();

      // Grid
      ctx.beginPath();
      path(earth?.grid);
      ctx.strokeStyle = 'rgba(255,255,255,0.04)';
      ctx.lineWidth = 0.4;
      ctx.stroke();

      // Land
      if (earth) {
        ctx.beginPath();
        path(earth.land);
        ctx.fillStyle = '#1e1e24';
        ctx.fill();
        ctx.strokeStyle = 'rgba(255,255,255,0.06)';
        ctx.lineWidth = 0.6;
        ctx.stroke();

        // Borders
        ctx.beginPath();
        path(earth.borders);
        ctx.strokeStyle = 'rgba(255,255,255,0.04)';
        ctx.lineWidth = 0.4;
        ctx.stroke();
      }

      // Proxy points
      const rot = proj.rotate();
      for (const pt of points) {
        if (!isFinite(pt.lat) || !isFinite(pt.lon)) continue;
        if (!_visible(pt.lon, pt.lat, rot[0], rot[1])) continue;
        const px = proj([pt.lon, pt.lat]);
        if (!px) continue;
        const [x, y] = px;

        // Glow
        const g = ctx.createRadialGradient(x, y, 0, x, y, 10);
        g.addColorStop(0, 'rgba(229,57,53,0.5)');
        g.addColorStop(1, 'rgba(229,57,53,0)');
        ctx.beginPath();
        ctx.arc(x, y, 10, 0, Math.PI * 2);
        ctx.fillStyle = g;
        ctx.fill();

        // Dot
        ctx.beginPath();
        ctx.arc(x, y, 2, 0, Math.PI * 2);
        ctx.fillStyle = '#e53935';
        ctx.fill();
      }

      ctx.restore();

      // Rim
      ctx.beginPath();
      ctx.arc(cx, cy, R, 0, Math.PI * 2);
      ctx.strokeStyle = 'rgba(255,255,255,0.08)';
      ctx.lineWidth = 1;
      ctx.stroke();

      // Atmosphere glow
      const atm = ctx.createRadialGradient(cx, cy, R * 0.92, cx, cy, R * 1.12);
      atm.addColorStop(0, 'rgba(229,57,53,0.06)');
      atm.addColorStop(1, 'rgba(229,57,53,0)');
      ctx.beginPath();
      ctx.arc(cx, cy, R * 1.12, 0, Math.PI * 2);
      ctx.fillStyle = atm;
      ctx.fill();

      animRef.current = requestAnimationFrame(draw);
    };

    animRef.current = requestAnimationFrame(draw);
    return () => cancelAnimationFrame(animRef.current);
  }, [earth, isActive, points, size]);

  return (
    <div ref={containerRef} className="relative w-full h-full min-h-[280px]">
      <canvas ref={canvasRef} className="w-full h-full" />
      {/* Live count overlay */}
      <div className="absolute inset-0 flex items-center justify-center pointer-events-none">
        <div className="text-center">
          <div className="text-3xl font-bold text-[#f0f0f2] tabular-nums leading-none">
            {liveCount}
          </div>
          <div className="text-[10px] text-[#6b6b72] uppercase tracking-widest mt-1.5">
            Live nodes
          </div>
        </div>
      </div>
    </div>
  );
}

function _visible(lon: number, lat: number, rLon: number, rLat: number) {
  const λ  = ((lon + rLon) * Math.PI) / 180;
  const φ  = (lat * Math.PI) / 180;
  const φ0 = (rLat * Math.PI) / 180;
  return Math.sin(φ0) * Math.sin(φ) + Math.cos(φ0) * Math.cos(φ) * Math.cos(λ) > 0;
}
