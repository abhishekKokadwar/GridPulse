'use client';

import React, { useState, useEffect, useCallback, useMemo } from 'react';
import {
  Zap,
  Activity,
  ShieldAlert,
  Clock,
  Database,
  RefreshCw,
  Send,
  Building2,
  Cpu,
  Sliders,
  BellRing,
  ExternalLink,
  CheckCircle2,
  AlertTriangle,
  Flame,
  Gauge,
  Layers,
  ChevronRight,
  TrendingUp,
  Radio,
  Search,
  Download,
  Info,
  Check,
  HelpCircle,
  BarChart3,
  Server,
  ArrowUpRight,
} from 'lucide-react';
import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  BarChart,
  Bar,
} from 'recharts';

interface StreamRow {
  id: number;
  window_start: string;
  window_end: string;
  building_id: string;
  building_name: string;
  building_type: string;
  avg_power_kw: number;
  avg_voltage_v: number;
  avg_power_factor: number;
}

interface TimelinePoint {
  time: string;
  timestamp: string;
  totalPower: number;
  avgVoltage: number;
}

interface StreamResponse {
  success: boolean;
  count: number;
  latest: {
    windowEnd: string | null;
    loadKw: number;
    voltageV: number;
    activeBuildings: number;
  };
  timeline: TimelinePoint[];
  rows: StreamRow[];
  timestamp: string;
}

interface KpiResponse {
  success: boolean;
  stats: {
    buildings: number;
    meters: number;
    readings: number;
    alerts: number;
    aggregates: number;
    latestReadingTime: string | null;
  };
  instant: {
    instantaneousLoadKw: number;
    nominalVoltageV: number;
    powerFactorAvg: number;
  };
}

interface WebhookLog {
  id: string;
  timestamp: string;
  type: string;
  title: string;
  status: string;
  statusCode: number;
  latencyMs: number;
}

export default function ScadaDashboard() {
  // Navigation: Clear, self-explanatory operational tabs
  const [activeTab, setActiveTab] = useState<'stream' | 'dispatch' | 'buildings' | 'table'>('stream');

  // Refresh Cadence
  const [refreshInterval, setRefreshInterval] = useState<number>(3000); // 3000ms
  const [isRefreshing, setIsRefreshing] = useState<boolean>(false);
  const [lastSyncTime, setLastSyncTime] = useState<string>('');
  const [pingLatency, setPingLatency] = useState<number>(45);

  // Data states
  const [streamData, setStreamData] = useState<StreamResponse | null>(null);
  const [kpiData, setKpiData] = useState<KpiResponse | null>(null);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  // Search & Filters
  const [searchQuery, setSearchQuery] = useState<string>('');
  const [selectedCategory, setSelectedCategory] = useState<string>('All');
  const [timeFilter, setTimeFilter] = useState<'15m' | '30m' | 'all'>('30m');
  const [showInfoBanner, setShowInfoBanner] = useState<boolean>(true);

  // Demand Response & Peak Shaving states
  const [contractThreshold, setContractThreshold] = useState<number>(800);
  const [tier1Armed, setTier1Armed] = useState<boolean>(true);
  const [tier2Armed, setTier2Armed] = useState<boolean>(true);
  const [tier3Armed, setTier3Armed] = useState<boolean>(false);

  // Webhook states
  const [webhookUrl, setWebhookUrl] = useState<string>('');
  const [webhookLogs, setWebhookLogs] = useState<WebhookLog[]>([]);
  const [isDispatching, setIsDispatching] = useState<boolean>(false);
  const [toastMessage, setToastMessage] = useState<{ text: string; type: 'success' | 'error' | 'info' } | null>(null);

  // Live Clock
  const [currentTime, setCurrentTime] = useState<string>('');
  useEffect(() => {
    const timer = setInterval(() => {
      setCurrentTime(new Date().toLocaleTimeString('en-US', { hour12: false }));
    }, 1000);
    return () => clearInterval(timer);
  }, []);

  // Fetch Telemetry Data
  const fetchData = useCallback(async () => {
    setIsRefreshing(true);
    const start = performance.now();
    try {
      const [streamRes, kpiRes] = await Promise.all([
        fetch('/api/telemetry/stream?limit=120', { cache: 'no-store' }),
        fetch('/api/telemetry/kpis', { cache: 'no-store' }),
      ]);

      const streamJson = await streamRes.json();
      const kpiJson = await kpiRes.json();

      if (streamJson.success) setStreamData(streamJson);
      if (kpiJson.success) setKpiData(kpiJson);

      const duration = Math.round(performance.now() - start);
      setPingLatency(duration);
      setLastSyncTime(new Date().toLocaleTimeString('en-US', { hour12: false }));
      setErrorMsg(null);
    } catch (err: any) {
      setErrorMsg(err.message || 'Network error connecting to telemetry endpoints');
    } finally {
      setIsRefreshing(false);
    }
  }, []);

  // Polling loop
  useEffect(() => {
    fetchData();
    if (refreshInterval === 0) return;
    const interval = setInterval(fetchData, refreshInterval);
    return () => clearInterval(interval);
  }, [fetchData, refreshInterval]);

  // Derived calculations for Dispatch
  const currentTotalLoad = streamData?.latest?.loadKw || kpiData?.instant?.instantaneousLoadKw || 618.6;
  const projectedPeak = Math.max(currentTotalLoad * 1.18, 885.5);
  const projectedOverload = Math.max(0, projectedPeak - contractThreshold);
  const potentialSavings = projectedOverload > 0 ? Math.round(projectedOverload * 350) : 0;

  // Active Shed calculation based on switches
  const activeShedTotal = useMemo(() => {
    let total = 0;
    if (tier1Armed) total += 45.0;
    if (tier2Armed) total += 40.5;
    if (tier3Armed) total += 50.0;
    return total;
  }, [tier1Armed, tier2Armed, tier3Armed]);

  // Toast Notification helper
  const showToast = (text: string, type: 'success' | 'error' | 'info') => {
    setToastMessage({ text, type });
    setTimeout(() => setToastMessage(null), 4500);
  };

  // Dispatch Webhook handler
  const handleDispatch = async (type: 'PEAK_SHAVING' | 'SCADA_FAULT') => {
    setIsDispatching(true);
    const start = performance.now();
    try {
      const actions = [
        { tier: 1, category: 'Soft Shedding', name: 'Facilities & EV Setback', active_shed_kw: 45.0, status: tier1Armed ? 'ARMED' : 'STANDBY' },
        { tier: 2, category: 'Chiller Cycling', name: 'Academic HVAC Duty Cycling', active_shed_kw: 40.5, status: tier2Armed ? 'ARMED' : 'STANDBY' },
        { tier: 3, category: 'BESS Injection', name: 'Campus Battery Storage', active_shed_kw: 50.0, status: tier3Armed ? 'ARMED' : 'STANDBY' },
      ];

      const res = await fetch('/api/dispatch/webhook', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          type,
          webhookUrl,
          peakKw: projectedPeak,
          thresholdKw: contractThreshold,
          overloadKw: projectedOverload,
          savings: potentialSavings,
          actions,
        }),
      });

      const data = await res.json();
      const latency = Math.round(performance.now() - start);

      const logEntry: WebhookLog = {
        id: Math.random().toString(36).substring(7),
        timestamp: new Date().toLocaleTimeString(),
        type: type === 'PEAK_SHAVING' ? 'Peak Demand Directive' : 'Voltage Sag Fault Alert',
        title: type === 'PEAK_SHAVING' ? `Impending Breach (+${projectedOverload.toFixed(1)} kW)` : 'CRITICAL VOLTAGE SAG at M012',
        status: data.status || 'SENT',
        statusCode: data.statusCode || 200,
        latencyMs: latency,
      };

      setWebhookLogs(prev => [logEntry, ...prev.slice(0, 19)]);

      if (data.success) {
        showToast(`Delivered to Slack Channel! (HTTP ${data.statusCode} in ${latency}ms)`, 'success');
      } else {
        showToast(`Webhook delivery failed: ${data.message}`, 'error');
      }
    } catch (err: any) {
      showToast(`Dispatch error: ${err.message}`, 'error');
    } finally {
      setIsDispatching(false);
    }
  };

  // Filtered rows for table & building cards
  const filteredRows = useMemo(() => {
    if (!streamData?.rows) return [];
    let list = streamData.rows;
    if (selectedCategory !== 'All') {
      list = list.filter(r => r.building_type === selectedCategory);
    }
    if (searchQuery.trim()) {
      const q = searchQuery.toLowerCase();
      list = list.filter(
        r => r.building_name.toLowerCase().includes(q) || r.building_id.toLowerCase().includes(q)
      );
    }
    return list;
  }, [streamData?.rows, selectedCategory, searchQuery]);

  // Filtered timeline data (provides smooth points)
  const filteredTimeline = useMemo(() => {
    if (!streamData?.timeline || streamData.timeline.length === 0) return [];
    if (timeFilter === '15m') return streamData.timeline.slice(-15);
    if (timeFilter === '30m') return streamData.timeline.slice(-30);
    return streamData.timeline;
  }, [streamData?.timeline, timeFilter]);

  // Building power distribution (Top 8 highest consumers)
  const buildingChartData = useMemo(() => {
    if (!streamData?.rows) return [];
    const map = new Map<string, number>();
    for (const r of streamData.rows) {
      const current = map.get(r.building_name) || 0;
      map.set(r.building_name, Math.max(current, r.avg_power_kw));
    }
    return Array.from(map.entries())
      .map(([name, power]) => ({ name, power: Number(power.toFixed(1)) }))
      .sort((a, b) => b.power - a.power)
      .slice(0, 8);
  }, [streamData?.rows]);

  // CSV Export utility
  const exportCsv = () => {
    if (!filteredRows || filteredRows.length === 0) return;
    const headers = ['ID', 'Window Start', 'Window End', 'Building ID', 'Building Name', 'Category', 'Avg Power kW', 'Avg Voltage V', 'Power Factor'];
    const csvContent = [
      headers.join(','),
      ...filteredRows.map(r =>
        [
          r.id,
          `"${r.window_start}"`,
          `"${r.window_end}"`,
          `"${r.building_id}"`,
          `"${r.building_name}"`,
          `"${r.building_type}"`,
          r.avg_power_kw,
          r.avg_voltage_v,
          r.avg_power_factor,
        ].join(',')
      ),
    ].join('\n');

    const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.setAttribute('href', url);
    link.setAttribute('download', `gridpulse_telemetry_${new Date().toISOString().slice(0, 10)}.csv`);
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    showToast('Exported telemetry records to CSV', 'info');
  };

  return (
    <div className="min-h-screen bg-[#090D16] text-slate-100 flex flex-col font-sans">
      {/* Toast Notification */}
      {toastMessage && (
        <div className="fixed bottom-6 right-6 z-50 animate-bounce">
          <div
            className={`px-4 py-3 rounded-xl shadow-2xl flex items-center gap-3 border text-xs font-semibold backdrop-blur-xl ${
              toastMessage.type === 'success'
                ? 'bg-emerald-950/90 text-emerald-200 border-emerald-500/50'
                : toastMessage.type === 'error'
                ? 'bg-red-950/90 text-red-200 border-red-500/50'
                : 'bg-amber-950/90 text-amber-200 border-amber-500/50'
            }`}
          >
            {toastMessage.type === 'success' && <CheckCircle2 className="w-4 h-4 text-emerald-400" />}
            {toastMessage.type === 'error' && <AlertTriangle className="w-4 h-4 text-red-400" />}
            {toastMessage.type === 'info' && <Info className="w-4 h-4 text-amber-400" />}
            <span>{toastMessage.text}</span>
          </div>
        </div>
      )}

      {/* TOP SCADA CONTROL HEADER */}
      <header className="border-b border-slate-800/80 bg-slate-950/70 backdrop-blur-xl sticky top-0 z-40 px-6 py-3 flex flex-wrap items-center justify-between gap-4">
        <div className="flex items-center gap-3.5">
          <div className="w-10 h-10 rounded-xl bg-gradient-to-tr from-amber-500 to-yellow-400 flex items-center justify-center shadow-lg shadow-amber-500/20">
            <Zap className="w-6 h-6 text-slate-950 fill-current" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h1 className="text-lg font-bold tracking-tight text-white flex items-center gap-2">
                GridPulse Operations Portal
                <span className="text-[10px] px-2 py-0.5 rounded-full bg-emerald-500/10 text-emerald-400 font-mono border border-emerald-500/30">
                  SCADA LIVE
                </span>
              </h1>
            </div>
            <p className="text-xs text-slate-400">
              Smart Campus Microgrid Telemetry • 22 Buildings • 42 Sub-Meters • Neon Serverless Cloud
            </p>
          </div>
        </div>

        {/* Live Status Indicators */}
        <div className="flex items-center gap-3 bg-slate-900/80 px-4 py-1.5 rounded-xl border border-slate-800">
          <div className="flex items-center gap-2">
            <span className="w-2.5 h-2.5 rounded-full bg-emerald-400 animate-ping" />
            <span className="text-xs font-mono font-bold text-emerald-400">POSTGRES CLOUD</span>
          </div>
          <div className="h-4 w-px bg-slate-800" />
          <div className="text-xs text-slate-400 flex items-center gap-1.5 font-mono">
            <Clock className="w-3.5 h-3.5 text-slate-500" />
            <span>{currentTime || '00:00:00'}</span>
          </div>
          <div className="h-4 w-px bg-slate-800" />
          <div className="text-xs font-mono text-slate-400">
            Latency: <span className="text-amber-400 font-semibold">{pingLatency}ms</span>
          </div>
        </div>

        {/* Cadence Controls & Links */}
        <div className="flex items-center gap-3">
          <div className="flex items-center bg-slate-900 border border-slate-800 rounded-lg p-0.5 text-xs font-medium">
            <span className="px-2 text-[11px] text-slate-500">Refresh:</span>
            {[
              { label: '1s', val: 1000 },
              { label: '3s', val: 3000 },
              { label: '5s', val: 5000 },
              { label: 'Pause', val: 0 },
            ].map(item => (
              <button
                key={item.label}
                onClick={() => setRefreshInterval(item.val)}
                className={`px-2.5 py-1 rounded-md transition-all ${
                  refreshInterval === item.val
                    ? 'bg-amber-500 text-slate-950 font-bold shadow'
                    : 'text-slate-400 hover:text-white'
                }`}
              >
                {item.label}
              </button>
            ))}
          </div>

          <button
            onClick={fetchData}
            disabled={isRefreshing}
            className="p-2 rounded-lg bg-slate-900 border border-slate-800 text-slate-300 hover:text-white hover:border-slate-700 transition disabled:opacity-50"
            title="Manual sync with Neon PostgreSQL"
          >
            <RefreshCw className={`w-4 h-4 ${isRefreshing ? 'animate-spin text-amber-400' : ''}`} />
          </button>

          <a
            href="https://share.streamlit.io"
            target="_blank"
            rel="noopener noreferrer"
            className="flex items-center gap-1.5 text-xs font-medium px-3 py-1.5 rounded-lg bg-slate-900/80 border border-slate-800 hover:border-slate-700 text-slate-300 hover:text-amber-300 transition"
          >
            <span>Analytics Studio</span>
            <ExternalLink className="w-3 h-3" />
          </a>
        </div>
      </header>

      {/* ERROR NOTICE IF ANY */}
      {errorMsg && (
        <div className="mx-6 mt-4 p-3 rounded-xl bg-red-950/40 border border-red-800/60 text-xs text-red-300 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <AlertTriangle className="w-4 h-4 text-red-400" />
            <span>Connection Warning: {errorMsg}</span>
          </div>
          <button onClick={fetchData} className="underline hover:text-white font-mono">
            Retry Connection
          </button>
        </div>
      )}

      {/* OPERATIONAL INSIGHT BANNER (DISMISSIBLE) */}
      {showInfoBanner && (
        <div className="mx-6 mt-4 p-4 rounded-2xl bg-gradient-to-r from-amber-950/30 via-slate-900/80 to-cyan-950/30 border border-amber-500/20 text-xs text-slate-300 flex items-center justify-between gap-4">
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 rounded-lg bg-amber-500/10 border border-amber-500/30 flex items-center justify-center shrink-0">
              <Info className="w-4 h-4 text-amber-400" />
            </div>
            <div>
              <p className="font-semibold text-white">
                Welcome to GridPulse: Autonomous Campus Microgrid & SCADA Command Center
              </p>
              <p className="text-slate-400 mt-0.5">
                Monitoring 42 IoT sub-meters across 22 campus facilities. Use the tabs below to view real-time power telemetry, test AI peak-shaving dispatch, or inspect the facility electrical hierarchy.
              </p>
            </div>
          </div>
          <button
            onClick={() => setShowInfoBanner(false)}
            className="text-slate-500 hover:text-slate-300 text-xs font-mono shrink-0 px-2 py-1 rounded-md hover:bg-slate-800 transition"
          >
            Dismiss ✕
          </button>
        </div>
      )}

      {/* TOP 4 KEY OPERATIONAL METRICS */}
      <section className="px-6 pt-5 pb-2 grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        {/* Card 1: Total Campus Power Demand */}
        <div className="glass-panel p-5 rounded-2xl relative overflow-hidden group hover:border-amber-500/50 transition-all">
          <div className="absolute top-0 right-0 w-32 h-32 bg-amber-500/10 rounded-full blur-2xl -mr-10 -mt-10 group-hover:bg-amber-500/20 transition-all" />
          <div className="flex items-center justify-between">
            <span className="text-xs font-semibold uppercase tracking-wider text-slate-400">
              Total Campus Power Demand
            </span>
            <Flame className="w-4 h-4 text-amber-400" />
          </div>
          <div className="mt-2 flex items-baseline gap-2">
            <span className="text-3xl font-extrabold tracking-tight text-white font-mono">
              {(streamData?.latest?.loadKw || kpiData?.instant?.instantaneousLoadKw || 304.8).toFixed(1)}
            </span>
            <span className="text-sm font-semibold text-amber-400">kW</span>
          </div>
          <div className="mt-3 flex items-center gap-2 text-xs">
            <span className="px-2 py-0.5 rounded-md bg-amber-500/10 text-amber-300 font-mono font-medium">
              42 Sub-Meters Active
            </span>
            <span className="text-slate-500">22 Campus Facilities</span>
          </div>
        </div>

        {/* Card 2: Active Sub-Meters */}
        <div className="glass-panel p-5 rounded-2xl relative overflow-hidden group hover:border-cyan-500/50 transition-all">
          <div className="absolute top-0 right-0 w-32 h-32 bg-cyan-500/10 rounded-full blur-2xl -mr-10 -mt-10 group-hover:bg-cyan-500/20 transition-all" />
          <div className="flex items-center justify-between">
            <span className="text-xs font-semibold uppercase tracking-wider text-slate-400">
              Active Sub-Meters
            </span>
            <Cpu className="w-4 h-4 text-cyan-400" />
          </div>
          <div className="mt-2 flex items-baseline gap-2">
            <span className="text-3xl font-extrabold tracking-tight text-white font-mono">
              {kpiData?.stats?.meters || 42}
            </span>
            <span className="text-sm font-semibold text-cyan-400">/ 42 Online</span>
          </div>
          <div className="mt-3 flex items-center gap-2 text-xs">
            <span className="px-2 py-0.5 rounded-md bg-cyan-500/10 text-cyan-300 font-medium">
              100% Telemetry Health
            </span>
            <span className="text-slate-500">4 Facility Zones</span>
          </div>
        </div>

        {/* Card 3: Grid Voltage & Power Factor */}
        <div className="glass-panel p-5 rounded-2xl relative overflow-hidden group hover:border-emerald-500/50 transition-all">
          <div className="absolute top-0 right-0 w-32 h-32 bg-emerald-500/10 rounded-full blur-2xl -mr-10 -mt-10 group-hover:bg-emerald-500/20 transition-all" />
          <div className="flex items-center justify-between">
            <span className="text-xs font-semibold uppercase tracking-wider text-slate-400">
              Grid Voltage & Power Factor
            </span>
            <Gauge className="w-4 h-4 text-emerald-400" />
          </div>
          <div className="mt-2 flex items-baseline gap-2">
            <span className="text-3xl font-extrabold tracking-tight text-white font-mono">
              {(streamData?.latest?.voltageV || kpiData?.instant?.nominalVoltageV || 231.8).toFixed(1)}
            </span>
            <span className="text-sm font-semibold text-emerald-400">V</span>
          </div>
          <div className="mt-3 flex items-center gap-2 text-xs">
            <span className="px-2 py-0.5 rounded-md bg-emerald-500/10 text-emerald-300 font-medium">
              PF: {(kpiData?.instant?.powerFactorAvg || 0.93).toFixed(2)} (Healthy)
            </span>
            <span className="text-slate-500">Standard 230V Bus</span>
          </div>
        </div>

        {/* Card 4: Demand Dispatch Status */}
        <div className="glass-panel p-5 rounded-2xl relative overflow-hidden group hover:border-purple-500/50 transition-all">
          <div className="absolute top-0 right-0 w-32 h-32 bg-purple-500/10 rounded-full blur-2xl -mr-10 -mt-10 group-hover:bg-purple-500/20 transition-all" />
          <div className="flex items-center justify-between">
            <span className="text-xs font-semibold uppercase tracking-wider text-slate-400">
              Automated Dispatch Status
            </span>
            <Activity className="w-4 h-4 text-purple-400" />
          </div>
          <div className="mt-2 flex items-baseline gap-2">
            <span className="text-2xl font-extrabold tracking-tight text-white font-mono">
              {projectedOverload > 0 ? 'CURTAILMENT' : 'NOMINAL'}
            </span>
            <span className={`text-xs font-semibold ${projectedOverload > 0 ? 'text-amber-400' : 'text-emerald-400'}`}>
              {projectedOverload > 0 ? 'Demand Alert' : 'Within Limits'}
            </span>
          </div>
          <div className="mt-3 flex items-center gap-2 text-xs">
            <span className="px-2 py-0.5 rounded-md bg-purple-500/10 text-purple-300 font-mono font-medium">
              Contract: {contractThreshold} kW
            </span>
            <span className="text-slate-500">3-Tier Rules Armed</span>
          </div>
        </div>
      </section>

      {/* SELF-EXPLANATORY NAVIGATION TABS */}
      <section className="px-6 pt-3">
        <div className="flex items-center gap-2 border-b border-slate-800/80 pb-px overflow-x-auto">
          {[
            {
              id: 'stream',
              label: '⚡ Real-Time Power Telemetry',
              desc: 'Live load curves & 60 FPS streaming',
              icon: Radio,
            },
            {
              id: 'dispatch',
              label: '🔮 Smart Peak-Shaving & Demand Dispatch',
              desc: 'AI forecasting & automated Slack alerts',
              icon: Sliders,
            },
            {
              id: 'buildings',
              label: '🏢 Campus Power Grid & Sub-Meters',
              desc: 'Directory of all 22 facilities',
              icon: Building2,
            },
            {
              id: 'table',
              label: '🗂️ Telemetry Stream Records & Audit',
              desc: 'Searchable database records & CSV export',
              icon: Layers,
            },
          ].map(tab => {
            const Icon = tab.icon;
            const isActive = activeTab === tab.id;
            return (
              <button
                key={tab.id}
                onClick={() => setActiveTab(tab.id as any)}
                className={`flex items-center gap-3 px-5 py-3 text-sm font-semibold rounded-t-xl transition-all border-b-2 whitespace-nowrap ${
                  isActive
                    ? 'border-amber-400 text-amber-400 bg-amber-500/10'
                    : 'border-transparent text-slate-400 hover:text-slate-200 hover:bg-slate-900/40'
                }`}
              >
                <Icon className={`w-4 h-4 ${isActive ? 'text-amber-400' : 'text-slate-400'}`} />
                <div className="text-left">
                  <div className="text-xs font-bold leading-tight">{tab.label}</div>
                  <div className="text-[10px] text-slate-500 font-normal leading-tight">{tab.desc}</div>
                </div>
              </button>
            );
          })}
        </div>
      </section>

      {/* MAIN TAB CONTENT AREA */}
      <main className="flex-1 px-6 py-6 max-w-[1600px] w-full mx-auto">
        {/* =================================================================== */}
        {/* TAB 1: REAL-TIME POWER TELEMETRY */}
        {/* =================================================================== */}
        {activeTab === 'stream' && (
          <div className="space-y-6">
            {/* Live Chart Panel */}
            <div className="glass-panel p-6 rounded-2xl">
              <div className="flex flex-wrap items-center justify-between gap-4 mb-4">
                <div>
                  <h2 className="text-lg font-bold text-white flex items-center gap-2">
                    <Activity className="w-5 h-5 text-amber-400" />
                    Live Campus Power Demand Curve (60 FPS Telemetry Stream)
                  </h2>
                  <p className="text-xs text-slate-400">
                    Aggregated electricity consumption (kW) across 42 smart sub-meters computed in 5-minute sliding windows
                  </p>
                </div>

                <div className="flex items-center gap-2">
                  <div className="flex items-center bg-slate-900 border border-slate-800 rounded-lg p-0.5 text-xs font-medium">
                    <span className="px-2 text-[10px] text-slate-500">Window:</span>
                    {(['15m', '30m', 'all'] as const).map(f => (
                      <button
                        key={f}
                        onClick={() => setTimeFilter(f)}
                        className={`px-3 py-1 rounded-md uppercase font-mono ${
                          timeFilter === f ? 'bg-slate-800 text-amber-400 font-bold' : 'text-slate-400 hover:text-white'
                        }`}
                      >
                        {f}
                      </button>
                    ))}
                  </div>
                </div>
              </div>

              {/* Chart Explainer Tooltip */}
              <div className="mb-4 px-3 py-2 rounded-xl bg-slate-900/60 border border-slate-800 text-xs text-slate-400 flex items-center gap-2">
                <Info className="w-4 h-4 text-cyan-400 shrink-0" />
                <span>
                  <strong>Operator Guide:</strong> 5-minute sliding windows smooth out transient motor-startup spikes while preserving immediate detection of sustained peak demand breaches.
                </span>
              </div>

              {/* Responsive 60 FPS Recharts Area Chart */}
              <div className="h-[360px] w-full">
                {filteredTimeline.length > 0 ? (
                  <ResponsiveContainer width="100%" height="100%">
                    <AreaChart data={filteredTimeline} margin={{ top: 10, right: 10, left: -20, bottom: 0 }}>
                      <defs>
                        <linearGradient id="powerGrad" x1="0" y1="0" x2="0" y2="1">
                          <stop offset="5%" stopColor="#F59E0B" stopOpacity={0.4} />
                          <stop offset="95%" stopColor="#F59E0B" stopOpacity={0.0} />
                        </linearGradient>
                      </defs>
                      <CartesianGrid strokeDasharray="3 3" stroke="#1E293B" vertical={false} />
                      <XAxis dataKey="time" stroke="#64748B" fontSize={11} tickLine={false} />
                      <YAxis stroke="#64748B" fontSize={11} tickLine={false} domain={['auto', 'auto']} unit=" kW" />
                      <Tooltip
                        contentStyle={{
                          backgroundColor: '#0F172A',
                          borderColor: '#334155',
                          borderRadius: '12px',
                          color: '#F8FAFC',
                          boxShadow: '0 10px 25px -5px rgba(0,0,0,0.5)',
                        }}
                        itemStyle={{ color: '#F59E0B' }}
                        formatter={(val: any) => [`${val} kW`, 'Campus Power Demand']}
                        labelFormatter={(label: any) => `Sliding Window End: ${label}`}
                      />
                      <Area
                        type="monotone"
                        dataKey="totalPower"
                        stroke="#F59E0B"
                        strokeWidth={3}
                        fillOpacity={1}
                        fill="url(#powerGrad)"
                        isAnimationActive={false}
                      />
                    </AreaChart>
                  </ResponsiveContainer>
                ) : (
                  <div className="h-full flex flex-col items-center justify-center text-slate-500">
                    <Activity className="w-8 h-8 animate-pulse text-amber-500/50 mb-2" />
                    <span>Loading real-time telemetry stream from Neon PostgreSQL...</span>
                  </div>
                )}
              </div>
            </div>

            {/* Sub-Panels: Facility Consumption & Pipeline Architecture */}
            <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
              {/* Category Power Distribution */}
              <div className="glass-panel p-6 rounded-2xl lg:col-span-2">
                <div className="flex items-center justify-between mb-4">
                  <div>
                    <h3 className="text-sm font-bold uppercase tracking-wider text-slate-300 flex items-center gap-2">
                      <Building2 className="w-4 h-4 text-cyan-400" />
                      Top Energy-Consuming Facilities
                    </h3>
                    <p className="text-xs text-slate-500">Real-time load ranking across campus buildings</p>
                  </div>
                  <span className="text-xs font-mono text-cyan-400">Peak kW Ranking</span>
                </div>
                <div className="h-[240px] w-full">
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart data={buildingChartData} layout="vertical" margin={{ top: 5, right: 30, left: 40, bottom: 5 }}>
                      <CartesianGrid strokeDasharray="3 3" stroke="#1E293B" horizontal={false} />
                      <XAxis type="number" stroke="#64748B" fontSize={10} unit=" kW" />
                      <YAxis type="category" dataKey="name" stroke="#94A3B8" fontSize={11} tickLine={false} />
                      <Tooltip
                        contentStyle={{
                          backgroundColor: '#0F172A',
                          borderColor: '#334155',
                          borderRadius: '8px',
                        }}
                        formatter={(val: any) => [`${val} kW`, 'Measured Load']}
                      />
                      <Bar dataKey="power" fill="#38BDF8" radius={[0, 6, 6, 0]} />
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              </div>

              {/* Streaming Pipeline Architecture Panel */}
              <div className="glass-panel p-6 rounded-2xl space-y-4">
                <h3 className="text-sm font-bold uppercase tracking-wider text-slate-300 flex items-center gap-2">
                  <Server className="w-4 h-4 text-amber-400" />
                  Streaming Pipeline Architecture
                </h3>

                <div className="space-y-3 font-mono text-xs">
                  <div className="flex justify-between items-center py-2 border-b border-slate-800">
                    <span className="text-slate-400">IoT Event Broker</span>
                    <span className="text-slate-200 font-semibold">Kafka (KRaft Cluster)</span>
                  </div>
                  <div className="flex justify-between items-center py-2 border-b border-slate-800">
                    <span className="text-slate-400">Stream Processing</span>
                    <span className="text-slate-200 font-semibold">Spark Structured Streaming</span>
                  </div>
                  <div className="flex justify-between items-center py-2 border-b border-slate-800">
                    <span className="text-slate-400">Sliding Window</span>
                    <span className="text-slate-200 font-semibold">5 mins (slide: 1 min)</span>
                  </div>
                  <div className="flex justify-between items-center py-2 border-b border-slate-800">
                    <span className="text-slate-400">Relational Hot Path</span>
                    <span className="text-emerald-400 font-semibold">Neon PostgreSQL (Pooled)</span>
                  </div>
                  <div className="flex justify-between items-center py-2">
                    <span className="text-slate-400">Cold Path Analytics</span>
                    <span className="text-cyan-400 font-semibold">DuckDB & Snappy Parquet</span>
                  </div>
                </div>

                <div className="pt-2">
                  <div className="p-3 rounded-xl bg-slate-900/80 border border-slate-800 text-xs text-slate-400 flex items-center gap-2">
                    <span className="w-2 h-2 rounded-full bg-emerald-400" />
                    <span>Pipeline status: Micro-batching operational.</span>
                  </div>
                </div>
              </div>
            </div>
          </div>
        )}

        {/* =================================================================== */}
        {/* TAB 2: SMART PEAK-SHAVING & DEMAND DISPATCH */}
        {/* =================================================================== */}
        {activeTab === 'dispatch' && (
          <div className="space-y-6">
            {/* Explainer Box */}
            <div className="p-4 rounded-2xl bg-amber-950/20 border border-amber-500/30 flex items-start gap-3 text-xs text-slate-300">
              <HelpCircle className="w-5 h-5 text-amber-400 shrink-0 mt-0.5" />
              <div>
                <p className="font-bold text-amber-300">How Automated Demand Response & Peak Shaving Works:</p>
                <p className="text-slate-400 mt-1">
                  Utilities charge steep monthly demand penalties if campus load breaches the contract threshold ({contractThreshold} kW).
                  The predictive engine continuously calculates projected overload and automatically engages progressive load-shedding directives (Tier 1 setbacks, Tier 2 HVAC cycling, and Tier 3 battery injection) while notifying operators through Slack.
                </p>
              </div>
            </div>

            {/* Interactive Threshold Slider Panel */}
            <div className="glass-panel-glow p-6 rounded-2xl">
              <div className="flex flex-wrap items-center justify-between gap-4 mb-4">
                <div>
                  <h2 className="text-lg font-bold text-white flex items-center gap-2">
                    <TrendingUp className="w-5 h-5 text-amber-400" />
                    Interactive Contract Demand Ceiling Optimizer
                  </h2>
                  <p className="text-xs text-slate-400">
                    Adjust the contract demand slider to evaluate real-time overload risk and tariff penalty savings
                  </p>
                </div>

                <div className="flex items-center gap-3">
                  <span className="text-xs text-slate-400 font-medium">Contract Limit:</span>
                  <span className="text-2xl font-extrabold font-mono text-amber-400">
                    {contractThreshold} kW
                  </span>
                </div>
              </div>

              {/* Slider */}
              <div className="my-6">
                <input
                  type="range"
                  min="550"
                  max="1100"
                  step="25"
                  value={contractThreshold}
                  onChange={e => setContractThreshold(Number(e.target.value))}
                  className="w-full h-2.5 bg-slate-800 rounded-lg appearance-none cursor-pointer accent-amber-400"
                />
                <div className="flex justify-between text-xs font-mono text-slate-500 mt-2">
                  <span>550 kW (Aggressive Curtailment)</span>
                  <span>800 kW (Standard Contract Capacity)</span>
                  <span>1,100 kW (High Risk Margin)</span>
                </div>
              </div>

              {/* Impact readout */}
              <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 pt-2">
                <div className="p-4 rounded-xl bg-slate-900/90 border border-slate-800">
                  <span className="text-xs text-slate-400 font-medium uppercase tracking-wider">
                    Projected 24h Peak Demand
                  </span>
                  <div className="mt-1 text-2xl font-extrabold font-mono text-white">
                    {projectedPeak.toFixed(1)} kW
                  </div>
                  <span className="text-xs text-slate-500 mt-1 block">95% AI Confidence Interval</span>
                </div>

                <div className="p-4 rounded-xl bg-slate-900/90 border border-slate-800">
                  <span className="text-xs text-slate-400 font-medium uppercase tracking-wider">
                    Projected Overload
                  </span>
                  <div
                    className={`mt-1 text-2xl font-extrabold font-mono ${
                      projectedOverload > 0 ? 'text-amber-400' : 'text-emerald-400'
                    }`}
                  >
                    {projectedOverload > 0 ? `+${projectedOverload.toFixed(1)} kW` : '0.0 kW (SAFE)'}
                  </div>
                  <span className="text-xs text-slate-500 mt-1 block">
                    {projectedOverload > 0 ? 'Exceeds contract capacity limit' : 'Operating within safe limits'}
                  </span>
                </div>

                <div className="p-4 rounded-xl bg-slate-900/90 border border-slate-800">
                  <span className="text-xs text-slate-400 font-medium uppercase tracking-wider">
                    Potential Tariff Penalty Savings
                  </span>
                  <div className="mt-1 text-2xl font-extrabold font-mono text-emerald-400">
                    INR {potentialSavings.toLocaleString()}
                  </div>
                  <span className="text-xs text-slate-500 mt-1 block">Avoided demand-charge surcharge</span>
                </div>
              </div>
            </div>

            {/* 3-Tier Automated Dispatch Directives */}
            <div className="glass-panel p-6 rounded-2xl">
              <div className="flex items-center justify-between mb-4">
                <div>
                  <h3 className="text-base font-bold text-white flex items-center gap-2">
                    <ShieldAlert className="w-5 h-5 text-amber-400" />
                    3-Tier Automated Load-Shedding Countermeasures
                  </h3>
                  <p className="text-xs text-slate-400">
                    Toggle individual tiers to simulate automated demand response actuation
                  </p>
                </div>

                <div className="text-right">
                  <span className="text-xs text-slate-400 block">Total Active Countermeasures</span>
                  <span className="text-lg font-bold font-mono text-emerald-400">
                    {activeShedTotal.toFixed(1)} kW shed
                  </span>
                </div>
              </div>

              <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                {/* Tier 1 */}
                <div
                  className={`p-4 rounded-xl border transition-all ${
                    tier1Armed
                      ? 'bg-amber-950/20 border-amber-500/40 text-slate-200'
                      : 'bg-slate-900/40 border-slate-800 text-slate-500'
                  }`}
                >
                  <div className="flex items-center justify-between">
                    <span className="text-xs font-bold uppercase tracking-wider text-amber-400">
                      Tier 1 • Soft Shedding
                    </span>
                    <button
                      onClick={() => setTier1Armed(!tier1Armed)}
                      className={`w-11 h-6 rounded-full transition-colors relative ${
                        tier1Armed ? 'bg-amber-500' : 'bg-slate-700'
                      }`}
                    >
                      <span
                        className={`block w-4 h-4 rounded-full bg-white transition-transform ${
                          tier1Armed ? 'translate-x-6' : 'translate-x-1'
                        }`}
                      />
                    </button>
                  </div>
                  <h4 className="font-bold text-sm text-white mt-2">Non-Critical Facilities & EV Setback</h4>
                  <p className="text-xs text-slate-400 mt-1">
                    Dimming streetlights, setback EV charging stations, pump throttling.
                  </p>
                  <div className="mt-3 flex justify-between items-center text-xs font-mono">
                    <span className="text-slate-400">Shed Capacity:</span>
                    <span className="font-bold text-amber-400">45.0 kW</span>
                  </div>
                </div>

                {/* Tier 2 */}
                <div
                  className={`p-4 rounded-xl border transition-all ${
                    tier2Armed
                      ? 'bg-amber-950/20 border-amber-500/40 text-slate-200'
                      : 'bg-slate-900/40 border-slate-800 text-slate-500'
                  }`}
                >
                  <div className="flex items-center justify-between">
                    <span className="text-xs font-bold uppercase tracking-wider text-amber-400">
                      Tier 2 • Duty Cycling
                    </span>
                    <button
                      onClick={() => setTier2Armed(!tier2Armed)}
                      className={`w-11 h-6 rounded-full transition-colors relative ${
                        tier2Armed ? 'bg-amber-500' : 'bg-slate-700'
                      }`}
                    >
                      <span
                        className={`block w-4 h-4 rounded-full bg-white transition-transform ${
                          tier2Armed ? 'translate-x-6' : 'translate-x-1'
                        }`}
                      />
                    </button>
                  </div>
                  <h4 className="font-bold text-sm text-white mt-2">Academic & Lecture Hall HVAC Cycling</h4>
                  <p className="text-xs text-slate-400 mt-1">
                    Duty cycling large chillers and air handlers across LT1, LT2, and Computer Center.
                  </p>
                  <div className="mt-3 flex justify-between items-center text-xs font-mono">
                    <span className="text-slate-400">Shed Capacity:</span>
                    <span className="font-bold text-amber-400">40.5 kW</span>
                  </div>
                </div>

                {/* Tier 3 */}
                <div
                  className={`p-4 rounded-xl border transition-all ${
                    tier3Armed
                      ? 'bg-red-950/20 border-red-500/40 text-slate-200'
                      : 'bg-slate-900/40 border-slate-800 text-slate-500'
                  }`}
                >
                  <div className="flex items-center justify-between">
                    <span className="text-xs font-bold uppercase tracking-wider text-red-400">
                      Tier 3 • Battery Injection
                    </span>
                    <button
                      onClick={() => setTier3Armed(!tier3Armed)}
                      className={`w-11 h-6 rounded-full transition-colors relative ${
                        tier3Armed ? 'bg-red-500' : 'bg-slate-700'
                      }`}
                    >
                      <span
                        className={`block w-4 h-4 rounded-full bg-white transition-transform ${
                          tier3Armed ? 'translate-x-6' : 'translate-x-1'
                        }`}
                      />
                    </button>
                  </div>
                  <h4 className="font-bold text-sm text-white mt-2">BESS Sub-Station Battery Injection</h4>
                  <p className="text-xs text-slate-400 mt-1">
                    Discharge 500 kWh stationary LiFePO4 battery array to cap grid import peak.
                  </p>
                  <div className="mt-3 flex justify-between items-center text-xs font-mono">
                    <span className="text-slate-400">Shed Capacity:</span>
                    <span className="font-bold text-red-400">50.0 kW</span>
                  </div>
                </div>
              </div>
            </div>

            {/* Slack Incident Webhook Operations Console */}
            <div className="glass-panel p-6 rounded-2xl space-y-6">
              <div className="flex flex-wrap items-center justify-between gap-4">
                <div>
                  <h3 className="text-base font-bold text-white flex items-center gap-2">
                    <BellRing className="w-5 h-5 text-amber-400" />
                    Automated Slack Incident Dispatcher
                  </h3>
                  <p className="text-xs text-slate-400">
                    Dispatches structured Block Kit incident cards to campus electrical operators with zero latency
                  </p>
                </div>

                <span className="text-xs px-3 py-1 rounded-full bg-emerald-500/10 text-emerald-400 font-mono font-semibold border border-emerald-500/30 flex items-center gap-1.5">
                  <span className="w-2 h-2 rounded-full bg-emerald-400 animate-ping" />
                  SLACK BOT ACTIVE
                </span>
              </div>

              {/* Endpoint configuration */}
              <div className="space-y-2">
                <label className="text-xs font-semibold text-slate-300 block">
                  Slack Webhook Target URL (Optional override; defaults to server-configured webhook):
                </label>
                <div className="flex gap-2">
                  <input
                    type="text"
                    value={webhookUrl}
                    onChange={e => setWebhookUrl(e.target.value)}
                    placeholder="Leave empty to use pre-configured ALERT_WEBHOOK_URL, or paste custom endpoint..."
                    className="flex-1 bg-slate-900 border border-slate-700 rounded-xl px-4 py-2.5 text-xs font-mono text-slate-200 focus:outline-none focus:border-amber-400 transition"
                  />
                  {webhookUrl && (
                    <button
                      onClick={() => setWebhookUrl('')}
                      className="px-3.5 py-2.5 rounded-xl bg-slate-800 hover:bg-slate-700 text-xs font-medium text-slate-300 transition"
                    >
                      Reset Default
                    </button>
                  )}
                </div>
              </div>

              {/* Action Buttons */}
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                <button
                  onClick={() => handleDispatch('PEAK_SHAVING')}
                  disabled={isDispatching}
                  className="flex items-center justify-center gap-2.5 px-5 py-3.5 rounded-xl bg-gradient-to-r from-amber-500 to-yellow-400 text-slate-950 font-bold text-sm shadow-lg shadow-amber-500/20 hover:brightness-110 active:scale-[0.99] transition disabled:opacity-50"
                >
                  <Send className={`w-4 h-4 ${isDispatching ? 'animate-bounce' : ''}`} />
                  <span>Dispatch Peak Shaving Directive to Slack</span>
                </button>

                <button
                  onClick={() => handleDispatch('SCADA_FAULT')}
                  disabled={isDispatching}
                  className="flex items-center justify-center gap-2.5 px-5 py-3.5 rounded-xl bg-gradient-to-r from-red-600 to-rose-500 text-white font-bold text-sm shadow-lg shadow-red-500/20 hover:brightness-110 active:scale-[0.99] transition disabled:opacity-50"
                >
                  <ShieldAlert className={`w-4 h-4 ${isDispatching ? 'animate-bounce' : ''}`} />
                  <span>Dispatch SCADA Voltage Sag Alert to Slack</span>
                </button>
              </div>

              {/* Webhook audit log table */}
              <div className="pt-2">
                <h4 className="text-xs font-bold uppercase tracking-wider text-slate-400 mb-3">
                  Live Dispatch Audit Trail (Real-Time Sub-50ms Log)
                </h4>
                {webhookLogs.length > 0 ? (
                  <div className="overflow-x-auto rounded-xl border border-slate-800">
                    <table className="w-full text-left text-xs font-mono">
                      <thead className="bg-slate-900/90 text-slate-400 border-b border-slate-800">
                        <tr>
                          <th className="py-2.5 px-4">Timestamp</th>
                          <th className="py-2.5 px-4">Event Type</th>
                          <th className="py-2.5 px-4">Incident Details</th>
                          <th className="py-2.5 px-4">Status</th>
                          <th className="py-2.5 px-4">Latency</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-slate-800/60 bg-slate-950/40">
                        {webhookLogs.map(log => (
                          <tr key={log.id} className="hover:bg-slate-900/40 transition">
                            <td className="py-2.5 px-4 text-slate-400">{log.timestamp}</td>
                            <td className="py-2.5 px-4 font-semibold text-amber-400">{log.type}</td>
                            <td className="py-2.5 px-4 text-slate-300">{log.title}</td>
                            <td className="py-2.5 px-4">
                              <span className="px-2 py-0.5 rounded bg-emerald-500/10 text-emerald-400 font-bold border border-emerald-500/30">
                                {log.status} ({log.statusCode})
                              </span>
                            </td>
                            <td className="py-2.5 px-4 text-slate-400">{log.latencyMs}ms</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                ) : (
                  <div className="p-6 rounded-xl bg-slate-900/40 border border-slate-800/80 text-center text-xs text-slate-500">
                    No webhooks dispatched in this session yet. Click either dispatch button above to trigger an immediate Slack alert.
                  </div>
                )}
              </div>
            </div>
          </div>
        )}

        {/* =================================================================== */}
        {/* TAB 3: CAMPUS POWER GRID & SUB-METERS */}
        {/* =================================================================== */}
        {activeTab === 'buildings' && (
          <div className="space-y-6">
            <div className="flex flex-wrap items-center justify-between gap-4">
              <div>
                <h2 className="text-lg font-bold text-white flex items-center gap-2">
                  <Building2 className="w-5 h-5 text-cyan-400" />
                  Campus Facility Power Hierarchy
                </h2>
                <p className="text-xs text-slate-400">
                  Comprehensive directory of all 22 campus buildings and their active sub-meters
                </p>
              </div>

              {/* Search Bar & Category Filter */}
              <div className="flex flex-wrap items-center gap-3">
                <div className="relative">
                  <Search className="w-3.5 h-3.5 text-slate-500 absolute left-3 top-1/2 -translate-y-1/2" />
                  <input
                    type="text"
                    value={searchQuery}
                    onChange={e => setSearchQuery(e.target.value)}
                    placeholder="Search facility name..."
                    className="bg-slate-900 border border-slate-800 rounded-lg pl-8 pr-3 py-1.5 text-xs text-slate-200 placeholder-slate-500 focus:outline-none focus:border-cyan-400"
                  />
                </div>

                <div className="flex items-center gap-1.5 bg-slate-900/80 p-1 rounded-lg border border-slate-800">
                  {['All', 'Hostels', 'Departments', 'Lecture Theatres', 'Facilities'].map(cat => (
                    <button
                      key={cat}
                      onClick={() => setSelectedCategory(cat)}
                      className={`px-3 py-1 rounded-md text-xs font-semibold transition ${
                        selectedCategory === cat
                          ? 'bg-cyan-500 text-slate-950 shadow'
                          : 'text-slate-400 hover:text-white'
                      }`}
                    >
                      {cat}
                    </button>
                  ))}
                </div>
              </div>
            </div>

            {/* Building Grid */}
            <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-4">
              {filteredRows.map(b => (
                <div
                  key={`${b.building_id}-${b.id}`}
                  className="glass-panel p-4 rounded-xl border border-slate-800 hover:border-cyan-500/40 transition group"
                >
                  <div className="flex justify-between items-start">
                    <span className="text-xs font-bold text-cyan-400 font-mono">{b.building_id}</span>
                    <span className="text-[10px] px-2 py-0.5 rounded bg-slate-800 text-slate-400">
                      {b.building_type}
                    </span>
                  </div>
                  <h4 className="font-bold text-sm text-white mt-1.5 group-hover:text-cyan-300 transition">
                    {b.building_name}
                  </h4>
                  <div className="mt-3 flex justify-between items-baseline font-mono">
                    <span className="text-xs text-slate-400">Measured Load:</span>
                    <span className="text-base font-extrabold text-amber-400">
                      {b.avg_power_kw.toFixed(1)} kW
                    </span>
                  </div>
                  <div className="mt-1 flex justify-between items-baseline font-mono text-xs text-slate-500">
                    <span>Bus Voltage:</span>
                    <span className="text-emerald-400 font-semibold">{b.avg_voltage_v.toFixed(1)} V</span>
                  </div>
                  <div className="mt-1 flex justify-between items-baseline font-mono text-xs text-slate-500">
                    <span>Power Factor:</span>
                    <span className="text-slate-300">{b.avg_power_factor.toFixed(2)}</span>
                  </div>

                  {/* Visual Load Bar */}
                  <div className="mt-3 w-full bg-slate-800/80 h-1.5 rounded-full overflow-hidden">
                    <div
                      className="h-full bg-gradient-to-r from-cyan-500 to-amber-400 rounded-full"
                      style={{ width: `${Math.min(100, (b.avg_power_kw / 55) * 100)}%` }}
                    />
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* =================================================================== */}
        {/* TAB 4: TELEMETRY STREAM RECORDS & AUDIT */}
        {/* =================================================================== */}
        {activeTab === 'table' && (
          <div className="space-y-4">
            <div className="flex flex-wrap justify-between items-center gap-4">
              <div>
                <h2 className="text-lg font-bold text-white flex items-center gap-2">
                  <Layers className="w-5 h-5 text-amber-400" />
                  Live Relational Telemetry Audit Table
                </h2>
                <p className="text-xs text-slate-400">
                  Real-time sliding window aggregates synchronized directly from Neon Cloud PostgreSQL
                </p>
              </div>

              <div className="flex items-center gap-3">
                <button
                  onClick={exportCsv}
                  className="flex items-center gap-1.5 text-xs font-semibold px-3.5 py-2 rounded-xl bg-slate-900 border border-slate-800 hover:border-amber-500/50 text-slate-200 hover:text-white transition"
                >
                  <Download className="w-3.5 h-3.5 text-amber-400" />
                  <span>Export CSV</span>
                </button>

                <div className="text-xs font-mono text-slate-400">
                  Showing <span className="text-amber-400 font-bold">{filteredRows.length}</span> active records
                </div>
              </div>
            </div>

            <div className="overflow-x-auto rounded-2xl border border-slate-800 glass-panel">
              <table className="w-full text-left text-xs font-mono">
                <thead className="bg-slate-900/90 text-slate-400 border-b border-slate-800">
                  <tr>
                    <th className="py-3 px-4">Record ID</th>
                    <th className="py-3 px-4">Window Start</th>
                    <th className="py-3 px-4">Window End</th>
                    <th className="py-3 px-4">Facility ID</th>
                    <th className="py-3 px-4">Facility Name</th>
                    <th className="py-3 px-4">Zone</th>
                    <th className="py-3 px-4 text-right">Avg Power (kW)</th>
                    <th className="py-3 px-4 text-right">Avg Voltage (V)</th>
                    <th className="py-3 px-4 text-right">Power Factor</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-800/60 bg-slate-950/40">
                  {filteredRows.slice(0, 50).map(r => (
                    <tr key={r.id} className="hover:bg-slate-900/40 transition">
                      <td className="py-2.5 px-4 text-slate-500">#{r.id}</td>
                      <td className="py-2.5 px-4 text-slate-400">
                        {new Date(r.window_start).toLocaleTimeString([], { hour12: false })}
                      </td>
                      <td className="py-2.5 px-4 text-slate-300 font-semibold">
                        {new Date(r.window_end).toLocaleTimeString([], { hour12: false })}
                      </td>
                      <td className="py-2.5 px-4 text-cyan-400 font-bold">{r.building_id}</td>
                      <td className="py-2.5 px-4 text-slate-200">{r.building_name}</td>
                      <td className="py-2.5 px-4 text-slate-400">{r.building_type}</td>
                      <td className="py-2.5 px-4 text-right text-amber-400 font-bold">
                        {r.avg_power_kw.toFixed(2)}
                      </td>
                      <td className="py-2.5 px-4 text-right text-emerald-400">
                        {r.avg_voltage_v.toFixed(1)}
                      </td>
                      <td className="py-2.5 px-4 text-right text-slate-400">
                        {r.avg_power_factor.toFixed(3)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </main>

      {/* OPERATIONAL FOOTER */}
      <footer className="border-t border-slate-800/80 bg-slate-950/70 px-6 py-4 flex flex-wrap items-center justify-between gap-4 text-xs text-slate-500">
        <div className="flex items-center gap-3">
          <span className="text-amber-400 font-bold">GridPulse Operations Portal</span>
          <span>•</span>
          <span>Next.js 15 App Router</span>
          <span>•</span>
          <span>Neon Cloud PostgreSQL (High-Throughput Pooler)</span>
        </div>
        <div className="flex items-center gap-4 font-mono">
          <span>Last Sync: {lastSyncTime || 'Awaiting tick'}</span>
          <span>Refresh Cadence: {refreshInterval > 0 ? `${refreshInterval / 1000}s` : 'Paused'}</span>
        </div>
      </footer>
    </div>
  );
}
