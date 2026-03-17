import { Package, RefreshCw, Archive } from 'lucide-react';

interface DashboardStatsProps {
  totalContainers: number;
  runningContainers: number;
  autoUpdateEnabled: number;
  staleContainers: number;
  pendingUpdates: number;
}

export default function DashboardStats({
  totalContainers,
  runningContainers,
  autoUpdateEnabled,
  staleContainers,
  pendingUpdates,
}: DashboardStatsProps) {
  return (
    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-5 gap-4 mb-8">
      <div className="bg-tide-surface rounded-lg p-6 border border-tide-border">
        <div className="flex items-center justify-between">
          <div>
            <p className="text-sm text-tide-text-muted">Total Containers</p>
            <p className="text-3xl font-bold text-tide-text mt-2">{totalContainers}</p>
          </div>
          <Package className="text-primary" size={32} />
        </div>
      </div>

      <div className="bg-tide-surface rounded-lg p-6 border border-tide-border">
        <div className="flex items-center justify-between">
          <div>
            <p className="text-sm text-tide-text-muted">Running</p>
            <p className="text-3xl font-bold text-green-400 mt-2">{runningContainers}</p>
          </div>
          <div className="w-3 h-3 bg-green-400 rounded-full animate-pulse"></div>
        </div>
      </div>

      <div className="bg-tide-surface rounded-lg p-6 border border-tide-border">
        <div className="flex items-center justify-between">
          <div>
            <p className="text-sm text-tide-text-muted">Auto-Update Enabled</p>
            <p className="text-3xl font-bold text-primary mt-2">{autoUpdateEnabled}</p>
          </div>
          <RefreshCw className="text-primary" size={32} />
        </div>
      </div>

      <div className="bg-tide-surface rounded-lg p-6 border border-tide-border">
        <div className="flex items-center justify-between">
          <div>
            <p className="text-sm text-tide-text-muted">Stale Containers</p>
            <p className="text-3xl font-bold text-orange-400 mt-2">{staleContainers}</p>
          </div>
          <Archive className="text-orange-400" size={32} />
        </div>
      </div>

      <div className="bg-tide-surface rounded-lg p-6 border border-tide-border">
        <div className="flex items-center justify-between">
          <div>
            <p className="text-sm text-tide-text-muted">Pending Updates</p>
            <p className="text-3xl font-bold text-accent mt-2">{pendingUpdates}</p>
          </div>
          {pendingUpdates > 0 && (
            <div className="w-3 h-3 bg-accent rounded-full animate-pulse"></div>
          )}
        </div>
      </div>
    </div>
  );
}
