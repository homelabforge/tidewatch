import { useState } from 'react';
import { toast } from 'sonner';
import { api } from '../../services/api';
import {
  NotificationSubTabs,
  type NotificationSubTab,
  EventNotificationsCard,
  NtfyConfig,
  GotifyConfig,
  PushoverConfig,
  SlackConfig,
  DiscordConfig,
  TelegramConfig,
  EmailConfig,
} from '../../components/notifications';

interface NotificationsTabProps {
  settings: Record<string, unknown>;
  saving: boolean;
  updateSetting: (key: string, value: unknown, updateState?: boolean) => Promise<void>;
  handleTextChange: (key: string, value: string) => void;
}

type NotificationTestType = 'ntfy' | 'gotify' | 'pushover' | 'slack' | 'discord' | 'telegram' | 'email';

export default function NotificationsTab({ settings, saving, updateSetting, handleTextChange }: NotificationsTabProps) {
  const [notificationSubTab, setNotificationSubTab] = useState<NotificationSubTab>('ntfy');
  const [testingNtfy, setTestingNtfy] = useState(false);
  const [testingGotify, setTestingGotify] = useState(false);
  const [testingPushover, setTestingPushover] = useState(false);
  const [testingSlack, setTestingSlack] = useState(false);
  const [testingDiscord, setTestingDiscord] = useState(false);
  const [testingTelegram, setTestingTelegram] = useState(false);
  const [testingEmail, setTestingEmail] = useState(false);

  const handleTestConnection = async (type: NotificationTestType) => {
    const setTestingState = {
      ntfy: setTestingNtfy,
      gotify: setTestingGotify,
      pushover: setTestingPushover,
      slack: setTestingSlack,
      discord: setTestingDiscord,
      telegram: setTestingTelegram,
      email: setTestingEmail,
    }[type];

    const testFunction = {
      ntfy: api.settings.testNtfy,
      gotify: api.settings.testGotify,
      pushover: api.settings.testPushover,
      slack: api.settings.testSlack,
      discord: api.settings.testDiscord,
      telegram: api.settings.testTelegram,
      email: api.settings.testEmail,
    }[type];

    try {
      setTestingState(true);
      const result = await testFunction();

      if (result.success) {
        toast.success(result.message, {
          description: result.details ? Object.entries(result.details).map(([k, v]) => `${k}: ${v}`).join(', ') : undefined,
        });
      } else {
        toast.error(result.message, {
          description: result.details ? Object.entries(result.details).map(([k, v]) => `${k}: ${v}`).join(', ') : undefined,
        });
      }
    } catch (error) {
      console.error(`Failed to test ${type} connection:`, error);
      toast.error(`Failed to test ${type} connection`);
    } finally {
      setTestingState(false);
    }
  };

  const testingStates: Record<NotificationTestType, boolean> = {
    ntfy: testingNtfy,
    gotify: testingGotify,
    pushover: testingPushover,
    slack: testingSlack,
    discord: testingDiscord,
    telegram: testingTelegram,
    email: testingEmail,
  };

  return (
    <div className="space-y-6">
      {/* Sub-tabs for notification services */}
      <NotificationSubTabs
        activeSubTab={notificationSubTab}
        onSubTabChange={setNotificationSubTab}
        enabledServices={{
          ntfy: Boolean(settings.ntfy_enabled),
          gotify: Boolean(settings.gotify_enabled),
          pushover: Boolean(settings.pushover_enabled),
          slack: Boolean(settings.slack_enabled),
          discord: Boolean(settings.discord_enabled),
          telegram: Boolean(settings.telegram_enabled),
          email: Boolean(settings.email_enabled),
        }}
      />

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Service Configuration */}
        <div>
          {notificationSubTab === 'ntfy' && (
            <NtfyConfig
              settings={settings}
              onSettingChange={updateSetting}
              onTextChange={handleTextChange}
              onTest={() => handleTestConnection('ntfy')}
              testing={testingStates.ntfy}
              saving={saving}
            />
          )}
          {notificationSubTab === 'gotify' && (
            <GotifyConfig
              settings={settings}
              onSettingChange={updateSetting}
              onTextChange={handleTextChange}
              onTest={() => handleTestConnection('gotify')}
              testing={testingStates.gotify}
              saving={saving}
            />
          )}
          {notificationSubTab === 'pushover' && (
            <PushoverConfig
              settings={settings}
              onSettingChange={updateSetting}
              onTextChange={handleTextChange}
              onTest={() => handleTestConnection('pushover')}
              testing={testingStates.pushover}
              saving={saving}
            />
          )}
          {notificationSubTab === 'slack' && (
            <SlackConfig
              settings={settings}
              onSettingChange={updateSetting}
              onTextChange={handleTextChange}
              onTest={() => handleTestConnection('slack')}
              testing={testingStates.slack}
              saving={saving}
            />
          )}
          {notificationSubTab === 'discord' && (
            <DiscordConfig
              settings={settings}
              onSettingChange={updateSetting}
              onTextChange={handleTextChange}
              onTest={() => handleTestConnection('discord')}
              testing={testingStates.discord}
              saving={saving}
            />
          )}
          {notificationSubTab === 'telegram' && (
            <TelegramConfig
              settings={settings}
              onSettingChange={updateSetting}
              onTextChange={handleTextChange}
              onTest={() => handleTestConnection('telegram')}
              testing={testingStates.telegram}
              saving={saving}
            />
          )}
          {notificationSubTab === 'email' && (
            <EmailConfig
              settings={settings}
              onSettingChange={updateSetting}
              onTextChange={handleTextChange}
              onTest={() => handleTestConnection('email')}
              testing={testingStates.email}
              saving={saving}
            />
          )}
        </div>

        {/* Event Notifications Card */}
        <EventNotificationsCard
          settings={settings}
          onSettingChange={updateSetting}
          onTextChange={handleTextChange}
          saving={saving}
          hasEnabledService={
            Boolean(settings.ntfy_enabled) ||
            Boolean(settings.gotify_enabled) ||
            Boolean(settings.pushover_enabled) ||
            Boolean(settings.slack_enabled) ||
            Boolean(settings.discord_enabled) ||
            Boolean(settings.telegram_enabled) ||
            Boolean(settings.email_enabled)
          }
        />
      </div>
    </div>
  );
}
