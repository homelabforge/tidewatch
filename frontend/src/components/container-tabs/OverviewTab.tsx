import { useState } from 'react';
import { AlertCircle, CircleCheckBig, RefreshCw } from 'lucide-react';
import { Container } from '../../types';
import { formatDistanceToNow } from 'date-fns';
import { api } from '../../services/api';
import { toast } from 'sonner';

interface OverviewTabProps {
  container: Container;
  onUpdate?: () => void;
}

export default function OverviewTab({ container, onUpdate }: OverviewTabProps) {
  const [checkingUpdate, setCheckingUpdate] = useState(false);

  const handleCheckForUpdates = async () => {
    setCheckingUpdate(true);
    try {
      const result = await api.containers.checkForUpdates(container.id);
      if (result.update) {
        toast.success(`Update found: ${result.update.to_tag}`);
      } else {
        toast.success('No updates available');
      }
      onUpdate?.();
    } catch (error) {
      toast.error('Failed to check for updates');
      console.error(error);
    } finally {
      setCheckingUpdate(false);
    }
  };

  const handleRestart = async () => {
    const reason = prompt('Optional: Enter a reason for the restart');
    try {
      await api.restarts.manualRestart(container.id, reason || undefined);
      toast.success('Container restarted successfully');
      onUpdate?.();
    } catch {
      toast.error('Failed to restart container');
    }
  };

  return (
    <div className="space-y-6">
      {/* Status Card */}
      {container.update_available ? (
        <div className="bg-tide-surface/50 rounded-lg p-4 border border-tide-border border-l-4 border-l-accent">
          <div className="flex items-center gap-3">
            <AlertCircle className="w-8 h-8 text-accent" />
            <div>
              <h3 className="text-lg font-semibold text-tide-text">Update Available</h3>
              <p className="text-tide-text-muted text-sm mt-1">
                A new version is available: {container.latest_tag || 'Unknown'}
              </p>
            </div>
          </div>
          <div className="mt-4 flex gap-2">
            <button
              onClick={handleCheckForUpdates}
              disabled={checkingUpdate}
              className="px-4 py-2 bg-tide-surface-light hover:bg-gray-500 text-tide-text rounded-lg transition-colors flex items-center gap-2 disabled:opacity-50 disabled:cursor-not-allowed"
            >
              <RefreshCw className={`w-4 h-4 ${checkingUpdate ? 'animate-spin' : ''}`} />
              {checkingUpdate ? 'Checking...' : 'Check for Updates'}
            </button>
            <button
              onClick={handleRestart}
              className="px-4 py-2 bg-accent hover:bg-accent-dark text-tide-text rounded-lg transition-colors flex items-center gap-2"
            >
              <RefreshCw className="w-4 h-4" />
              Restart
            </button>
          </div>
        </div>
      ) : (
        <div className="bg-tide-surface/50 rounded-lg p-4 border border-tide-border border-l-4 border-l-green-500">
          <div className="flex items-center gap-3">
            <CircleCheckBig className="w-8 h-8 text-green-500" />
            <div>
              <h3 className="text-lg font-semibold text-tide-text">Up to Date</h3>
              <p className="text-tide-text-muted text-sm mt-1">This container is running the latest version.</p>
            </div>
          </div>
          <div className="mt-4 flex gap-2">
            <button
              onClick={handleCheckForUpdates}
              disabled={checkingUpdate}
              className="px-4 py-2 bg-tide-surface-light hover:bg-gray-500 text-tide-text rounded-lg transition-colors flex items-center gap-2 disabled:opacity-50 disabled:cursor-not-allowed"
            >
              <RefreshCw className={`w-4 h-4 ${checkingUpdate ? 'animate-spin' : ''}`} />
              {checkingUpdate ? 'Checking...' : 'Check for Updates'}
            </button>
            <button
              onClick={handleRestart}
              className="px-4 py-2 bg-accent hover:bg-accent-dark text-tide-text rounded-lg transition-colors flex items-center gap-2"
            >
              <RefreshCw className="w-4 h-4" />
              Restart
            </button>
          </div>
        </div>
      )}

      {/* Information Card */}
      <div className="bg-tide-surface/50 rounded-lg p-4 border border-tide-border">
        <h3 className="text-lg font-semibold text-tide-text mb-4">Information</h3>
        <div className="space-y-3">
          <div className="flex justify-between">
            <span className="text-tide-text-muted">Registry</span>
            <span className="text-tide-text font-mono text-sm">{container.registry}</span>
          </div>
          <div className="flex justify-between">
            <span className="text-tide-text-muted">Compose File</span>
            <span className="text-tide-text font-mono text-sm truncate max-w-xs" title={container.compose_file}>
              {container.compose_file}
            </span>
          </div>
          <div className="flex justify-between">
            <span className="text-tide-text-muted">Service Name</span>
            <span className="text-tide-text font-mono text-sm">{container.service_name}</span>
          </div>
          <div className="flex justify-between">
            <span className="text-tide-text-muted">Last Checked</span>
            <span className="text-tide-text text-sm">
              {container.last_checked
                ? formatDistanceToNow(new Date(container.last_checked), { addSuffix: true })
                : 'Never'}
            </span>
          </div>
        </div>
      </div>
    </div>
  );
}
