import { Mail, RefreshCw, CircleCheck, Info } from 'lucide-react';
import { HelpTooltip } from '../HelpTooltip';

interface EmailConfigProps {
  settings: Record<string, unknown>;
  onSettingChange: (key: string, value: unknown) => void;
  onTextChange: (key: string, value: string) => void;
  onTest: () => void;
  testing: boolean;
  saving: boolean;
}

export function EmailConfig({ settings, onSettingChange, onTextChange, onTest, testing, saving }: EmailConfigProps) {
  return (
    <div className="bg-tide-surface rounded-lg p-6">
      <div className="flex items-start justify-between mb-4">
        <div className="flex items-center gap-3">
          <Mail className="w-6 h-6 text-teal-500" />
          <div>
            <h2 className="text-xl font-semibold text-tide-text">Email Configuration</h2>
            <p className="text-sm text-tide-text-muted mt-0.5">SMTP email notifications</p>
          </div>
        </div>
        <HelpTooltip content="Send notifications via email using SMTP. Works with any SMTP server including Gmail, Outlook, or self-hosted." />
      </div>

      <div className="space-y-4">
        <div className="flex items-center justify-between">
          <div>
            <label className="block text-sm font-medium text-tide-text">Enable Email</label>
            <p className="text-xs text-tide-text-muted mt-1">Send notifications via email</p>
          </div>
          <button
            type="button"
            onClick={() => onSettingChange('email_enabled', !settings.email_enabled)}
            disabled={saving}
            className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors focus:outline-none ${
              settings.email_enabled ? 'bg-teal-500' : 'bg-red-500'
            }`}
          >
            <span className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${
              settings.email_enabled ? 'translate-x-6' : 'translate-x-1'
            }`}></span>
          </button>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <div className="space-y-2">
            <label className="block">
              <span className="text-sm font-medium text-tide-text">SMTP Host</span>
              <p className="text-xs text-tide-text-muted mb-2">SMTP server hostname</p>
              <input
                placeholder="smtp.gmail.com"
                className="w-full px-3 py-2 bg-tide-surface border border-tide-border rounded-lg text-tide-text focus:outline-none focus:ring-2 focus:ring-teal-500"
                type="text"
                value={String(settings.email_smtp_host || '')}
                onChange={(e) => onTextChange('email_smtp_host', e.target.value)}
                disabled={saving}
              />
            </label>
          </div>

          <div className="space-y-2">
            <label className="block">
              <span className="text-sm font-medium text-tide-text">SMTP Port</span>
              <p className="text-xs text-tide-text-muted mb-2">Usually 587 (TLS) or 465 (SSL)</p>
              <input
                placeholder="587"
                className="w-full px-3 py-2 bg-tide-surface border border-tide-border rounded-lg text-tide-text focus:outline-none focus:ring-2 focus:ring-teal-500"
                type="number"
                value={String(settings.email_smtp_port || '587')}
                onChange={(e) => onTextChange('email_smtp_port', e.target.value)}
                disabled={saving}
              />
            </label>
          </div>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <div className="space-y-2">
            <label className="block">
              <span className="text-sm font-medium text-tide-text">Username</span>
              <p className="text-xs text-tide-text-muted mb-2">SMTP username</p>
              <input
                placeholder="user@example.com"
                className="w-full px-3 py-2 bg-tide-surface border border-tide-border rounded-lg text-tide-text focus:outline-none focus:ring-2 focus:ring-teal-500"
                type="text"
                value={String(settings.email_smtp_user || '')}
                onChange={(e) => onTextChange('email_smtp_user', e.target.value)}
                disabled={saving}
              />
            </label>
          </div>

          <div className="space-y-2">
            <label className="block">
              <span className="text-sm font-medium text-tide-text">Password</span>
              <p className="text-xs text-tide-text-muted mb-2">SMTP password or app password</p>
              <input
                placeholder="********"
                className="w-full px-3 py-2 bg-tide-surface border border-tide-border rounded-lg text-tide-text focus:outline-none focus:ring-2 focus:ring-teal-500"
                type="password"
                value={String(settings.email_smtp_password || '')}
                onChange={(e) => onTextChange('email_smtp_password', e.target.value)}
                disabled={saving}
              />
            </label>
          </div>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <div className="space-y-2">
            <label className="block">
              <span className="text-sm font-medium text-tide-text">From Address</span>
              <p className="text-xs text-tide-text-muted mb-2">Sender email address</p>
              <input
                placeholder="tidewatch@example.com"
                className="w-full px-3 py-2 bg-tide-surface border border-tide-border rounded-lg text-tide-text focus:outline-none focus:ring-2 focus:ring-teal-500"
                type="email"
                value={String(settings.email_from || '')}
                onChange={(e) => onTextChange('email_from', e.target.value)}
                disabled={saving}
              />
            </label>
          </div>

          <div className="space-y-2">
            <label className="block">
              <span className="text-sm font-medium text-tide-text">To Address</span>
              <p className="text-xs text-tide-text-muted mb-2">Recipient email address</p>
              <input
                placeholder="admin@example.com"
                className="w-full px-3 py-2 bg-tide-surface border border-tide-border rounded-lg text-tide-text focus:outline-none focus:ring-2 focus:ring-teal-500"
                type="email"
                value={String(settings.email_to || '')}
                onChange={(e) => onTextChange('email_to', e.target.value)}
                disabled={saving}
              />
            </label>
          </div>
        </div>

        <div className="flex items-center justify-between">
          <div>
            <label className="block text-sm font-medium text-tide-text">Use TLS</label>
            <p className="text-xs text-tide-text-muted mt-1">Enable STARTTLS encryption</p>
          </div>
          <button
            type="button"
            onClick={() => onSettingChange('email_smtp_tls', !settings.email_smtp_tls)}
            disabled={saving}
            className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors focus:outline-none ${
              settings.email_smtp_tls !== false ? 'bg-teal-500' : 'bg-gray-600'
            }`}
          >
            <span className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${
              settings.email_smtp_tls !== false ? 'translate-x-6' : 'translate-x-1'
            }`}></span>
          </button>
        </div>

        <button
          type="button"
          onClick={onTest}
          disabled={testing || !settings.email_enabled}
          className="px-4 py-2 bg-tide-surface hover:bg-tide-surface-light text-tide-text rounded-lg text-sm flex items-center gap-2 transition-colors disabled:opacity-50 border border-tide-border"
        >
          {testing ? <RefreshCw className="w-4 h-4 animate-spin" /> : <CircleCheck className="w-4 h-4" />}
          {testing ? 'Testing...' : 'Send Test Email'}
        </button>

        <div className="pt-4 border-t border-tide-border">
          <div className="p-3 bg-blue-500/10 rounded-lg border border-blue-500/30">
            <div className="flex items-start gap-2">
              <Info className="w-4 h-4 text-blue-400 mt-0.5 flex-shrink-0" />
              <div className="text-xs text-tide-text-muted">
                <p className="font-medium text-tide-text mb-1">Gmail Users</p>
                <p>Use an App Password instead of your regular password. Enable 2FA and generate one at Google Account settings.</p>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
