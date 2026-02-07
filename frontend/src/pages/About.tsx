import { useEffect, useState } from 'react';
import { api } from '../services/api';
import { Shield, CircleCheckBig, Code, Layers, RefreshCw, RotateCw, Package, Activity, ChartColumn, Database, Waves, Sparkles } from 'lucide-react';

export default function About() {
  const [version, setVersion] = useState({ version: 'Loading...', docker_version: 'Loading...' });

  useEffect(() => {
    api.system.version().then(setVersion).catch(() => {});
  }, []);

  return (
    <div className="min-h-screen bg-tide-bg">
      <div className="max-w-4xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        {/* Header */}
        <div className="text-center mb-12">
          <div className="flex items-center justify-center gap-3 mb-4">
            <Waves className="w-12 h-12 text-primary" />
            <h1 className="text-4xl font-bold text-tide-text">
              Tide<span className="text-primary">Watch</span>
            </h1>
          </div>
          <p className="text-xl text-tide-text-muted">Intelligent Docker Container Update Manager</p>
          <p className="text-sm text-tide-text-muted mt-2">Version {version.version}</p>
        </div>

        {/* Description */}
        <div className="bg-tide-surface border border-tide-border rounded-lg p-6 mb-6">
          <h2 className="text-2xl font-bold text-tide-text mb-4">What is TideWatch?</h2>
          <div className="text-tide-text space-y-3">
            <p>
              TideWatch is a smart, security-focused container update manager built for homelabs and production
              environments. Digest-aware registry monitoring pairs with VulnForge intelligence, so you always
              know when an image changed and whether it improves your security posture.
            </p>
            <p>
              Built as a Watchtower replacement, TideWatch gives you full control over when and how containers
              update. It discovers services from your docker-compose files, tracks updates across multiple
              registries, enriches every update with CVE information, and applies changes with configuration
              snapshots, custom compose command parity, and post-update health checks—all while respecting
              your update policies.
            </p>
          </div>
        </div>

        {/* Why TideWatch */}
        <div className="bg-tide-surface border border-tide-border rounded-lg p-6 mb-6">
          <h2 className="text-2xl font-bold text-tide-text mb-4">Why TideWatch?</h2>
          <div className="space-y-3 text-tide-text">
            <div className="flex items-start gap-3">
              <Shield className="w-5 h-5 text-primary mt-1 flex-shrink-0" />
              <div>
                <p className="font-semibold">Security First</p>
                <p className="text-sm text-tide-text-muted">Never blindly update. Every change includes CVE tracking, vulnerability deltas, and digest comparisons for true change detection.</p>
              </div>
            </div>
            <div className="flex items-start gap-3">
              <Database className="w-5 h-5 text-primary mt-1 flex-shrink-0" />
              <div>
                <p className="font-semibold">Encrypted Configuration Snapshots</p>
                <p className="text-sm text-tide-text-muted">Store settings in SQLite with encrypted exports, plus compose backups before every change.</p>
              </div>
            </div>
            <div className="flex items-start gap-3">
              <RefreshCw className="w-5 h-5 text-primary mt-1 flex-shrink-0" />
              <div>
                <p className="font-semibold">Health-Gated Rollbacks</p>
                <p className="text-sm text-tide-text-muted">Post-update health checks gate releases and roll back automatically if containers falter.</p>
              </div>
            </div>
            <div className="flex items-start gap-3">
              <Waves className="w-5 h-5 text-primary mt-1 flex-shrink-0" />
              <div>
                <p className="font-semibold">Watchtower Replacement</p>
                <p className="text-sm text-tide-text-muted">Drop-in replacement with smarter policies, multi-service notifications (ntfy, Gotify, Pushover, Slack, Discord, Telegram, Email), and audit trails.</p>
              </div>
            </div>
          </div>
        </div>

        {/* Features */}
        <div className="bg-tide-surface border border-tide-border rounded-lg p-6 mb-6">
          <h2 className="text-2xl font-bold text-tide-text mb-6">Key Features</h2>
          <div className="space-y-4">
            <details className="group border border-tide-border rounded-lg bg-tide-surface" open>
              <summary className="flex flex-col gap-2 md:flex-row md:items-center md:justify-between px-4 py-4 cursor-pointer select-none">
                <span className="flex items-center gap-3 text-tide-text font-semibold">
                  <RefreshCw className="w-5 h-5 text-primary" />
                  Smart Update Detection
                </span>
                <span className="text-sm text-tide-text-muted md:text-right">Digest-aware monitoring across Docker Hub, GHCR, and LSCR.</span>
              </summary>
              <ul className="px-6 pb-5 space-y-3 text-sm text-tide-text">
                <li className="flex items-start gap-2">
                  <CircleCheckBig className="w-4 h-4 text-green-500 mt-0.5 flex-shrink-0" />
                  <span>Multi-registry coverage with automatic tag discovery and digest comparisons for "latest" images.</span>
                </li>
                <li className="flex items-start gap-2">
                  <CircleCheckBig className="w-4 h-4 text-green-500 mt-0.5 flex-shrink-0" />
                  <span>Semantic version normalization with configurable patch/minor/major scopes.</span>
                </li>
                <li className="flex items-start gap-2">
                  <CircleCheckBig className="w-4 h-4 text-green-500 mt-0.5 flex-shrink-0" />
                  <span>Rate-limit optimized polling with caching and early exits when registries stay quiet.</span>
                </li>
              </ul>
            </details>

            <details className="group border border-tide-border rounded-lg bg-tide-surface">
              <summary className="flex flex-col gap-2 md:flex-row md:items-center md:justify-between px-4 py-4 cursor-pointer select-none">
                <span className="flex items-center gap-3 text-tide-text font-semibold">
                  <Shield className="w-5 h-5 text-primary" />
                  Security-Driven Updates
                </span>
                <span className="text-sm text-tide-text-muted md:text-right">VulnForge intelligence ensures every update improves security posture.</span>
              </summary>
              <ul className="px-6 pb-5 space-y-3 text-sm text-tide-text">
                <li className="flex items-start gap-2">
                  <CircleCheckBig className="w-4 h-4 text-green-500 mt-0.5 flex-shrink-0" />
                  <span>Automatic CVE tracking with vulnerability delta comparisons between current and candidate images.</span>
                </li>
                <li className="flex items-start gap-2">
                  <CircleCheckBig className="w-4 h-4 text-green-500 mt-0.5 flex-shrink-0" />
                  <span>Security policies block updates that raise risk while highlighting critical/high fixes.</span>
                </li>
                <li className="flex items-start gap-2">
                  <CircleCheckBig className="w-4 h-4 text-green-500 mt-0.5 flex-shrink-0" />
                  <span>Triggered-by auditing for every applied change, surfaced in history and dashboard timelines.</span>
                </li>
              </ul>
            </details>

            <details className="group border border-tide-border rounded-lg bg-tide-surface">
              <summary className="flex flex-col gap-2 md:flex-row md:items-center md:justify-between px-4 py-4 cursor-pointer select-none">
                <span className="flex items-center gap-3 text-tide-text font-semibold">
                  <RotateCw className="w-5 h-5 text-primary" />
                  Intelligent Auto-Restart
                </span>
                <span className="text-sm text-tide-text-muted md:text-right">Smart container restart with exponential backoff and circuit breaker patterns.</span>
              </summary>
              <ul className="px-6 pb-5 space-y-3 text-sm text-tide-text">
                <li className="flex items-start gap-2">
                  <CircleCheckBig className="w-4 h-4 text-green-500 mt-0.5 flex-shrink-0" />
                  <span>Exponential backoff with jitter prevents restart storms and thundering herd problems.</span>
                </li>
                <li className="flex items-start gap-2">
                  <CircleCheckBig className="w-4 h-4 text-green-500 mt-0.5 flex-shrink-0" />
                  <span>Success window reset clears failure counters after 5 minutes of stable operation.</span>
                </li>
                <li className="flex items-start gap-2">
                  <CircleCheckBig className="w-4 h-4 text-green-500 mt-0.5 flex-shrink-0" />
                  <span>Exit code analysis makes smart retry decisions based on failure type (skip config errors, retry application crashes).</span>
                </li>
                <li className="flex items-start gap-2">
                  <CircleCheckBig className="w-4 h-4 text-green-500 mt-0.5 flex-shrink-0" />
                  <span>Circuit breaker with max retries, pause controls, and health check validation for operational safety.</span>
                </li>
              </ul>
            </details>

            <details className="group border border-tide-border rounded-lg bg-tide-surface">
              <summary className="flex flex-col gap-2 md:flex-row md:items-center md:justify-between px-4 py-4 cursor-pointer select-none">
                <span className="flex items-center gap-3 text-tide-text font-semibold">
                  <Package className="w-5 h-5 text-primary" />
                  Compose-Aware Automation
                </span>
                <span className="text-sm text-tide-text-muted md:text-right">Native docker-compose integration tuned for real-world stacks.</span>
              </summary>
              <ul className="px-6 pb-5 space-y-3 text-sm text-tide-text">
                <li className="flex items-start gap-2">
                  <CircleCheckBig className="w-4 h-4 text-green-500 mt-0.5 flex-shrink-0" />
                  <span>Automatic compose file discovery and service mapping from configured directories.</span>
                </li>
                <li className="flex items-start gap-2">
                  <CircleCheckBig className="w-4 h-4 text-green-500 mt-0.5 flex-shrink-0" />
                  <span>Custom compose command parity across apply and rollback workflows.</span>
                </li>
                <li className="flex items-start gap-2">
                  <CircleCheckBig className="w-4 h-4 text-green-500 mt-0.5 flex-shrink-0" />
                  <span>Timestamped compose backups plus encrypted configuration snapshots for restore.</span>
                </li>
                <li className="flex items-start gap-2">
                  <CircleCheckBig className="w-4 h-4 text-green-500 mt-0.5 flex-shrink-0" />
                  <span>Health-check and release-source detection directly from compose and registry metadata.</span>
                </li>
              </ul>
            </details>

            <details className="group border border-tide-border rounded-lg bg-tide-surface">
              <summary className="flex flex-col gap-2 md:flex-row md:items-center md:justify-between px-4 py-4 cursor-pointer select-none">
                <span className="flex items-center gap-3 text-tide-text font-semibold">
                  <CircleCheckBig className="w-5 h-5 text-primary" />
                  Policy-Based Automation
                </span>
                <span className="text-sm text-tide-text-muted md:text-right">Flexible update policies tailored to teams and homelabs alike.</span>
              </summary>
              <ul className="px-6 pb-5 space-y-3 text-sm text-tide-text">
                <li className="flex items-start gap-2">
                  <CircleCheckBig className="w-4 h-4 text-green-500 mt-0.5 flex-shrink-0" />
                  <span>Auto policy: zero-touch updates coordinated by the scheduler.</span>
                </li>
                <li className="flex items-start gap-2">
                  <CircleCheckBig className="w-4 h-4 text-green-500 mt-0.5 flex-shrink-0" />
                  <span>Security policy: only ship updates that reduce vulnerability counts.</span>
                </li>
                <li className="flex items-start gap-2">
                  <CircleCheckBig className="w-4 h-4 text-green-500 mt-0.5 flex-shrink-0" />
                  <span>Manual policy: review dashboards backed by reasoning, CVEs, and ntfy notifications.</span>
                </li>
              </ul>
            </details>

            <details className="group border border-tide-border rounded-lg bg-tide-surface">
              <summary className="flex flex-col gap-2 md:flex-row md:items-center md:justify-between px-4 py-4 cursor-pointer select-none">
                <span className="flex items-center gap-3 text-tide-text font-semibold">
                  <Activity className="w-5 h-5 text-primary" />
                  Operational Safety & Visibility
                </span>
                <span className="text-sm text-tide-text-muted md:text-right">Guardrails that keep updates reversible and observable.</span>
              </summary>
              <ul className="px-6 pb-5 space-y-3 text-sm text-tide-text">
                <li className="flex items-start gap-2">
                  <CircleCheckBig className="w-4 h-4 text-green-500 mt-0.5 flex-shrink-0" />
                  <span>Post-update health checks gate promotions and trigger automatic rollback on failure.</span>
                </li>
                <li className="flex items-start gap-2">
                  <CircleCheckBig className="w-4 h-4 text-green-500 mt-0.5 flex-shrink-0" />
                  <span>Digest-aware history with triggered-by attribution for every change.</span>
                </li>
                <li className="flex items-start gap-2">
                  <CircleCheckBig className="w-4 h-4 text-green-500 mt-0.5 flex-shrink-0" />
                  <span>Multi-service notifications (ntfy, Gotify, Pushover, Slack, Discord, Telegram, Email) with event-based routing and per-service configuration.</span>
                </li>
                <li className="flex items-start gap-2">
                  <CircleCheckBig className="w-4 h-4 text-green-500 mt-0.5 flex-shrink-0" />
                  <span>Automatic retry with exponential backoff (5min → 15min → 1hr → 4hrs) handles transient failures.</span>
                </li>
                <li className="flex items-start gap-2">
                  <CircleCheckBig className="w-4 h-4 text-green-500 mt-0.5 flex-shrink-0" />
                  <span>Update windows restrict updates to maintenance periods (e.g., "02:00-06:00", "Sat,Sun:00:00-23:59").</span>
                </li>
                <li className="flex items-start gap-2">
                  <CircleCheckBig className="w-4 h-4 text-green-500 mt-0.5 flex-shrink-0" />
                  <span>Dependency-ordered updates ensure databases update before apps, preventing out-of-order breakage.</span>
                </li>
                <li className="flex items-start gap-2">
                  <CircleCheckBig className="w-4 h-4 text-green-500 mt-0.5 flex-shrink-0" />
                  <span>Historical resource metrics and restart history for per-container operational insight.</span>
                </li>
              </ul>
            </details>
          </div>
        </div>

        {/* Technology Stack */}
        <div className="bg-tide-surface border border-tide-border rounded-lg p-6 mb-6">
          <h2 className="text-2xl font-bold text-tide-text mb-4">Technology Stack</h2>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            <div>
              <h3 className="text-tide-text font-semibold mb-3 flex items-center gap-2">
                <Code className="w-5 h-5 text-accent" />
                Backend
              </h3>
              <ul className="space-y-2 text-tide-text-muted text-sm">
                <li className="flex items-start gap-2">
                  <CircleCheckBig className="w-4 h-4 text-primary flex-shrink-0 mt-0.5" />
                  <span>Python 3.14+ with FastAPI and Granian</span>
                </li>
                <li className="flex items-start gap-2">
                  <CircleCheckBig className="w-4 h-4 text-primary flex-shrink-0 mt-0.5" />
                  <span>SQLAlchemy 2.x + SQLite (WAL) via aiosqlite</span>
                </li>
                <li className="flex items-start gap-2">
                  <CircleCheckBig className="w-4 h-4 text-primary flex-shrink-0 mt-0.5" />
                  <span>APScheduler orchestration with retry logic and dependency ordering</span>
                </li>
                <li className="flex items-start gap-2">
                  <CircleCheckBig className="w-4 h-4 text-primary flex-shrink-0 mt-0.5" />
                  <span>Docker Registry clients with digest tracking and normalized semver</span>
                </li>
                <li className="flex items-start gap-2">
                  <CircleCheckBig className="w-4 h-4 text-primary flex-shrink-0 mt-0.5" />
                  <span>VulnForge enrichment and security scoring</span>
                </li>
                <li className="flex items-start gap-2">
                  <CircleCheckBig className="w-4 h-4 text-primary flex-shrink-0 mt-0.5" />
                  <span>httpx async HTTP client with multi-service notifications (ntfy, Gotify, Pushover, Slack, Discord, Telegram) and aiosmtplib for email</span>
                </li>
                <li className="flex items-start gap-2">
                  <CircleCheckBig className="w-4 h-4 text-primary flex-shrink-0 mt-0.5" />
                  <span>Encrypted configuration snapshots and compose backup engine</span>
                </li>
                <li className="flex items-start gap-2">
                  <CircleCheckBig className="w-4 h-4 text-primary flex-shrink-0 mt-0.5" />
                  <span>Exponential backoff retry engine with update window validation</span>
                </li>
              </ul>
            </div>

            <div>
              <h3 className="text-tide-text font-semibold mb-3 flex items-center gap-2">
                <Layers className="w-5 h-5 text-accent" />
                Frontend
              </h3>
              <ul className="space-y-2 text-tide-text-muted text-sm">
                <li className="flex items-start gap-2">
                  <CircleCheckBig className="w-4 h-4 text-primary flex-shrink-0 mt-0.5" />
                  <span>React 19 + TypeScript with Vite 6</span>
                </li>
                <li className="flex items-start gap-2">
                  <CircleCheckBig className="w-4 h-4 text-primary flex-shrink-0 mt-0.5" />
                  <span>Tailwind CSS v4 with a responsive teal/orange theme</span>
                </li>
                <li className="flex items-start gap-2">
                  <CircleCheckBig className="w-4 h-4 text-primary flex-shrink-0 mt-0.5" />
                  <span>React Router v6 navigation with guarded routes</span>
                </li>
                <li className="flex items-start gap-2">
                  <CircleCheckBig className="w-4 h-4 text-primary flex-shrink-0 mt-0.5" />
                  <span>Sonner toast notifications and actionable alerts</span>
                </li>
                <li className="flex items-start gap-2">
                  <CircleCheckBig className="w-4 h-4 text-primary flex-shrink-0 mt-0.5" />
                  <span>date-fns formatting and Lucide iconography throughout the UI</span>
                </li>
              </ul>
            </div>
          </div>
        </div>

        {/* Project Statistics */}
        <div className="bg-tide-surface border border-tide-border rounded-lg p-6 mb-6">
          <h2 className="text-2xl font-bold text-tide-text mb-6">Project Statistics</h2>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div className="bg-tide-surface border border-tide-border rounded-lg p-4 flex items-start gap-4">
              <div className="flex-shrink-0">
                <ChartColumn className="w-6 h-6 text-primary" />
              </div>
              <div>
                <p className="text-sm font-semibold text-tide-text">Total Lines of Code</p>
                <p className="text-2xl font-bold text-primary mt-1">~32,300</p>
              </div>
            </div>
            <div className="bg-tide-surface border border-tide-border rounded-lg p-4 flex items-start gap-4">
              <div className="flex-shrink-0">
                <Code className="w-6 h-6 text-primary" />
              </div>
              <div>
                <p className="text-sm font-semibold text-tide-text">Python Backend</p>
                <p className="text-2xl font-bold text-primary mt-1">~22,600</p>
              </div>
            </div>
            <div className="bg-tide-surface border border-tide-border rounded-lg p-4 flex items-start gap-4">
              <div className="flex-shrink-0">
                <Activity className="w-6 h-6 text-primary" />
              </div>
              <div>
                <p className="text-sm font-semibold text-tide-text">TypeScript Frontend</p>
                <p className="text-2xl font-bold text-primary mt-1">~9,700</p>
              </div>
            </div>
            <div className="bg-tide-surface border border-tide-border rounded-lg p-4 flex items-start gap-4">
              <div className="flex-shrink-0">
                <Layers className="w-6 h-6 text-primary" />
              </div>
              <div>
                <p className="text-sm font-semibold text-tide-text">Interactive Pages</p>
                <p className="text-2xl font-bold text-primary mt-1">5</p>
              </div>
            </div>
          </div>
        </div>

        {/* Built with AI */}
        <div className="bg-tide-surface border border-tide-border rounded-lg p-6 mb-6">
          <h2 className="text-2xl font-bold text-tide-text mb-4 flex items-center gap-2">
            <Sparkles className="w-5 h-5 text-yellow-500" />
            Built with AI
          </h2>
          <p className="text-tide-text leading-relaxed mb-4">
            TideWatch is built by a collaborative crew blending human expertise with AI copilots. We pair Claude (Sonnet 4.5) and Codex (GPT-5) on architecture, security, and release polish, while Operator steers product vision and deployment strategy.
          </p>
          <ul className="space-y-2 text-tide-text text-sm">
            <li className="flex items-start gap-2">
              <CircleCheckBig className="w-4 h-4 text-primary mt-0.5 flex-shrink-0" />
              <span><strong>Claude (Sonnet 4.5)</strong> – Full-stack architecture, security integration, and production-ready code delivery across all phases.</span>
            </li>
            <li className="flex items-start gap-2">
              <CircleCheckBig className="w-4 h-4 text-primary mt-0.5 flex-shrink-0" />
              <span><strong>Codex (GPT-5)</strong> – Day-to-day engineering partner delivering documentation alignment, feature hardening, and release readiness across updates.</span>
            </li>
            <li className="flex items-start gap-2">
              <CircleCheckBig className="w-4 h-4 text-primary mt-0.5 flex-shrink-0" />
              <span><strong>Operator</strong> – Product vision, requirements, VulnForge integration direction, and homelab deployment expertise.</span>
            </li>
          </ul>
        </div>

        {/* Integration */}
        <div className="bg-tide-surface border border-tide-border rounded-lg p-6 mb-6 border-l-4 border-accent">
          <h2 className="text-2xl font-bold text-tide-text mb-4 flex items-center gap-2">
            <Shield className="w-6 h-6 text-accent" />
            Powered by VulnForge
          </h2>
          <p className="text-tide-text leading-relaxed mb-3">
            TideWatch integrates seamlessly with VulnForge to provide vulnerability intelligence for every update decision. When an update is detected, TideWatch queries VulnForge to compare vulnerability counts, identify CVEs fixed or introduced, and generate security recommendations.
          </p>
          <p className="text-tide-text leading-relaxed">
            This integration gives you full visibility into the security impact of every update. VulnForge enrichment shows CVEs fixed or introduced, so you can make informed decisions about which updates to apply.
          </p>
        </div>
      </div>
    </div>
  );
}
