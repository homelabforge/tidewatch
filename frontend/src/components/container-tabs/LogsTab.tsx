import { useState, useEffect, useCallback } from 'react';
import { RefreshCw, Search, Copy, Download, ChevronDown, ChevronUp } from 'lucide-react';
import { Container } from '../../types';
import { format } from 'date-fns';
import { api } from '../../services/api';
import { toast } from 'sonner';

interface LogsTabProps {
  container: Container;
}

export default function LogsTab({ container }: LogsTabProps) {
  const [logs, setLogs] = useState<string>('');
  const [loadingLogs, setLoadingLogs] = useState(false);
  const [autoRefreshLogs, setAutoRefreshLogs] = useState(true);
  const [logLines, setLogLines] = useState(100);
  const [logSearchQuery, setLogSearchQuery] = useState('');
  const [followMode, setFollowMode] = useState(true);

  const loadLogs = useCallback(async () => {
    setLoadingLogs(true);
    try {
      const data = await api.containers.getLogs(container.id, logLines);
      setLogs(data.logs.join('\n') || '');
    } catch (error) {
      console.error('Failed to load logs:', error);
      setLogs('Failed to load logs');
    } finally {
      setLoadingLogs(false);
    }
  }, [container.id, logLines]);

  useEffect(() => {
    loadLogs();

    if (autoRefreshLogs) {
      const interval = setInterval(loadLogs, 2000);
      return () => clearInterval(interval);
    }
  }, [autoRefreshLogs, loadLogs]);

  const highlightLogLine = (line: string) => {
    const lowerLine = line.toLowerCase();
    if (lowerLine.includes('error')) return 'text-red-400';
    if (lowerLine.includes('warn') || lowerLine.includes('warning')) return 'text-yellow-400';
    if (lowerLine.includes('info')) return 'text-blue-400';
    if (lowerLine.includes('debug')) return 'text-tide-text-muted';
    return 'text-tide-text';
  };

  const filterLogs = (logContent: string) => {
    if (!logSearchQuery.trim()) return logContent;
    const lines = logContent.split('\n');
    const query = logSearchQuery.toLowerCase();
    return lines.filter(line => line.toLowerCase().includes(query)).join('\n');
  };

  const copyLogsToClipboard = async () => {
    try {
      const logsToCopy = filterLogs(logs);
      await navigator.clipboard.writeText(logsToCopy);
      toast.success('Logs copied to clipboard');
    } catch (error) {
      console.error('Failed to copy logs:', error);
      toast.error('Failed to copy logs');
    }
  };

  const downloadLogs = () => {
    try {
      const logsToDownload = filterLogs(logs);
      const timestamp = format(new Date(), 'yyyy-MM-dd-HHmmss');
      const filename = `${container.name}-logs-${timestamp}.txt`;

      const blob = new Blob([logsToDownload], { type: 'text/plain' });
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = filename;
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      URL.revokeObjectURL(url);

      toast.success(`Logs downloaded as ${filename}`);
    } catch (error) {
      console.error('Failed to download logs:', error);
      toast.error('Failed to download logs');
    }
  };

  return (
    <div className="flex flex-col h-full">
      {/* Logs Header with Controls */}
      <div className="flex flex-col gap-3 mb-4">
        <div className="flex items-center justify-between">
          <h3 className="text-lg font-semibold text-tide-text">Container Logs</h3>
          <div className="flex items-center gap-2">
            <div className="flex items-center gap-2">
              <label className="text-sm text-tide-text-muted">Lines:</label>
              <select
                value={logLines}
                onChange={(e) => setLogLines(Number(e.target.value))}
                className="bg-tide-surface text-tide-text text-sm rounded-lg px-3 py-1 border border-tide-border-light focus:outline-none focus:ring-2 focus:ring-primary"
              >
                <option value={100}>100</option>
                <option value={500}>500</option>
                <option value={1000}>1000</option>
                <option value={10000}>All</option>
              </select>
            </div>

            <button
              onClick={() => setAutoRefreshLogs(!autoRefreshLogs)}
              className={`flex items-center gap-2 px-3 py-1 rounded-lg text-sm transition-colors ${
                autoRefreshLogs
                  ? 'bg-primary text-tide-text'
                  : 'bg-tide-surface-light text-tide-text hover:bg-gray-500'
              }`}
            >
              <RefreshCw className={`w-4 h-4 ${autoRefreshLogs && loadingLogs ? 'animate-spin' : ''}`} />
              {autoRefreshLogs ? 'Live' : 'Paused'}
            </button>

            <button
              onClick={loadLogs}
              disabled={loadingLogs}
              className="px-3 py-1 bg-tide-surface-light hover:bg-gray-500 text-tide-text rounded-lg text-sm transition-colors disabled:opacity-50"
            >
              Refresh
            </button>
          </div>
        </div>

        {/* Search and Action Buttons */}
        <div className="flex items-center gap-2">
          <div className="flex-1 relative">
            <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 w-4 h-4 text-tide-text-muted" />
            <input
              type="text"
              placeholder="Search logs..."
              value={logSearchQuery}
              onChange={(e) => setLogSearchQuery(e.target.value)}
              className="w-full pl-10 pr-3 py-2 bg-tide-surface border border-tide-border text-tide-text rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-primary"
            />
          </div>

          <button
            onClick={copyLogsToClipboard}
            disabled={!logs}
            className="flex items-center gap-2 px-3 py-2 bg-tide-surface-light hover:bg-gray-500 text-tide-text rounded-lg text-sm transition-colors disabled:opacity-50"
            title="Copy to clipboard"
          >
            <Copy className="w-4 h-4" />
            Copy
          </button>

          <button
            onClick={downloadLogs}
            disabled={!logs}
            className="flex items-center gap-2 px-3 py-2 bg-tide-surface-light hover:bg-gray-500 text-tide-text rounded-lg text-sm transition-colors disabled:opacity-50"
            title="Download as .txt file"
          >
            <Download className="w-4 h-4" />
            Download
          </button>

          <button
            onClick={() => setFollowMode(!followMode)}
            className={`flex items-center gap-2 px-3 py-2 rounded-lg text-sm transition-colors ${
              followMode
                ? 'bg-primary text-tide-text'
                : 'bg-tide-surface-light text-tide-text hover:bg-gray-500'
            }`}
            title={followMode ? 'Auto-scroll enabled' : 'Auto-scroll disabled'}
          >
            {followMode ? <ChevronDown className="w-4 h-4" /> : <ChevronUp className="w-4 h-4" />}
            Follow
          </button>
        </div>
      </div>

      {/* Logs Content */}
      <div className="flex-1 bg-tide-surface rounded-lg p-4 overflow-auto font-mono text-xs">
        {loadingLogs && !logs ? (
          <div className="flex items-center justify-center h-full">
            <RefreshCw className="w-8 h-8 text-primary animate-spin" />
          </div>
        ) : logs ? (
          <div className="whitespace-pre-wrap break-words">
            {filterLogs(logs).split('\n').map((line, index) => (
              <div key={index} className={highlightLogLine(line)}>
                {line}
              </div>
            ))}
          </div>
        ) : (
          <div className="flex items-center justify-center h-full text-tide-text-muted">
            No logs available
          </div>
        )}
      </div>

      {/* Info footer */}
      <div className="mt-2 flex items-center justify-between text-xs text-tide-text-muted">
        <span>
          {autoRefreshLogs && 'Auto-refreshing every 2 seconds'}
          {!autoRefreshLogs && 'Auto-refresh paused'}
          {logSearchQuery && ` • Filtering by: "${logSearchQuery}"`}
        </span>
        <span>
          {followMode && 'Auto-scroll enabled'}
        </span>
      </div>
    </div>
  );
}
