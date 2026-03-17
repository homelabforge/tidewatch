import React from 'react';
import { RefreshCw, Download, Ban, RotateCw, RotateCcw, Server, Eye } from 'lucide-react';
import { HttpServer, HttpServersResponse } from '../../../types';
import { formatDistanceToNow } from 'date-fns';

interface HttpServerSectionProps {
  httpServers: HttpServersResponse | null;
  loading: boolean;
  onRescan: () => Promise<void>;
  onPreviewUpdate: (server: HttpServer, type: 'http_server') => void;
  onDirectUpdate: (server: HttpServer, type: 'http_server') => void;
  onIgnore: (server: HttpServer, type: 'http_server') => void;
  onUnignore: (server: HttpServer, type: 'http_server') => void;
  onRollback: (server: HttpServer, type: 'http_server') => void;
}

const severityColors = {
  critical: 'bg-red-500/20 text-red-400 border-red-500/30',
  high: 'bg-orange-500/20 text-orange-400 border-orange-500/30',
  medium: 'bg-yellow-500/20 text-yellow-400 border-yellow-500/30',
  low: 'bg-blue-500/20 text-blue-400 border-blue-500/30',
  info: 'bg-gray-500/20 text-tide-text-muted border-gray-500/30',
};

export default function HttpServerSection({
  httpServers,
  loading,
  onRescan,
  onPreviewUpdate,
  onDirectUpdate,
  onIgnore,
  onUnignore,
  onRollback,
}: HttpServerSectionProps): React.ReactNode {
  return (
    <div>
      <div className="mb-4 flex items-start justify-between">
        <div>
          <h3 className="text-xl font-semibold text-tide-text">HTTP Servers</h3>
          <p className="text-sm text-tide-text-muted mt-1">
            Detected HTTP servers running in the container with version information.
          </p>
        </div>
        <button
          onClick={onRescan}
          disabled={loading}
          className="px-3 py-1.5 bg-primary hover:bg-primary-dark text-tide-text rounded-lg font-medium transition-colors disabled:opacity-50 flex items-center gap-2 text-sm"
        >
          <RefreshCw size={14} className={loading ? 'animate-spin' : ''} />
          Rescan
        </button>
      </div>

      {/* HTTP Servers Content */}
      {loading ? (
        <div className="text-center py-12 bg-tide-surface border border-tide-border rounded-lg">
          <RefreshCw className="animate-spin mx-auto mb-4 text-primary" size={48} />
          <p className="text-tide-text-muted">Scanning for HTTP servers...</p>
        </div>
      ) : httpServers && (httpServers.servers?.length ?? 0) > 0 ? (
        <>
          <div className="grid grid-cols-2 gap-4 mb-4">
            <div className="bg-tide-surface rounded-lg p-4 border border-tide-border">
              <p className="text-sm text-tide-text-muted">Total Servers</p>
              <p className="text-2xl font-bold text-tide-text mt-1">{httpServers.total}</p>
            </div>
            <div className="bg-tide-surface rounded-lg p-4 border border-tide-border">
              <p className="text-sm text-tide-text-muted">Updates Available</p>
              <p className="text-2xl font-bold text-accent mt-1">{httpServers.with_updates}</p>
            </div>
          </div>

          <div className="space-y-2">
            {(httpServers.servers ?? []).map((server, index) => (
              <div
                key={`${server.name}-${index}`}
                className="bg-tide-surface rounded-lg p-4 border border-tide-border"
              >
                <div className="flex items-start justify-between">
                  <div className="flex-1">
                    <div className="flex items-center gap-3">
                      <Server size={20} className="text-primary" />
                      <div>
                        <p className="text-tide-text font-medium capitalize">{server.name}</p>
                        <p className="text-sm text-tide-text-muted">
                          {server.current_version ? `v${server.current_version}` : 'Version unknown'}
                          {server.latest_version && server.update_available && (
                            <span className="text-accent ml-2">&rarr; v{server.latest_version}</span>
                          )}
                        </p>
                        <p className="text-xs text-tide-text-muted mt-1">
                          Detected via {
                            server.detection_method === 'dependency_file' ? 'dependency file' :
                            server.detection_method === 'dockerfile_from' ? 'Dockerfile FROM' :
                            server.detection_method === 'dockerfile_run' ? 'Dockerfile RUN' :
                            server.detection_method === 'labels' ? 'labels' :
                            server.detection_method
                          }
                        </p>
                      </div>
                    </div>
                  </div>
                  <div className="flex items-center gap-2">
                    {!server.ignored && server.update_available && (
                      <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${severityColors[server.severity as keyof typeof severityColors]}`}>
                        {server.severity === 'critical' && 'Critical Update'}
                        {server.severity === 'high' && 'High Priority'}
                        {server.severity === 'medium' && 'Major Update'}
                        {server.severity === 'low' && 'Minor Update'}
                        {server.severity === 'info' && 'Patch Update'}
                      </span>
                    )}
                    {!server.ignored && !server.update_available && server.current_version && (
                      <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-green-500/20 text-green-400 border border-green-500/30">
                        Up to date
                      </span>
                    )}
                    {server.ignored && (
                      <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-gray-500/20 text-gray-400 border border-gray-500/30">
                        Up to date
                      </span>
                    )}
                    {!server.ignored && server.update_available && (
                      <>
                        <button
                          onClick={() => onPreviewUpdate(server, 'http_server')}
                          className="px-2.5 py-1.5 bg-tide-surface hover:bg-tide-surface-light text-tide-text rounded-lg font-medium transition-colors flex items-center gap-1.5 text-xs border border-tide-border"
                          title="Preview update changes"
                        >
                          <Eye size={14} />
                          Preview
                        </button>
                        <button
                          onClick={() => onDirectUpdate(server, 'http_server')}
                          className="px-2.5 py-1.5 bg-primary hover:bg-primary/90 text-white rounded-lg font-medium transition-colors flex items-center gap-1.5 text-xs border border-primary"
                          title="Update HTTP server immediately"
                        >
                          <Download size={14} />
                          Update
                        </button>
                        <button
                          onClick={() => onIgnore(server, 'http_server')}
                          className="px-2.5 py-1.5 bg-primary/20 hover:bg-primary/30 text-primary rounded-lg font-medium transition-colors flex items-center gap-1.5 text-xs border border-primary/30"
                          title="Ignore this update"
                        >
                          <Ban size={14} />
                          Ignore
                        </button>
                      </>
                    )}
                    {server.ignored && (
                      <button
                        onClick={() => onUnignore(server, 'http_server')}
                        className="px-2.5 py-1.5 bg-tide-surface hover:bg-tide-surface-light text-tide-text rounded-lg font-medium transition-colors flex items-center gap-1.5 text-xs border border-tide-border"
                        title="Unignore this update"
                      >
                        <RotateCw size={14} />
                        Unignore
                      </button>
                    )}
                    <button
                      onClick={() => onRollback(server, 'http_server')}
                      className="px-2.5 py-1.5 bg-orange-500/20 hover:bg-orange-500/30 text-orange-400 rounded-lg font-medium transition-colors flex items-center gap-1.5 text-xs border border-orange-500/30"
                      title="Rollback to a previous version"
                    >
                      <RotateCcw size={14} />
                      Rollback
                    </button>
                  </div>
                </div>
              </div>
            ))}
          </div>

          {httpServers.last_scan && (
            <div className="text-sm text-tide-text-muted text-center mt-4">
              Last scanned: {formatDistanceToNow(new Date(httpServers.last_scan), { addSuffix: true })}
            </div>
          )}
        </>
      ) : (
        <div className="text-center py-12 bg-tide-surface border border-tide-border rounded-lg">
          <Server className="mx-auto mb-4 text-gray-600" size={48} />
          <p className="text-tide-text-muted">No HTTP servers detected</p>
          <p className="text-sm text-tide-text-muted mt-1">
            Container may not be running or doesn't contain common HTTP servers
          </p>
        </div>
      )}
    </div>
  );
}
