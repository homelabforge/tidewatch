import { useState } from 'react';
import { Bell, ChevronDown, ChevronRight, RefreshCw, AlertTriangle, ArrowUpCircle, Settings2 } from 'lucide-react';

interface EventGroup {
  id: string;
  label: string;
  description: string;
  icon: React.ElementType;
  enabledKey: string;
  events: {
    key: string;
    label: string;
    description: string;
  }[];
}

const eventGroups: EventGroup[] = [
  {
    id: 'updates',
    label: 'Updates',
    description: 'Container update notifications',
    icon: ArrowUpCircle,
    enabledKey: 'notify_updates_enabled',
    events: [
      { key: 'notify_updates_available', label: 'Update Available', description: 'When a new version is detected' },
      { key: 'notify_updates_applied_success', label: 'Update Applied', description: 'When an update completes successfully' },
      { key: 'notify_updates_applied_failed', label: 'Update Failed', description: 'When an update fails to apply' },
      { key: 'notify_updates_rollback', label: 'Rollback', description: 'When a rollback is performed' },
    ],
  },
  {
    id: 'restarts',
    label: 'Restarts',
    description: 'Container restart notifications',
    icon: RefreshCw,
    enabledKey: 'notify_restarts_enabled',
    events: [
      { key: 'notify_restarts_scheduled', label: 'Restart Scheduled', description: 'When a restart is scheduled' },
      { key: 'notify_restarts_success', label: 'Restart Success', description: 'When a restart completes' },
      { key: 'notify_restarts_failure', label: 'Restart Failed', description: 'When a restart attempt fails' },
      { key: 'notify_restarts_max_retries', label: 'Max Retries Reached', description: 'When max restart attempts exceeded' },
    ],
  },
  {
    id: 'system',
    label: 'System',
    description: 'System-level notifications',
    icon: AlertTriangle,
    enabledKey: 'notify_system_enabled',
    events: [
      { key: 'notify_system_check_complete', label: 'Check Complete', description: 'When scheduled check finishes' },
      { key: 'notify_system_dockerfile_updates', label: 'Dockerfile Updates', description: 'When Dockerfile dependency updates found' },
    ],
  },
];

interface EventNotificationsCardProps {
  settings: Record<string, unknown>;
  onSettingChange: (key: string, value: boolean) => void;
  onTextChange: (key: string, value: string) => void;
  saving: boolean;
  hasEnabledService: boolean;
}

export function EventNotificationsCard({ settings, onSettingChange, onTextChange, saving, hasEnabledService }: EventNotificationsCardProps) {
  const [expandedGroups, setExpandedGroups] = useState<Set<string>>(new Set(['updates']));
  const [showAdvanced, setShowAdvanced] = useState(false);

  const toggleGroup = (groupId: string) => {
    setExpandedGroups((prev) => {
      const next = new Set(prev);
      if (next.has(groupId)) {
        next.delete(groupId);
      } else {
        next.add(groupId);
      }
      return next;
    });
  };

  if (!hasEnabledService) {
    return (
      <div className="bg-tide-surface/50 border border-tide-border rounded-lg p-6">
        <div className="flex items-center gap-3 mb-4">
          <Bell className="w-6 h-6 text-tide-text-muted" />
          <div>
            <h2 className="text-xl font-semibold text-tide-text">Event Notifications</h2>
            <p className="text-sm text-tide-text-muted mt-0.5">Configure which events trigger notifications</p>
          </div>
        </div>
        <div className="p-4 bg-yellow-500/10 rounded-lg border border-yellow-500/30">
          <p className="text-sm text-tide-text">
            Enable at least one notification service above to configure event notifications.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="bg-tide-surface rounded-lg p-6">
      <div className="flex items-center gap-3 mb-4">
        <Bell className="w-6 h-6 text-teal-500" />
        <div>
          <h2 className="text-xl font-semibold text-tide-text">Event Notifications</h2>
          <p className="text-sm text-tide-text-muted mt-0.5">Configure which events trigger notifications</p>
        </div>
      </div>

      <div className="space-y-3">
        {eventGroups.map((group) => {
          const Icon = group.icon;
          const isExpanded = expandedGroups.has(group.id);
          const isGroupEnabled = Boolean(settings[group.enabledKey]);

          return (
            <div key={group.id} className="border border-tide-border rounded-lg overflow-hidden">
              {/* Group Header */}
              <div className="flex items-center justify-between p-3 bg-tide-surface/50">
                <button
                  onClick={() => toggleGroup(group.id)}
                  className="flex items-center gap-3 flex-1 text-left"
                >
                  <Icon className={`w-5 h-5 ${isGroupEnabled ? 'text-teal-400' : 'text-tide-text-muted'}`} />
                  <div>
                    <span className="text-sm font-medium text-tide-text">{group.label}</span>
                    <p className="text-xs text-tide-text-muted">{group.description}</p>
                  </div>
                  {isExpanded ? (
                    <ChevronDown className="w-4 h-4 text-tide-text-muted ml-2" />
                  ) : (
                    <ChevronRight className="w-4 h-4 text-tide-text-muted ml-2" />
                  )}
                </button>
                <button
                  type="button"
                  onClick={() => onSettingChange(group.enabledKey, !isGroupEnabled)}
                  disabled={saving}
                  className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors focus:outline-none ${
                    isGroupEnabled ? 'bg-teal-500' : 'bg-red-500'
                  }`}
                >
                  <span className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${
                    isGroupEnabled ? 'translate-x-6' : 'translate-x-1'
                  }`}></span>
                </button>
              </div>

              {/* Group Events */}
              {isExpanded && isGroupEnabled && (
                <div className="p-3 pt-0 space-y-2">
                  {group.events.map((event) => {
                    const isEventEnabled = Boolean(settings[event.key]);

                    return (
                      <div
                        key={event.key}
                        className="flex items-center justify-between p-2 rounded-lg bg-tide-surface/30 hover:bg-tide-surface/50 transition-colors"
                      >
                        <div className="flex-1 min-w-0">
                          <span className="text-sm text-tide-text">{event.label}</span>
                          <p className="text-xs text-tide-text-muted truncate">{event.description}</p>
                        </div>
                        <button
                          type="button"
                          onClick={() => onSettingChange(event.key, !isEventEnabled)}
                          disabled={saving}
                          className={`relative inline-flex h-5 w-9 items-center rounded-full transition-colors focus:outline-none flex-shrink-0 ml-3 ${
                            isEventEnabled ? 'bg-teal-500' : 'bg-gray-600'
                          }`}
                        >
                          <span className={`inline-block h-3 w-3 transform rounded-full bg-white transition-transform ${
                            isEventEnabled ? 'translate-x-5' : 'translate-x-1'
                          }`}></span>
                        </button>
                      </div>
                    );
                  })}
                </div>
              )}

              {/* Collapsed but enabled indicator */}
              {!isExpanded && isGroupEnabled && (
                <div className="px-3 pb-2">
                  <p className="text-xs text-tide-text-muted">
                    {group.events.filter(e => Boolean(settings[e.key])).length} of {group.events.length} events enabled
                  </p>
                </div>
              )}
            </div>
          );
        })}
      </div>

      {/* Advanced Settings */}
      <div className="mt-4 border border-tide-border rounded-lg overflow-hidden">
        <button
          onClick={() => setShowAdvanced(!showAdvanced)}
          className="flex items-center gap-3 w-full p-3 bg-tide-surface/50 text-left"
        >
          <Settings2 className="w-5 h-5 text-tide-text-muted" />
          <div className="flex-1">
            <span className="text-sm font-medium text-tide-text">Advanced</span>
            <p className="text-xs text-tide-text-muted">Retry settings for high-priority notifications</p>
          </div>
          {showAdvanced ? (
            <ChevronDown className="w-4 h-4 text-tide-text-muted" />
          ) : (
            <ChevronRight className="w-4 h-4 text-tide-text-muted" />
          )}
        </button>

        {showAdvanced && (
          <div className="p-3 space-y-3">
            <div className="flex items-center justify-between gap-4">
              <div className="flex-1 min-w-0">
                <label className="text-sm text-tide-text">Retry Attempts</label>
                <p className="text-xs text-tide-text-muted">Max retries for urgent/high priority events</p>
              </div>
              <input
                type="number"
                min="1"
                max="10"
                value={String(settings.notification_retry_attempts ?? '3')}
                onChange={(e) => onTextChange('notification_retry_attempts', e.target.value)}
                disabled={saving}
                className="w-20 px-2 py-1 text-sm bg-tide-bg border border-tide-border rounded text-tide-text focus:outline-none focus:border-teal-500"
              />
            </div>
            <div className="flex items-center justify-between gap-4">
              <div className="flex-1 min-w-0">
                <label className="text-sm text-tide-text">Retry Delay (seconds)</label>
                <p className="text-xs text-tide-text-muted">Base delay between retry attempts</p>
              </div>
              <input
                type="number"
                min="0.5"
                max="30"
                step="0.5"
                value={String(settings.notification_retry_delay ?? '2.0')}
                onChange={(e) => onTextChange('notification_retry_delay', e.target.value)}
                disabled={saving}
                className="w-20 px-2 py-1 text-sm bg-tide-bg border border-tide-border rounded text-tide-text focus:outline-none focus:border-teal-500"
              />
            </div>
            <p className="text-xs text-tide-text-muted italic">
              Retries only apply to urgent/high priority events (failures, max retries reached)
            </p>
          </div>
        )}
      </div>
    </div>
  );
}
