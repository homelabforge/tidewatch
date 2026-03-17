// ============================================================================
// Section A: Generated type aliases from OpenAPI schema
// Source of truth: backend Pydantic models → openapi.json → api.generated.ts
// Run `bun run generate:api` after backend schema changes and commit both files.
// ============================================================================

import type { components } from './api.generated';

export type Container = components['schemas']['ContainerSchema'];
export type Update = components['schemas']['UpdateSchema'];
export type HistoryItem = components['schemas']['HistoryItemSchema'];
export type UpdateHistoryDetail = components['schemas']['UpdateHistorySchema'];
export type UnifiedHistoryEvent = components['schemas']['UnifiedHistoryEventSchema'];
export type RestartState = components['schemas']['RestartStateSchema'];
export type RestartLog = components['schemas']['RestartLogSchema'];
export type RestartStats = components['schemas']['RestartStatsResponse'];
export type AppDependency = components['schemas']['AppDependencySchema'];
export type AppDependenciesResponse = components['schemas']['AppDependenciesResponse'];
export type DockerfileDependency = components['schemas']['DockerfileDependencySchema'];
export type DockerfileDependenciesResponse = components['schemas']['DockerfileDependenciesResponse'];
export type HttpServer = components['schemas']['HttpServerSchema'];
export type HttpServersResponse = components['schemas']['HttpServersResponse'];
export type AnalyticsSummary = components['schemas']['AnalyticsSummary'];
export type SettingCategory = components['schemas']['SettingCategory'];
export type SettingValue = components['schemas']['SettingSchema'];
export type BatchDependencyUpdateItem = components['schemas']['BatchDependencyUpdateItem'];
export type BatchDependencyUpdateSummary = components['schemas']['BatchDependencyUpdateSummary'];
export type BatchDependencyUpdateResponse = components['schemas']['BatchDependencyUpdateResponse'];
export type CheckJobResult = components['schemas']['CheckJobResult'];
export type CheckJobStartResponse = components['schemas']['CheckJobStartResponse'];
export type CheckJobSummary = components['schemas']['CheckJobSummary'];
export type RollbackHistoryItem = components['schemas']['RollbackHistoryItem'];
export type RollbackHistoryResponse = components['schemas']['RollbackHistoryResponse'];
export type RollbackResponse = components['schemas']['RollbackResponse'];

/** @deprecated Use HistoryItem (container history) or UpdateHistoryDetail (single record) */
export type UpdateHistory = HistoryItem;

// ============================================================================
// Section B: Hand-maintained frontend-only types
// These are either frontend-specific (not in OpenAPI) or require narrow unions
// ============================================================================

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

// Hand-maintained: backoff_strategy uses narrow union for form validation
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

// Dependency summary for My Projects badges
export interface DependencySummary {
  http_server_updates: number;
  dockerfile_updates: number;
  app_prod_updates: number;
  app_dev_updates: number;
}

// Dependency scan job (background scan tracking)
export interface DependencyScanJobState {
  jobId: number;
  status: 'queued' | 'running' | 'done' | 'failed' | 'canceled';
  totalCount: number;
  scannedCount: number;
  updatesFound: number;
  errorsCount: number;
  currentProject: string | null;
  progressPercent: number;
}

// Event streaming types
export interface ServerEvent {
  type: string;
  data: Record<string, unknown>;
  timestamp: string;
}

export interface ContainerLogs {
  logs: string[];
  timestamp: string;
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

export interface SystemInfo {
  version: string;
  docker_version: string;
  total_containers: number;
  monitored_containers: number;
  pending_updates: number;
  auto_update_enabled: boolean;
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

// Dependency info
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

// Check Job progress (frontend tracking, distinct from CheckJobResult)
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
