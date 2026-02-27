import { useEffect, useState } from 'react';
import { api } from '../services/api';
import { Waves, Shield, Database, RefreshCw, Bell, Sparkles, CheckCircle, Heart, ExternalLink } from 'lucide-react';

export default function About() {
  const [version, setVersion] = useState({ version: 'Loading...', docker_version: 'Loading...' });

  useEffect(() => {
    api.system.version().then(setVersion).catch(() => {});
  }, []);

  return (
    <div className="max-w-5xl mx-auto space-y-6">
      {/* Hero */}
      <div className="text-center">
        <div className="inline-flex items-center justify-center w-20 h-20 bg-primary/10 rounded-2xl mb-6">
          <Waves className="w-12 h-12 text-primary" />
        </div>
        <h1 className="text-4xl font-bold text-tide-text mb-3">
          Tide<span className="text-primary">Watch</span>
        </h1>
        <p className="text-xl text-tide-text-muted">Intelligent Docker Container Update Manager</p>
        <div className="mt-4 inline-block px-4 py-2 bg-primary/10 border border-primary/20 rounded-full">
          <span className="text-primary font-semibold">v{version.version}</span>
        </div>
      </div>

      {/* What is TideWatch */}
      <div className="bg-tide-surface rounded-lg border border-tide-border p-6">
        <h2 className="text-2xl font-bold text-tide-text mb-4">What is TideWatch?</h2>
        <p className="text-tide-text-muted leading-relaxed mb-4">
          TideWatch is a smart, security-focused container update manager built for homelabs and
          self-hosted environments. It monitors your running containers across multiple registries,
          detects available updates, enriches every candidate with CVE intelligence from VulnForge,
          and applies changes with rollback-safe automation—without blindly overwriting what's working.
        </p>
        <p className="text-tide-text-muted leading-relaxed">
          Built as a Watchtower replacement, TideWatch gives you full control over when and how
          containers update. It discovers services from your docker-compose files, respects configurable
          update windows, gates releases on post-update health checks, and keeps encrypted compose
          snapshots so every change is reversible.
        </p>
      </div>

      {/* Why TideWatch */}
      <div className="bg-tide-surface rounded-lg border border-tide-border p-6">
        <h2 className="text-2xl font-bold text-tide-text mb-4">Why TideWatch?</h2>
        <div className="space-y-3 text-tide-text-muted">
          <div className="flex items-start gap-3">
            <Shield className="w-5 h-5 text-primary mt-1 flex-shrink-0" />
            <div>
              <p className="font-semibold text-tide-text">Security First</p>
              <p className="text-sm">
                Never blindly update. Every candidate is enriched with CVE data from VulnForge so
                you can see vulnerability deltas before applying any change.
              </p>
            </div>
          </div>
          <div className="flex items-start gap-3">
            <Database className="w-5 h-5 text-primary mt-1 flex-shrink-0" />
            <div>
              <p className="font-semibold text-tide-text">Encrypted Snapshots & Rollback</p>
              <p className="text-sm">
                Timestamped compose backups and Docker-native volume snapshots before every update.
                Health-check failures trigger automatic image and data rollback.
              </p>
            </div>
          </div>
          <div className="flex items-start gap-3">
            <RefreshCw className="w-5 h-5 text-primary mt-1 flex-shrink-0" />
            <div>
              <p className="font-semibold text-tide-text">Policy-Based Automation</p>
              <p className="text-sm">
                Auto, Monitor, or Off per container. Configurable patch/minor/major scopes, update
                windows, dependency ordering, and concurrency guards keep your stack stable.
              </p>
            </div>
          </div>
          <div className="flex items-start gap-3">
            <Bell className="w-5 h-5 text-primary mt-1 flex-shrink-0" />
            <div>
              <p className="font-semibold text-tide-text">Multi-Service Notifications</p>
              <p className="text-sm">
                7 notification providers (ntfy, Gotify, Pushover, Slack, Discord, Telegram, Email)
                with per-event toggles and a full audit trail for every applied change.
              </p>
            </div>
          </div>
        </div>
      </div>

      {/* Built with AI */}
      <div className="bg-tide-surface rounded-lg border border-tide-border p-6">
        <h2 className="text-2xl font-bold text-tide-text mb-4 flex items-center gap-2">
          <Sparkles className="w-5 h-5 text-yellow-400" />
          Built with AI
        </h2>
        <p className="text-tide-text-muted leading-relaxed mb-4">
          TideWatch is built through collaboration between human expertise and cutting-edge AI
          capabilities. Claude handles architecture design and full-stack development, Codex assists
          with bug fixing and security auditing, while the Operator guides product vision, requirements,
          and deployment strategy.
        </p>
        <ul className="space-y-2 text-tide-text-muted text-sm">
          <li className="flex items-start gap-2">
            <CheckCircle className="w-4 h-4 text-primary mt-0.5 flex-shrink-0" />
            <span>
              <strong className="text-tide-text">Claude</strong> – Full-stack architecture,
              feature development, and production-ready code delivery.
            </span>
          </li>
          <li className="flex items-start gap-2">
            <CheckCircle className="w-4 h-4 text-primary mt-0.5 flex-shrink-0" />
            <span>
              <strong className="text-tide-text">Operator</strong> – Product vision, requirements
              definition, VulnForge integration direction, and homelab deployment expertise.
            </span>
          </li>
          <li className="flex items-start gap-2">
            <CheckCircle className="w-4 h-4 text-primary mt-0.5 flex-shrink-0" />
            <span>
              <strong className="text-tide-text">Codex</strong> – Bug fixing, security auditing,
              and code quality improvements.
            </span>
          </li>
        </ul>
      </div>

      {/* Powered by VulnForge */}
      <div className="bg-tide-surface rounded-lg border border-tide-border border-l-4 border-l-accent p-6">
        <h2 className="text-2xl font-bold text-tide-text mb-4 flex items-center gap-2">
          <Shield className="w-6 h-6 text-accent" />
          Powered by VulnForge
        </h2>
        <p className="text-tide-text-muted leading-relaxed mb-3">
          TideWatch integrates with VulnForge to provide vulnerability intelligence for every update
          decision. When an update is detected, TideWatch queries VulnForge to compare vulnerability
          counts, identify CVEs fixed or introduced, and surface security recommendations alongside
          the available tag.
        </p>
        <p className="text-tide-text-muted leading-relaxed">
          This integration gives you full visibility into the security impact of every update before
          you apply it—so updates improve your posture rather than quietly introduce new risk.
        </p>
      </div>

      {/* Learn More */}
      <div className="bg-tide-surface rounded-lg border border-tide-border p-6">
        <h2 className="text-2xl font-bold text-tide-text mb-4">Learn More</h2>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <a
            href="https://homelabforge.io/builds/tidewatch"
            target="_blank"
            rel="noopener noreferrer"
            className="flex items-center gap-2 px-4 py-2 bg-primary text-white rounded-lg hover:bg-primary/90 transition-colors text-sm font-medium"
          >
            <ExternalLink className="w-4 h-4" />
            Project Website
          </a>
          <a
            href="https://github.com/homelabforge/tidewatch"
            target="_blank"
            rel="noopener noreferrer"
            className="flex items-center gap-2 px-4 py-2 bg-primary text-white rounded-lg hover:bg-primary/90 transition-colors text-sm font-medium"
          >
            <ExternalLink className="w-4 h-4" />
            GitHub Repository
          </a>
        </div>
      </div>

      {/* Footer */}
      <div className="text-center pt-8 pb-8 border-t border-tide-border">
        <p className="text-tide-text-muted text-sm flex items-center justify-center gap-1">
          Made with <Heart className="w-4 h-4 text-red-500" /> for the homelab community
        </p>
        <p className="text-tide-text-muted text-xs mt-2">
          TideWatch v{version.version}
        </p>
      </div>
    </div>
  );
}
