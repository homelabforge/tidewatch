import { useState } from 'react';
import { X, Info, Activity, FileText, Clock, Settings, Package } from 'lucide-react';
import { Container } from '../types';
import OverviewTab from './container-tabs/OverviewTab';
import MetricsTab from './container-tabs/MetricsTab';
import LogsTab from './container-tabs/LogsTab';
import HistoryTab from './container-tabs/HistoryTab';
import DependenciesTab from './container-tabs/DependenciesTab';
import SettingsTab from './container-tabs/SettingsTab';

interface ContainerModalProps {
  container: Container;
  onClose: () => void;
  onUpdate?: () => void;
}

type TabType = 'overview' | 'metrics' | 'logs' | 'history' | 'dependencies' | 'settings';

export default function ContainerModal({ container, onClose, onUpdate }: ContainerModalProps) {
  const [activeTab, setActiveTab] = useState<TabType>('overview');

  return (
    <div className="fixed inset-0 z-50 overflow-y-auto">
      <div className="flex items-center justify-center min-h-screen px-4 pt-4 pb-20 text-center sm:block sm:p-0">
        {/* Background overlay */}
        <div className="fixed inset-0 transition-opacity bg-tide-surface/75" onClick={onClose} />

        {/* Modal panel */}
        <div className="inline-block overflow-hidden text-left align-bottom transition-all transform bg-tide-surface rounded-lg shadow-xl sm:my-8 sm:align-middle sm:max-w-6xl sm:w-full relative">
          {/* Header */}
          <div className="flex items-center justify-between p-6 border-b border-tide-border">
            <div>
              <h2 className="text-2xl font-bold text-tide-text">{container.name}</h2>
              <p className="text-sm text-tide-text-muted mt-1">{container.image}:{container.current_tag}</p>
            </div>
            <button
              onClick={onClose}
              className="text-tide-text-muted hover:text-tide-text transition-colors"
            >
              <X className="w-6 h-6" />
            </button>
          </div>

          {/* Tabs */}
          <div className="border-b border-tide-border px-6">
            <div className="flex items-center justify-between">
              {/* Left tabs */}
              <div className="flex space-x-1">
                <button
                  onClick={() => setActiveTab('overview')}
                  className={`px-4 py-3 text-sm font-medium transition-colors border-b-2 flex items-center gap-2 ${
                    activeTab === 'overview'
                      ? 'border-primary text-primary'
                      : 'border-transparent text-tide-text-muted hover:text-tide-text'
                  }`}
                >
                  <Info size={16} />
                  Overview
                </button>
                <button
                  onClick={() => setActiveTab('metrics')}
                  className={`px-4 py-3 text-sm font-medium transition-colors border-b-2 flex items-center gap-2 ${
                    activeTab === 'metrics'
                      ? 'border-primary text-primary'
                      : 'border-transparent text-tide-text-muted hover:text-tide-text'
                  }`}
                >
                  <Activity size={16} />
                  Metrics
                </button>
                <button
                  onClick={() => setActiveTab('logs')}
                  className={`px-4 py-3 text-sm font-medium transition-colors border-b-2 flex items-center gap-2 ${
                    activeTab === 'logs'
                      ? 'border-primary text-primary'
                      : 'border-transparent text-tide-text-muted hover:text-tide-text'
                  }`}
                >
                  <FileText size={16} />
                  Logs
                </button>
                <button
                  onClick={() => setActiveTab('history')}
                  className={`px-4 py-3 text-sm font-medium transition-colors border-b-2 flex items-center gap-2 ${
                    activeTab === 'history'
                      ? 'border-primary text-primary'
                      : 'border-transparent text-tide-text-muted hover:text-tide-text'
                  }`}
                >
                  <Clock size={16} />
                  History
                </button>
                {container.is_my_project && (
                  <button
                    onClick={() => setActiveTab('dependencies')}
                    className={`px-4 py-3 text-sm font-medium transition-colors border-b-2 flex items-center gap-2 ${
                      activeTab === 'dependencies'
                        ? 'border-primary text-primary'
                        : 'border-transparent text-tide-text-muted hover:text-tide-text'
                    }`}
                  >
                    <Package size={16} />
                    Dependencies
                  </button>
                )}
              </div>

              {/* Right tab */}
              <button
                onClick={() => setActiveTab('settings')}
                className={`px-4 py-3 text-sm font-medium transition-colors border-b-2 flex items-center gap-2 ${
                  activeTab === 'settings'
                    ? 'border-primary text-primary'
                    : 'border-transparent text-tide-text-muted hover:text-tide-text'
                }`}
              >
                <Settings size={16} />
                Settings
              </button>
            </div>
          </div>

          {/* Tab Content */}
          <div className="p-6 max-h-[70vh] overflow-y-auto">
            {activeTab === 'overview' && (
              <OverviewTab container={container} onUpdate={onUpdate} />
            )}
            {activeTab === 'metrics' && (
              <MetricsTab container={container} />
            )}
            {activeTab === 'logs' && (
              <LogsTab container={container} />
            )}
            {activeTab === 'history' && (
              <HistoryTab container={container} onClose={onClose} onUpdate={onUpdate} />
            )}
            {activeTab === 'dependencies' && (
              <DependenciesTab container={container} />
            )}
            {activeTab === 'settings' && (
              <SettingsTab container={container} onUpdate={onUpdate} />
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
