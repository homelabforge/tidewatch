import { useQuery } from '@tanstack/react-query';
import { api } from '../services/api';

/**
 * Reactive single-container selector backed by the shared `['containers','all']`
 * cache. No extra HTTP — derives via `select` from the list query, so any
 * mutation that invalidates `['containers','all']` reflects here automatically.
 */
export function useContainer(id: number | undefined) {
  return useQuery({
    queryKey: ['containers', 'all'] as const,
    queryFn: () => api.containers.getAll(),
    select: (list) => list.find((c) => c.id === id),
    enabled: id != null,
  });
}
