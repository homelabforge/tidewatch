/**
 * PageSkeleton - Loading skeleton for route transitions
 * Provides visual feedback during code-split route loading
 */
export default function PageSkeleton() {
  return (
    <div className="container mx-auto px-4 py-8 max-w-7xl">
      {/* Header skeleton */}
      <div className="mb-8 animate-pulse">
        <div className="h-8 bg-tide-surface rounded w-1/4 mb-4"></div>
        <div className="h-4 bg-tide-surface rounded w-1/2"></div>
      </div>

      {/* Content grid skeleton */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6 mb-8">
        {[1, 2, 3].map((i) => (
          <div
            key={i}
            className="bg-tide-surface border border-tide-border rounded-lg p-6 animate-pulse"
          >
            <div className="h-6 bg-tide-surface rounded w-3/4 mb-4"></div>
            <div className="h-4 bg-tide-surface rounded w-full mb-2"></div>
            <div className="h-4 bg-tide-surface rounded w-5/6"></div>
          </div>
        ))}
      </div>

      {/* Table skeleton */}
      <div className="bg-tide-surface border border-tide-border rounded-lg overflow-hidden animate-pulse">
        <div className="p-4 border-b border-tide-border">
          <div className="h-6 bg-tide-surface rounded w-1/3"></div>
        </div>
        <div className="divide-y divide-gray-800">
          {[1, 2, 3, 4, 5].map((i) => (
            <div key={i} className="p-4 flex items-center space-x-4">
              <div className="h-10 w-10 bg-tide-surface rounded"></div>
              <div className="flex-1 space-y-2">
                <div className="h-4 bg-tide-surface rounded w-3/4"></div>
                <div className="h-3 bg-tide-surface rounded w-1/2"></div>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
