import { useCallback, useEffect, useMemo, useRef } from 'react';
import { useSearchParams } from 'react-router-dom';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { RotateCcw, Server, Plug, Bell, Database, RefreshCw, Cpu } from 'lucide-react';
import { toast } from 'sonner';
import { api, ApiError } from '../services/api';
import type { SettingValue, SettingCategory } from '../types';
import { SystemTab, UpdatesTab, DockerTab, IntegrationsTab, NotificationsTab, BackupTab } from './settings-tabs';

type TabType = 'system' | 'updates' | 'docker' | 'integrations' | 'notifications' | 'backup';

const tabs = [
  { id: 'system', label: 'System', icon: Cpu },
  { id: 'updates', label: 'Updates', icon: RotateCcw },
  { id: 'docker', label: 'Docker', icon: Server },
  { id: 'integrations', label: 'Integrations', icon: Plug },
  { id: 'notifications', label: 'Notifications', icon: Bell },
  { id: 'backup', label: 'Backup & Maintenance', icon: Database },
];

const SETTINGS_KEY = ['settings', 'all'] as const;
const EMPTY_CATEGORIES: SettingCategory[] = [];

// Coerce backend's stringified values to the JS types the UI expects.
function coerceSettings(raw: SettingValue[] | undefined): Record<string, unknown> {
  const map: Record<string, unknown> = {};
  if (!Array.isArray(raw)) return map;
  for (const setting of raw) {
    let value: unknown = setting.value;
    if (setting.value === 'true') value = true;
    else if (setting.value === 'false') value = false;
    else if (!isNaN(Number(setting.value)) && setting.value !== '') {
      value = Number(setting.value);
    }
    map[setting.key] = value;
  }
  return map;
}

export default function Settings() {
  const [searchParams, setSearchParams] = useSearchParams();
  const queryClient = useQueryClient();
  const debounceTimers = useRef<Record<string, number>>({});

  // Pattern D: derive activeTab directly from URL — no state mirror.
  const tabParam = searchParams.get('tab') as TabType | null;
  const activeTab: TabType =
    tabParam && tabs.some((t) => t.id === tabParam) ? tabParam : 'system';

  const setActiveTab = useCallback(
    (next: TabType) => {
      const sp = new URLSearchParams(searchParams);
      sp.set('tab', next);
      setSearchParams(sp);
    },
    [searchParams, setSearchParams],
  );

  const settingsQuery = useQuery({
    queryKey: SETTINGS_KEY,
    queryFn: () => api.settings.getAll(),
  });

  const settings = useMemo(
    () => coerceSettings(settingsQuery.data),
    [settingsQuery.data],
  );
  const loading = settingsQuery.isLoading;

  const settingsError = settingsQuery.error;
  useEffect(() => {
    if (settingsError) toast.error('Failed to load settings');
  }, [settingsError]);

  const invalidateSettings = useCallback(
    () => queryClient.invalidateQueries({ queryKey: SETTINGS_KEY }),
    [queryClient],
  );

  // Optimistically patch a single key in the cache so toggles and text inputs
  // update immediately without waiting for the server round-trip + refetch.
  const patchSettingInCache = useCallback(
    (key: string, value: unknown) => {
      queryClient.setQueryData<SettingValue[] | undefined>(
        SETTINGS_KEY,
        (old) =>
          old?.map((s) => (s.key === key ? { ...s, value: String(value) } : s)),
      );
    },
    [queryClient],
  );

  const updateMutation = useMutation({
    mutationFn: ({ key, value }: { key: string; value: unknown }) =>
      api.settings.update(key, String(value)),
    onSuccess: (_data, { key }) => {
      toast.success('Setting updated successfully');
      // Special case: reloading the scheduler when its schedule changed.
      if (key === 'check_schedule') {
        api.updates
          .reloadScheduler()
          .then(() => {
            queryClient.invalidateQueries({ queryKey: ['scheduler', 'status'] });
          })
          .catch(() => toast.error('Failed to reload scheduler'));
      }
      invalidateSettings();
    },
    onError: (error, { key }) => {
      console.error(`Failed to update ${key}:`, error);
      const message =
        error instanceof ApiError && error.status === 400
          ? error.message
          : 'Failed to update setting';
      toast.error(message);
      // Refetch reverts the optimistic patch.
      invalidateSettings();
    },
  });

  const saving = updateMutation.isPending;

  const updateSetting = useCallback(
    async (key: string, value: unknown, updateState: boolean = true) => {
      if (updateState) patchSettingInCache(key, value);
      await updateMutation.mutateAsync({ key, value });
    },
    [patchSettingInCache, updateMutation],
  );

  const handleTextChange = useCallback(
    (key: string, value: string) => {
      patchSettingInCache(key, value);
      if (debounceTimers.current[key]) {
        clearTimeout(debounceTimers.current[key]);
      }
      debounceTimers.current[key] = setTimeout(() => {
        updateMutation.mutate({ key, value });
      }, 1000) as unknown as number;
    },
    [patchSettingInCache, updateMutation],
  );

  const loadSettings = useCallback(async () => {
    await invalidateSettings();
  }, [invalidateSettings]);

  if (loading) {
    return (
      <div className="min-h-screen bg-tide-bg flex items-center justify-center">
        <RefreshCw className="animate-spin text-primary" size={48} />
      </div>
    );
  }

  // The categories feature was never wired to a real source (loadSettings used
  // to `setCategories([])` unconditionally). Kept as a stable empty array so
  // child tabs that take a SettingCategory[] prop don't have to be reworked.
  const categories: SettingCategory[] = EMPTY_CATEGORIES;

  return (
    <div className="min-h-screen bg-tide-bg">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        <div className="mb-8">
          <h1 className="text-3xl font-bold text-tide-text mb-2">Settings</h1>
          <p className="text-tide-text-muted">Configure TideWatch to match your needs</p>
        </div>

        <div className="border-b border-tide-border mb-6 overflow-x-auto">
          <nav className="-mb-px flex space-x-6 sm:space-x-8 min-w-max">
            {tabs.map((tab) => {
              const Icon = tab.icon;
              const isActive = activeTab === tab.id;
              return (
                <button
                  key={tab.id}
                  onClick={() => setActiveTab(tab.id as TabType)}
                  className={`flex items-center gap-2 px-1 py-4 border-b-2 font-medium text-sm transition-colors ${
                    isActive
                      ? 'border-primary text-primary'
                      : 'border-transparent text-tide-text-muted hover:text-tide-text hover:border-tide-border'
                  }`}
                >
                  <Icon size={18} />
                  {tab.label}
                </button>
              );
            })}
          </nav>
        </div>

        <div className="bg-tide-surface-light rounded-lg p-6 mt-6">
          {activeTab === 'system' && (
            <SystemTab
              settings={settings}
              saving={saving}
              updateSetting={updateSetting}
              handleTextChange={handleTextChange}
              categories={categories}
              loadSettings={loadSettings}
            />
          )}
          {activeTab === 'updates' && (
            <UpdatesTab
              settings={settings}
              saving={saving}
              updateSetting={updateSetting}
              handleTextChange={handleTextChange}
              categories={categories}
            />
          )}
          {activeTab === 'docker' && (
            <DockerTab
              settings={settings}
              saving={saving}
              updateSetting={updateSetting}
              handleTextChange={handleTextChange}
              categories={categories}
            />
          )}
          {activeTab === 'integrations' && (
            <IntegrationsTab
              settings={settings}
              saving={saving}
              updateSetting={updateSetting}
              handleTextChange={handleTextChange}
              categories={categories}
            />
          )}
          {activeTab === 'notifications' && (
            <NotificationsTab
              settings={settings}
              saving={saving}
              updateSetting={updateSetting}
              handleTextChange={handleTextChange}
            />
          )}
          {activeTab === 'backup' && (
            <BackupTab loadSettings={loadSettings} />
          )}
        </div>
      </div>
    </div>
  );
}
