import { useState, useEffect, useCallback } from 'react';
import { X, RefreshCw, TrendingUp, FileDown } from 'lucide-react';
import { Container, ContainerMetrics } from '../../types';
import { format } from 'date-fns';
import { api } from '../../services/api';
import { toast } from 'sonner';
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend } from 'recharts';

type MetricType = 'cpu' | 'memory' | 'network' | 'disk' | 'pids';
type TimePeriod = '1h' | '6h' | '24h' | '7d' | '30d';

interface MetricsHistoryDataPoint {
  timestamp: string;
  cpu_percent: number;
  memory_usage: number;
  memory_limit: number;
  memory_percent: number;
  network_rx: number;
  network_tx: number;
  block_read: number;
  block_write: number;
  pids: number;
}

interface MetricsTabProps {
  container: Container;
}

export default function MetricsTab({ container }: MetricsTabProps) {
  const [metrics, setMetrics] = useState<ContainerMetrics | null>(null);
  const [loadingMetrics, setLoadingMetrics] = useState(false);
  const [selectedMetric, setSelectedMetric] = useState<MetricType | null>(null);
  const [timePeriod, setTimePeriod] = useState<TimePeriod>('24h');
  const [historyData, setHistoryData] = useState<MetricsHistoryDataPoint[]>([]);
  const [loadingHistory, setLoadingHistory] = useState(false);
  const [compareMetrics, setCompareMetrics] = useState(false);

  const formatBytes = (bytes: number) => {
    if (bytes === 0) return '0 B';
    const k = 1024;
    const sizes = ['B', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return `${(bytes / Math.pow(k, i)).toFixed(2)} ${sizes[i]}`;
  };

  const loadMetrics = useCallback(async () => {
    setLoadingMetrics(true);
    try {
      const data = await api.containers.getMetrics(container.id);
      setMetrics(data);
    } catch (error) {
      console.error('Failed to load metrics:', error);
      setMetrics(null);
    } finally {
      setLoadingMetrics(false);
    }
  }, [container.id]);

  const loadHistoricalData = useCallback(async () => {
    setLoadingHistory(true);
    try {
      const response = await fetch(`/api/v1/containers/${container.id}/metrics/history?period=${timePeriod}`);
      if (!response.ok) throw new Error('Failed to fetch history');
      const data = await response.json();
      setHistoryData(data);
    } catch (error) {
      console.error('Failed to load historical data:', error);
      setHistoryData([]);
    } finally {
      setLoadingHistory(false);
    }
  }, [container.id, timePeriod]);

  useEffect(() => {
    loadMetrics();
  }, [loadMetrics]);

  useEffect(() => {
    if (selectedMetric) {
      loadHistoricalData();
    }
  }, [selectedMetric, timePeriod, loadHistoricalData]);

  const exportMetricsToCSV = () => {
    if (historyData.length === 0) {
      toast.error('No metrics data to export');
      return;
    }

    try {
      const headers = [
        'Timestamp', 'CPU %', 'Memory Usage (bytes)', 'Memory Limit (bytes)',
        'Memory %', 'Network RX (bytes)', 'Network TX (bytes)',
        'Block Read (bytes)', 'Block Write (bytes)', 'PIDs'
      ];

      const rows = historyData.map(point => [
        point.timestamp, point.cpu_percent, point.memory_usage, point.memory_limit,
        point.memory_percent, point.network_rx, point.network_tx,
        point.block_read, point.block_write, point.pids
      ]);

      const csvContent = [headers.join(','), ...rows.map(row => row.join(','))].join('\n');

      const timestamp = format(new Date(), 'yyyy-MM-dd-HHmmss');
      const filename = `${container.name}-metrics-${timePeriod}-${timestamp}.csv`;
      const blob = new Blob([csvContent], { type: 'text/csv' });
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = filename;
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      URL.revokeObjectURL(url);

      toast.success(`Metrics exported as ${filename}`);
    } catch (error) {
      console.error('Failed to export metrics:', error);
      toast.error('Failed to export metrics');
    }
  };

  if (loadingMetrics) {
    return (
      <div className="flex items-center justify-center py-12">
        <RefreshCw className="w-8 h-8 text-primary animate-spin" />
      </div>
    );
  }

  if (selectedMetric) {
    return (
      <div>
        {/* Back button and time period selector */}
        <div className="mb-4 flex items-center justify-between">
          <button
            onClick={() => setSelectedMetric(null)}
            className="text-primary hover:text-primary/80 transition-colors flex items-center gap-2"
          >
            <X className="w-4 h-4" />
            Back to Metrics
          </button>
          <div className="flex gap-2">
            {(['1h', '6h', '24h', '7d', '30d'] as TimePeriod[]).map((period) => (
              <button
                key={period}
                onClick={() => setTimePeriod(period)}
                className={`px-3 py-1 rounded-lg text-sm transition-colors ${
                  timePeriod === period
                    ? 'bg-primary text-tide-text'
                    : 'bg-tide-surface-light text-tide-text hover:bg-gray-500'
                }`}
              >
                {period}
              </button>
            ))}
          </div>
        </div>

        {/* Chart view */}
        <div className="bg-tide-surface/50 rounded-lg p-6">
          <div className="flex items-center justify-between mb-6">
            <h3 className="text-xl font-semibold text-tide-text capitalize">{selectedMetric} History</h3>
            <div className="flex items-center gap-3">
              {(selectedMetric === 'cpu' || selectedMetric === 'memory') && (
                <button
                  onClick={() => setCompareMetrics(!compareMetrics)}
                  className={`flex items-center gap-2 px-3 py-2 rounded-lg text-sm transition-colors ${
                    compareMetrics
                      ? 'bg-primary text-tide-text'
                      : 'bg-tide-surface-light text-tide-text hover:bg-gray-500'
                  }`}
                >
                  <TrendingUp className="w-4 h-4" />
                  {compareMetrics ? 'Comparing' : 'Compare'}
                </button>
              )}
              <button
                onClick={exportMetricsToCSV}
                disabled={historyData.length === 0}
                className="flex items-center gap-2 px-3 py-2 bg-tide-surface-light hover:bg-gray-500 text-tide-text rounded-lg text-sm transition-colors disabled:opacity-50"
              >
                <FileDown className="w-4 h-4" />
                Export CSV
              </button>
            </div>
          </div>
          {loadingHistory ? (
            <div className="flex items-center justify-center h-64">
              <RefreshCw className="w-8 h-8 text-primary animate-spin" />
            </div>
          ) : historyData.length === 0 ? (
            <div className="flex items-center justify-center h-64 text-tide-text-muted">
              <p>No historical data available yet. Data will be collected every 5 minutes.</p>
            </div>
          ) : (
            <div className="h-80">
              <ResponsiveContainer width="100%" height="100%">
                {selectedMetric === 'cpu' && (
                  <LineChart data={historyData}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
                    <XAxis dataKey="timestamp" stroke="#9CA3AF" tickFormatter={(value) => format(new Date(value), 'HH:mm')} />
                    <YAxis yAxisId="left" stroke="#9CA3AF" label={{ value: 'CPU %', angle: -90, position: 'insideLeft', style: { fill: '#9CA3AF' } }} />
                    {compareMetrics && (
                      <YAxis yAxisId="right" orientation="right" stroke="#9CA3AF" tickFormatter={(value) => formatBytes(value)} label={{ value: 'Memory (MB)', angle: 90, position: 'insideRight', style: { fill: '#9CA3AF' } }} />
                    )}
                    <Tooltip contentStyle={{ backgroundColor: '#1F2937', border: '1px solid #374151' }} labelFormatter={(value) => format(new Date(value as string), 'PPpp')} />
                    <Legend />
                    <Line yAxisId="left" type="monotone" dataKey="cpu_percent" stroke="#3B82F6" name="CPU %" strokeWidth={2} />
                    {compareMetrics && (
                      <Line yAxisId="right" type="monotone" dataKey="memory_usage" stroke="#10B981" name="Memory Usage" strokeWidth={2} />
                    )}
                  </LineChart>
                )}
                {selectedMetric === 'memory' && (
                  <LineChart data={historyData}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
                    <XAxis dataKey="timestamp" stroke="#9CA3AF" tickFormatter={(value) => format(new Date(value), 'HH:mm')} />
                    <YAxis yAxisId="left" stroke="#9CA3AF" tickFormatter={(value) => formatBytes(value)} label={{ value: 'Memory (MB)', angle: -90, position: 'insideLeft', style: { fill: '#9CA3AF' } }} />
                    {compareMetrics && (
                      <YAxis yAxisId="right" orientation="right" stroke="#9CA3AF" label={{ value: 'CPU %', angle: 90, position: 'insideRight', style: { fill: '#9CA3AF' } }} />
                    )}
                    <Tooltip contentStyle={{ backgroundColor: '#1F2937', border: '1px solid #374151' }} labelFormatter={(value) => format(new Date(value as string), 'PPpp')} />
                    <Legend />
                    <Line yAxisId="left" type="monotone" dataKey="memory_usage" stroke="#10B981" name="Memory Usage" strokeWidth={2} />
                    {compareMetrics && (
                      <Line yAxisId="right" type="monotone" dataKey="cpu_percent" stroke="#3B82F6" name="CPU %" strokeWidth={2} />
                    )}
                  </LineChart>
                )}
                {selectedMetric === 'network' && (
                  <LineChart data={historyData}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
                    <XAxis dataKey="timestamp" stroke="#9CA3AF" tickFormatter={(value) => format(new Date(value), 'HH:mm')} />
                    <YAxis stroke="#9CA3AF" tickFormatter={(value) => formatBytes(value)} />
                    <Tooltip contentStyle={{ backgroundColor: '#1F2937', border: '1px solid #374151' }} labelFormatter={(value) => format(new Date(value as string), 'PPpp')} formatter={(value, name?: string) => [formatBytes((value as number) || 0), name || '']} />
                    <Legend />
                    <Line type="monotone" dataKey="network_rx" stroke="#8B5CF6" name="RX" />
                    <Line type="monotone" dataKey="network_tx" stroke="#EC4899" name="TX" />
                  </LineChart>
                )}
                {selectedMetric === 'disk' && (
                  <LineChart data={historyData}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
                    <XAxis dataKey="timestamp" stroke="#9CA3AF" tickFormatter={(value) => format(new Date(value), 'HH:mm')} />
                    <YAxis stroke="#9CA3AF" tickFormatter={(value) => formatBytes(value)} />
                    <Tooltip contentStyle={{ backgroundColor: '#1F2937', border: '1px solid #374151' }} labelFormatter={(value) => format(new Date(value as string), 'PPpp')} formatter={(value, name?: string) => [formatBytes((value as number) || 0), name || '']} />
                    <Legend />
                    <Line type="monotone" dataKey="block_read" stroke="#F59E0B" name="Read" />
                    <Line type="monotone" dataKey="block_write" stroke="#EF4444" name="Write" />
                  </LineChart>
                )}
                {selectedMetric === 'pids' && (
                  <LineChart data={historyData}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
                    <XAxis dataKey="timestamp" stroke="#9CA3AF" tickFormatter={(value) => format(new Date(value), 'HH:mm')} />
                    <YAxis stroke="#9CA3AF" />
                    <Tooltip contentStyle={{ backgroundColor: '#1F2937', border: '1px solid #374151' }} labelFormatter={(value) => format(new Date(value as string), 'PPpp')} formatter={(value) => [(value as number) || 0, 'Processes']} />
                    <Legend />
                    <Line type="monotone" dataKey="pids" stroke="#06B6D4" name="PIDs" />
                  </LineChart>
                )}
              </ResponsiveContainer>
            </div>
          )}
        </div>
      </div>
    );
  }

  // Grid view
  return (
    <div className="grid grid-cols-3 gap-4">
      {/* CPU Usage */}
      <div onClick={() => setSelectedMetric('cpu')} className="bg-tide-surface/50 rounded-lg p-4 cursor-pointer hover:bg-tide-surface transition-colors border border-tide-border">
        <h3 className="text-lg font-semibold text-tide-text mb-4">CPU Usage</h3>
        <div className="space-y-3">
          <div className="flex justify-between">
            <span className="text-tide-text-muted">Current</span>
            <span className="text-tide-text font-mono text-sm">{metrics ? `${metrics.cpu_percent.toFixed(2)}%` : 'N/A'}</span>
          </div>
          <div className="w-full bg-tide-surface-light rounded-full h-2">
            <div className="bg-primary h-2 rounded-full transition-all" style={{ width: `${metrics ? Math.min(metrics.cpu_percent, 100) : 0}%` }}></div>
          </div>
        </div>
      </div>

      {/* Memory Usage */}
      <div onClick={() => setSelectedMetric('memory')} className="bg-tide-surface/50 rounded-lg p-4 cursor-pointer hover:bg-tide-surface transition-colors border border-tide-border">
        <h3 className="text-lg font-semibold text-tide-text mb-4">Memory Usage</h3>
        <div className="space-y-3">
          <div className="flex justify-between">
            <span className="text-tide-text-muted">Current</span>
            <span className="text-tide-text font-mono text-sm">{metrics ? `${formatBytes(metrics.memory_usage)} / ${formatBytes(metrics.memory_limit)}` : 'N/A'}</span>
          </div>
          <div className="w-full bg-tide-surface-light rounded-full h-2">
            <div className="bg-accent h-2 rounded-full transition-all" style={{ width: `${metrics ? Math.min(metrics.memory_percent, 100) : 0}%` }}></div>
          </div>
        </div>
      </div>

      {/* PIDs */}
      <div onClick={() => setSelectedMetric('pids')} className="bg-tide-surface/50 rounded-lg p-4 cursor-pointer hover:bg-tide-surface transition-colors border border-tide-border">
        <h3 className="text-lg font-semibold text-tide-text mb-4">Processes</h3>
        <div className="space-y-3">
          <div className="flex justify-between">
            <span className="text-tide-text-muted">PIDs</span>
            <span className="text-tide-text font-mono text-sm">{metrics ? metrics.pids : 'N/A'}</span>
          </div>
          <div className="text-tide-text-muted text-xs mt-2">Active process count</div>
        </div>
      </div>

      {/* Network I/O */}
      <div onClick={() => setSelectedMetric('network')} className="bg-tide-surface/50 rounded-lg p-4 cursor-pointer hover:bg-tide-surface transition-colors border border-tide-border">
        <h3 className="text-lg font-semibold text-tide-text mb-4">Network I/O</h3>
        <div className="space-y-3">
          <div className="flex justify-between">
            <span className="text-tide-text-muted">RX</span>
            <span className="text-tide-text font-mono text-sm">{metrics ? formatBytes(metrics.network_rx) : 'N/A'}</span>
          </div>
          <div className="flex justify-between">
            <span className="text-tide-text-muted">TX</span>
            <span className="text-tide-text font-mono text-sm">{metrics ? formatBytes(metrics.network_tx) : 'N/A'}</span>
          </div>
        </div>
      </div>

      {/* Block I/O */}
      <div onClick={() => setSelectedMetric('disk')} className="bg-tide-surface/50 rounded-lg p-4 cursor-pointer hover:bg-tide-surface transition-colors border border-tide-border">
        <h3 className="text-lg font-semibold text-tide-text mb-4">Block I/O</h3>
        <div className="space-y-3">
          <div className="flex justify-between">
            <span className="text-tide-text-muted">Read</span>
            <span className="text-tide-text font-mono text-sm">{metrics ? formatBytes(metrics.block_read) : 'N/A'}</span>
          </div>
          <div className="flex justify-between">
            <span className="text-tide-text-muted">Write</span>
            <span className="text-tide-text font-mono text-sm">{metrics ? formatBytes(metrics.block_write) : 'N/A'}</span>
          </div>
        </div>
      </div>
    </div>
  );
}
