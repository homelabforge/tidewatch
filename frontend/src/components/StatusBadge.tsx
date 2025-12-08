interface StatusBadgeProps {
  status: string;
  className?: string;
}

export default function StatusBadge({ status, className = '' }: StatusBadgeProps) {
  const getStatusColor = (status: string) => {
    const normalizedStatus = status.toLowerCase();

    // Restart-specific statuses
    if (normalizedStatus.includes('restarted')) return 'bg-blue-500/20 text-blue-400 border-blue-500/30';
    if (normalizedStatus.includes('failed_to_restart')) return 'bg-red-500/20 text-red-400 border-red-500/30';
    if (normalizedStatus.includes('crashed')) return 'bg-orange-500/20 text-orange-400 border-orange-500/30';

    // Update statuses
    if (normalizedStatus.includes('completed')) return 'bg-green-500/20 text-green-400 border-green-500/30';
    if (normalizedStatus.includes('success')) return 'bg-green-500/20 text-green-400 border-green-500/30';
    if (normalizedStatus.includes('running')) return 'bg-green-500/20 text-green-400 border-green-500/30';
    if (normalizedStatus.includes('pending_retry')) return 'bg-orange-500/20 text-orange-400 border-orange-500/30';
    if (normalizedStatus.includes('pending')) return 'bg-yellow-500/20 text-yellow-400 border-yellow-500/30';
    if (normalizedStatus.includes('approved')) return 'bg-blue-500/20 text-blue-400 border-blue-500/30';
    if (normalizedStatus.includes('applied')) return 'bg-primary/20 text-primary border-primary/30';
    if (normalizedStatus.includes('rejected')) return 'bg-tide-border-light/20 text-tide-text-muted border-gray-500/30';
    if (normalizedStatus.includes('failed') || normalizedStatus.includes('error')) return 'bg-red-500/20 text-red-400 border-red-500/30';
    if (normalizedStatus.includes('stopped') || normalizedStatus.includes('exited')) return 'bg-tide-border-light/20 text-tide-text-muted border-gray-500/30';
    if (normalizedStatus.includes('rolled_back')) return 'bg-yellow-500/20 text-yellow-400 border-yellow-500/30';

    return 'bg-tide-border-light/20 text-tide-text-muted border-gray-500/30';
  };

  const getStatusLabel = (status: string) => {
    // Convert snake_case to Title Case with spaces
    return status
      .split('_')
      .map(word => word.charAt(0).toUpperCase() + word.slice(1).toLowerCase())
      .join(' ');
  };

  return (
    <span className={`px-2.5 py-0.5 rounded-full text-xs font-medium border ${getStatusColor(status)} ${className}`}>
      {getStatusLabel(status)}
    </span>
  );
}
