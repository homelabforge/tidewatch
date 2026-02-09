// Container types
export interface Container {
  id: number;
  name: string;
  image: string;
  current_tag: string;
  current_digest: string | null;
  registry: string;
  compose_file: string;
  service_name: string;
  policy: string;
  scope: string;
  include_prereleases: boolean | null;
  vulnforge_enabled: boolean;
  current_vuln_count: number;
  is_my_project: boolean;
  update_available: boolean;
  latest_tag: string | null;
  latest_major_tag: string | null;
  last_checked: string | null;
  last_updated: string | null;
  labels: Record<string, string>;
  health_check_url: string | null;
  health_check_method: string;
  health_check_has_auth: boolean;
  release_source: string | null;
  auto_restart_enabled: boolean;
  restart_policy: string;
  restart_max_attempts: number;
  restart_backoff_strategy: string;
  restart_success_window: number;
  update_window: string | null;
  dependencies: string[];
  dependents: string[];
  created_at: string;
  updated_at: string;
}

export interface Mount {
  source: string;
  destination: string;
  type: string;
  read_only: boolean;
}

// Update types
export interface Update {
  id: number;
  container_id: number;
  container_name: string;
  from_tag: string;
  to_tag: string;
  registry: string;
  reason_type: string;
  reason_summary: string | null;
  recommendation: string | null;
  changelog: string | null;
  changelog_url: string | null;
  cves_fixed: string[];
  current_vulns: number;
  new_vulns: number;
  vuln_delta: number;
  published_date: string | null;
  image_size_delta: number;
  status: string;
  scope_violation: number;
  approved_by: string | null;
  approved_at: string | null;
  retry_count: number;
  max_retries: number;
  next_retry_at: string | null;
  last_error: string | null;
  backoff_multiplier: number;
  snoozed_until: string | null;
  created_at: string;
  updated_at: string;
  // Decision traceability
  update_kind: 'tag' | 'digest' | null;
  change_type: 'major' | 'minor' | 'patch' | null;
}

// History types
export interface UpdateHistory {
  id: number;
  container_id: number;
  container_name?: string; // Only in global history endpoint
  from_tag: string;
  to_tag: string;
  status: string;
  event_type?: string | null; // 'update', 'dependency_update', 'dependency_ignore', 'dependency_unignore'
  update_type: string | null;
  reason: string | null;
  reason_type: string | null;
  reason_summary: string | null;
  triggered_by: string;
  performed_by?: string | null; // Alias for triggered_by in some contexts
  can_rollback: boolean;
  rollback_available?: boolean; // Alias for can_rollback in some contexts
  backup_path: string | null;
  data_backup_id: string | null;
  data_backup_status: string | null; // success, failed, skipped, timeout
  error_message: string | null;
  cves_fixed: string[];
  duration_seconds: number | null;
  started_at: string;
  completed_at: string | null;
  rolled_back_at: string | null;

  // Dependency-specific fields (present for dependency ignore/unignore events)
  dependency_type?: string | null; // 'dockerfile', 'http_server', 'app_dependency'
  dependency_id?: number | null;
  dependency_name?: string | null;
}

export interface UnifiedHistoryEvent {
  // Common fields
  id: number;
  event_type: 'update' | 'restart' | 'dependency_ignore' | 'dependency_unignore' | 'dependency_update';
  container_id: number;
  container_name: string;
  status: string;
  started_at: string;
  completed_at: string | null;
  duration_seconds: number | null;
  error_message: string | null;
  performed_by: string;

  // Update-specific fields (present when event_type === 'update')
  from_tag?: string;
  to_tag?: string;
  update_type?: string | null;
  reason?: string | null;
  reason_type?: string | null;
  reason_summary?: string | null;
  can_rollback?: boolean;
  rollback_available?: boolean;
  backup_path?: string | null;
  data_backup_id?: string | null;
  data_backup_status?: string | null;
  cves_fixed?: string[];
  rolled_back_at?: string | null;

  // Restart-specific fields (present when event_type === 'restart')
  attempt_number?: number;
  trigger_reason?: string;
  exit_code?: number | null;
  health_check_passed?: boolean | null;
  final_container_status?: string | null;

  // Dependency-specific fields (present when event_type includes 'dependency')
  dependency_type?: 'dockerfile' | 'http_server' | 'app_dependency' | null;
  dependency_id?: number | null;
  dependency_name?: string | null;
}

// Settings types
export interface Settings {
  update_settings: UpdateSettings;
  docker_settings: DockerSettings;
  integration_settings: IntegrationSettings;
  notification_settings: NotificationSettings;
  backup_settings: BackupSettings;
}

export interface UpdateSettings {
  auto_update_enabled: boolean;
  update_check_interval: number;
  update_strategy: string;
  rollback_enabled: boolean;
  max_concurrent_updates: number;
  update_window_start: string | null;
  update_window_end: string | null;
}

export interface DockerSettings {
  docker_host: string;
  compose_path: string;
  socket_proxy_enabled: boolean;
  registry_auth: Record<string, RegistryAuth>;
}

export interface RegistryAuth {
  username: string;
  password: string;
}

export interface IntegrationSettings {
  vulnforge_enabled: boolean;
  vulnforge_url: string;
  vulnforge_api_key: string;
}

export interface NotificationSettings {
  email_enabled: boolean;
  email_recipients: string[];
  webhook_enabled: boolean;
  webhook_url: string;
  notify_on_update_available: boolean;
  notify_on_update_applied: boolean;
  notify_on_update_failed: boolean;
}

export interface BackupSettings {
  backup_enabled: boolean;
  backup_path: string;
  backup_retention_days: number;
}

// System types
export interface SystemInfo {
  version: string;
  docker_version: string;
  total_containers: number;
  monitored_containers: number;
  pending_updates: number;
  auto_update_enabled: boolean;
}

export interface ContainerMetrics {
  cpu_percent: number;
  memory_usage: number;
  memory_limit: number;
  memory_percent: number;
  network_rx: number;
  network_tx: number;
  block_read: number;
  block_write: number;
  pids: number;
}

export interface ContainerLogs {
  logs: string[];
  timestamp: string;
}

// Filter and sort types
export interface FilterOptions {
  search: string;
  status: string;
  autoUpdate: string;
  hasUpdate: string;
}

export interface SortOption {
  field: string;
  direction: 'asc' | 'desc';
}

// Backup types
export interface BackupFile {
  filename: string;
  size_mb: number;
  size_bytes: number;
  created: string;
  is_safety: boolean;
}

export interface BackupStats {
  database_path: string;
  database_size: number;
  database_modified: string;
  database_exists: boolean;
  total_backups: number;
  total_size: number;
  backup_directory: string;
}

export interface BackupListResponse {
  backups: BackupFile[];
  stats: BackupStats;
}

// Test connection types
export interface TestConnectionResult {
  success: boolean;
  message: string;
  details?: Record<string, unknown>;
}

// Settings individual value type
export interface SettingValue {
  key: string;
  value: unknown;
  category: string;
  description: string | null;
  encrypted: boolean;
  created_at: string;
  updated_at: string;
}

// Settings category type
export interface SettingCategory {
  category: string;
  settings: SettingValue[];
}

// Auto-Restart types
export interface RestartState {
  id: number;
  container_id: number;
  container_name: string;
  consecutive_failures: number;
  total_restarts: number;
  last_exit_code: number | null;
  last_failure_reason: string | null;
  current_backoff_seconds: number;
  next_retry_at: string | null;
  max_retries_reached: boolean;
  last_successful_start: string | null;
  last_failure_at: string | null;
  success_window_seconds: number;
  enabled: boolean;
  max_attempts: number;
  backoff_strategy: string;
  base_delay_seconds: number;
  max_delay_seconds: number;
  health_check_enabled: boolean;
  health_check_timeout: number;
  rollback_on_health_fail: boolean;
  paused_until: string | null;
  pause_reason: string | null;
  restart_history: string[];
  created_at: string;
  updated_at: string;
  is_paused: boolean;
  is_ready_for_retry: boolean;
  uptime_seconds: number | null;
}

export interface EnableRestartConfig {
  max_attempts: number;
  backoff_strategy: 'exponential' | 'linear' | 'fixed';
  base_delay_seconds: number;
  max_delay_seconds: number;
  success_window_seconds: number;
  health_check_enabled: boolean;
  health_check_timeout: number;
  rollback_on_health_fail: boolean;
}

export interface RestartLog {
  id: number;
  container_id: number;
  attempt_number: number;
  trigger_reason: string;
  exit_code: number | null;
  backoff_delay_seconds: number;
  success: boolean;
  health_check_passed: boolean | null;
  error_message: string | null;
  scheduled_at: string;
  executed_at: string | null;
  completed_at: string | null;
}

export interface RestartStats {
  total_containers: number;
  containers_with_restart_enabled: number;
  total_restarts_24h: number;
  total_restarts_7d: number;
  containers_with_failures: number;
  average_backoff_seconds: number;
}

// Dependency types
export interface DependencyInfo {
  dependencies: string[];
  dependents: string[];
}

// Update Window types
export interface UpdateWindowInfo {
  update_window: string | null;
  valid: boolean;
  error: string | null;
  examples: string[];
}

// Analytics types
export interface AnalyticsSummary {
  period_days: number;
  total_updates: number;
  successful_updates: number;
  failed_updates: number;
  update_frequency: Record<string, number>;
  vulnerability_trends: Record<string, number>;
  policy_distribution: Record<string, number>;
  avg_update_duration_seconds: number;
  total_cves_fixed: number;
  updates_with_cves: number;
}

// Event streaming types
export interface ServerEvent {
  type: string;
  data: Record<string, unknown>;
  timestamp: string;
}

// App Dependencies types
export interface AppDependency {
  id: number;
  name: string;
  ecosystem: string; // npm, pypi, composer, cargo, go, engine, package-manager
  current_version: string;
  latest_version: string | null;
  update_available: boolean;
  security_advisories: number;
  socket_score: number | null; // Socket.dev security score (0-100)
  severity: string; // critical, high, medium, low, info
  dependency_type: 'production' | 'development' | 'optional' | 'peer'; // production, development, optional, peer
  manifest_file: string;
  ignored: boolean;
  ignored_version: string | null;
  ignored_by: string | null;
  ignored_at: string | null;
  ignored_reason: string | null;
  last_checked: string | null;
}

export interface AppDependenciesResponse {
  dependencies: AppDependency[];
  total: number;
  with_updates: number;
  with_security_issues: number;
  last_scan: string | null;
  scan_status: string; // idle, scanning, error
}

// Batch dependency update types
export interface BatchDependencyUpdateItem {
  id: number;
  name: string;
  from_version: string;
  to_version: string;
  success: boolean;
  error?: string;
  backup_path?: string;
  history_id?: number;
}

export interface BatchDependencyUpdateSummary {
  total: number;
  updated_count: number;
  failed_count: number;
}

export interface BatchDependencyUpdateResponse {
  updated: BatchDependencyUpdateItem[];
  failed: BatchDependencyUpdateItem[];
  summary: BatchDependencyUpdateSummary;
}

// Dockerfile Dependencies types
export interface DockerfileDependency {
  id: number;
  container_id: number;
  dependency_type: 'base_image' | 'build_image';
  image_name: string;
  current_tag: string;
  registry: string;
  full_image: string;
  latest_tag: string | null;
  update_available: boolean;
  severity: 'critical' | 'high' | 'medium' | 'low' | 'info';
  ignored: boolean;
  ignored_version: string | null;
  ignored_by: string | null;
  ignored_at: string | null;
  ignored_reason: string | null;
  last_checked: string | null;
  dockerfile_path: string;
  line_number: number | null;
  stage_name: string | null;
  created_at: string;
  updated_at: string;
}

export interface DockerfileDependenciesResponse {
  dependencies: DockerfileDependency[];
  total: number;
  with_updates: number;
  last_scan: string | null;
  scan_status: 'idle' | 'scanning' | 'error';
}

// HTTP Server types
export interface HttpServer {
  id: number;
  name: string;
  current_version: string | null;
  latest_version: string | null;
  update_available: boolean;
  severity: 'critical' | 'high' | 'medium' | 'low' | 'info';
  detection_method: 'process' | 'version_command' | 'unknown';
  dockerfile_path: string | null;
  line_number: number | null;
  ignored: boolean;
  ignored_version: string | null;
  ignored_by: string | null;
  ignored_at: string | null;
  ignored_reason: string | null;
  last_checked: string | null;
}

export interface HttpServersResponse {
  servers: HttpServer[];
  total: number;
  with_updates: number;
  last_scan: string | null;
  scan_status: 'idle' | 'scanning' | 'error';
}

// Check Job types (background update check tracking)
export interface CheckJobProgress {
  job_id: number;
  status: 'queued' | 'running' | 'done' | 'failed' | 'canceled';
  total_count: number;
  checked_count: number;
  updates_found: number;
  errors_count: number;
  progress_percent: number;
  current_container: string | null;
}

export interface CheckJobResult {
  id: number;
  status: 'queued' | 'running' | 'done' | 'failed' | 'canceled';
  total_count: number;
  checked_count: number;
  updates_found: number;
  errors_count: number;
  progress_percent: number;
  current_container: string | null;
  triggered_by: string;
  started_at: string | null;
  completed_at: string | null;
  duration_seconds: number | null;
  error_message: string | null;
  results: CheckJobContainerResult[] | null;
  errors: CheckJobError[] | null;
}

export interface CheckJobContainerResult {
  container_id: number;
  container_name: string;
  update_found: boolean;
  from_tag?: string;
  to_tag?: string;
}

export interface CheckJobError {
  container_id: number;
  container_name: string;
  error: string;
}

export interface CheckJobSummary {
  id: number;
  status: 'queued' | 'running' | 'done' | 'failed' | 'canceled';
  total_count: number;
  checked_count: number;
  updates_found: number;
  errors_count: number;
  triggered_by: string;
  started_at: string | null;
  completed_at: string | null;
  duration_seconds: number | null;
}

export interface CheckJobStartResponse {
  success: boolean;
  job_id: number;
  status: string;
  message: string;
  already_running: boolean;
}

// Rollback types
export interface RollbackHistoryItem {
  history_id: number;
  from_version: string;
  to_version: string;
  updated_at: string;
  triggered_by: string;
}

export interface RollbackHistoryResponse {
  dependency_id: number;
  dependency_type: 'dockerfile' | 'http_server' | 'app_dependency';
  dependency_name: string;
  current_version: string;
  rollback_options: RollbackHistoryItem[];
}

export interface RollbackResponse {
  success: boolean;
  history_id: number | null;
  changes_made: string | null;
  error: string | null;
}
