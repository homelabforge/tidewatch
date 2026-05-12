import { useQuery } from '@tanstack/react-query';
import { api } from '../services/api';

// Inbound variants observed in the codebase. Normalized to canonical keys so
// query-key strings never drift between call sites.
export type DepTypeRaw =
  | 'app'
  | 'app_dependency'
  | 'dockerfile'
  | 'httpServer'
  | 'http_server';

type DepTypeCanonical = 'app' | 'dockerfile' | 'httpServer';

const NORMALIZE: Record<DepTypeRaw, DepTypeCanonical> = {
  app: 'app',
  app_dependency: 'app',
  dockerfile: 'dockerfile',
  httpServer: 'httpServer',
  http_server: 'httpServer',
};

export const dependencyTypeToQueryKey = (
  t: DepTypeRaw,
  containerId: number,
) => ['dependencies', NORMALIZE[t], containerId] as const;

/**
 * Cross-container dependency summary. Used by Dashboard and the dep-scan
 * completion handler. Swallows fetch errors to an empty summary so a transient
 * failure doesn't blank out the dashboard chrome — the broader page still
 * surfaces error states from its own queries.
 */
export function useDependencySummaryQuery() {
  return useQuery({
    queryKey: ['containers', 'dependencySummary'] as const,
    queryFn: () =>
      api.containers.getDependencySummary().catch(() => ({ summaries: {} })),
  });
}
