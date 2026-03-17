import { Search, RefreshCw } from 'lucide-react';
import type { FilterOptions } from '../../types';
import type { CheckJobState } from '../CheckProgressBar';

interface DashboardFiltersProps {
  filters: FilterOptions;
  onFilterChange: (filters: FilterOptions) => void;
  scanning: boolean;
  checkingUpdates: boolean;
  checkJobStatus: CheckJobState['status'] | null;
  onScan: () => void;
  onCheckUpdates: () => void;
}

export default function DashboardFilters({
  filters,
  onFilterChange,
  scanning,
  checkingUpdates,
  checkJobStatus,
  onScan,
  onCheckUpdates,
}: DashboardFiltersProps) {
  const isCheckRunning = checkJobStatus === 'running' || checkJobStatus === 'queued';

  return (
    <div className="flex flex-col sm:flex-row gap-4 mb-6">
      <div className="flex-1 relative">
        <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 text-tide-text-muted" size={20} />
        <input
          type="text"
          placeholder="Search containers..."
          value={filters.search}
          onChange={(e) => onFilterChange({ ...filters, search: e.target.value })}
          className="w-full pl-10 pr-4 py-2 bg-tide-surface border border-tide-border rounded-lg text-tide-text placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-primary"
        />
      </div>

      <div className="flex flex-wrap gap-2">
        <select
          value={filters.status}
          onChange={(e) => onFilterChange({ ...filters, status: e.target.value })}
          className="px-4 py-2 bg-tide-surface border border-tide-border rounded-lg text-tide-text focus:outline-none focus:ring-2 focus:ring-primary"
        >
          <option value="all">All Status</option>
          <option value="running">Running</option>
          <option value="stopped">Stopped</option>
          <option value="exited">Exited</option>
        </select>

        <select
          value={filters.autoUpdate}
          onChange={(e) => onFilterChange({ ...filters, autoUpdate: e.target.value })}
          className="px-4 py-2 bg-tide-surface border border-tide-border rounded-lg text-tide-text focus:outline-none focus:ring-2 focus:ring-primary"
        >
          <option value="all">All Auto-Update</option>
          <option value="enabled">Enabled</option>
          <option value="disabled">Disabled</option>
        </select>

        <select
          value={filters.hasUpdate}
          onChange={(e) => onFilterChange({ ...filters, hasUpdate: e.target.value })}
          className="px-4 py-2 bg-tide-surface border border-tide-border rounded-lg text-tide-text focus:outline-none focus:ring-2 focus:ring-primary"
        >
          <option value="all">All Updates</option>
          <option value="yes">Has Updates</option>
          <option value="no">No Updates</option>
        </select>

        <button
          onClick={onScan}
          disabled={scanning || checkingUpdates}
          className="px-4 py-2 bg-primary hover:bg-primary-dark text-tide-text rounded-lg font-medium transition-colors disabled:opacity-50 flex items-center gap-2"
        >
          <RefreshCw size={16} className={scanning ? 'animate-spin' : ''} />
          {scanning ? 'Scanning...' : 'Scan'}
        </button>

        <button
          onClick={onCheckUpdates}
          disabled={scanning || isCheckRunning}
          className="px-4 py-2 bg-accent hover:bg-accent-dark text-tide-text rounded-lg font-medium transition-colors disabled:opacity-50 flex items-center gap-2"
        >
          <RefreshCw size={16} className={isCheckRunning ? 'animate-spin' : ''} />
          Check Updates
        </button>
      </div>
    </div>
  );
}
