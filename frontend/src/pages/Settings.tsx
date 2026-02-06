import { useState, useEffect, useRef } from 'react';
import { RotateCcw, Server, Plug, Bell, Database, RefreshCw, Cpu } from 'lucide-react';
import { toast } from 'sonner';
import { api } from '../services/api';
import type { SettingCategory } from '../types';
import { SystemTab, UpdatesTab, DockerTab, IntegrationsTab, NotificationsTab, BackupTab } from './settings-tabs';

type TabType = 'system' | 'updates' | 'docker' | 'integrations' | 'notifications' | 'backup';

export default function Settings() {
  const [activeTab, setActiveTab] = useState<TabType>('system');
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  // Settings state
  const [settings, setSettings] = useState<Record<string, unknown>>({});
  const [categories, setCategories] = useState<SettingCategory[]>([]);

  // Debounce timer for text inputs
  const debounceTimers = useRef<Record<string, number>>({});

  const tabs = [
    { id: 'system', label: 'System', icon: Cpu },
    { id: 'updates', label: 'Updates', icon: RotateCcw },
    { id: 'docker', label: 'Docker', icon: Server },
    { id: 'integrations', label: 'Integrations', icon: Plug },
    { id: 'notifications', label: 'Notifications', icon: Bell },
    { id: 'backup', label: 'Backup & Maintenance', icon: Database },
  ];

  // Load settings on mount
  useEffect(() => {
    loadSettings();
  }, []);

  const loadSettings = async () => {
    try {
      setLoading(true);
      const settingsData = await api.settings.getAll();
      setCategories([]); // Disable categories to show card-based UI
      const settingsMap: Record<string, unknown> = {};
      settingsData.forEach((setting) => {
        let value = setting.value;
        if (value === 'true') value = true;
        else if (value === 'false') value = false;
        else if (!isNaN(Number(value)) && value !== '') {
          value = Number(value);
        }
        settingsMap[setting.key] = value;
      });
      setSettings(settingsMap);
    } catch (error) {
      console.error('Failed to load settings:', error);
      toast.error('Failed to load settings');
    } finally {
      setLoading(false);
    }
  };

  const updateSetting = async (key: string, value: unknown, updateState: boolean = true) => {
    try {
      setSaving(true);
      const apiValue = String(value);
      await api.settings.update(key, apiValue);
      if (updateState) {
        setSettings((prev) => ({ ...prev, [key]: value }));
      }
      toast.success('Setting updated successfully');
    } catch (error) {
      console.error(`Failed to update ${key}:`, error);
      toast.error('Failed to update setting');
      await loadSettings();
    } finally {
      setSaving(false);
    }
  };

  const handleTextChange = (key: string, value: string) => {
    setSettings((prev) => ({ ...prev, [key]: value }));

    if (debounceTimers.current[key]) {
      clearTimeout(debounceTimers.current[key]);
    }

    debounceTimers.current[key] = setTimeout(async () => {
      await updateSetting(key, value, false);

      if (key === 'check_schedule') {
        try {
          await api.updates.reloadScheduler();
          toast.success('Scheduler reloaded with new schedule');
        } catch (error) {
          console.error('Failed to reload scheduler:', error);
          toast.error('Failed to reload scheduler');
        }
      }
    }, 1000);
  };

  if (loading) {
    return (
      <div className="min-h-screen bg-tide-bg flex items-center justify-center">
        <RefreshCw className="animate-spin text-primary" size={48} />
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-tide-bg">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        {/* Header */}
        <div className="mb-8">
          <h1 className="text-3xl font-bold text-tide-text mb-2">Settings</h1>
          <p className="text-tide-text-muted">Configure TideWatch to match your needs</p>
        </div>

        {/* Tabs */}
        <div className="border-b border-tide-border mb-6">
          <nav className="-mb-px flex space-x-8">
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

        {/* Content */}
        <div className="bg-tide-surface-light rounded-lg p-6 mt-6">
          {/* Category View Toggle (if categories available) */}
          {categories.length > 0 && (
            <div className="mb-6 pb-6 border-b border-tide-border">
              <div className="flex items-center justify-between">
                <div>
                  <h3 className="text-sm font-semibold text-tide-text mb-1">Settings Organization</h3>
                  <p className="text-xs text-tide-text-muted">
                    Settings are grouped by category. Click to expand/collapse sections.
                  </p>
                </div>
                <div className="text-xs text-teal-400 bg-teal-500/10 px-3 py-1 rounded-full border border-teal-500/30">
                  EXPERIMENTAL
                </div>
              </div>
            </div>
          )}

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
