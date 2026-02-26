import React from 'react';
import { RefreshCw, ChevronDown, Timer } from 'lucide-react';
import { Button } from '@/components/ui/button';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
  DropdownMenuSeparator,
} from '@/components/ui/dropdown-menu';
import { useKubernetesStore } from '@/stores/kubernetesStore';
import { useKubernetesConnection } from '@/contexts/KubernetesConnectionContext';
import { cn } from '@/lib/utils';

const REFRESH_INTERVALS = [
  { label: 'Off', value: 0 },
  { label: '1s', value: 1000 },
  { label: '5s', value: 5000 },
  { label: '10s', value: 10000 },
  { label: '30s', value: 30000 },
  { label: '1m', value: 60000 },
];

export function AutoRefreshControl() {
  const { 
    autoRefreshEnabled, 
    autoRefreshInterval, 
    isRefreshing, 
    nextRefreshTime,
    setAutoRefreshEnabled, 
    setAutoRefreshInterval,
    setNextRefreshTime
  } = useKubernetesStore();
  const { refreshAll, startPolling, stopPolling, connected } = useKubernetesConnection();
  
  const [countdown, setCountdown] = React.useState<number | null>(null);

  const currentInterval = REFRESH_INTERVALS.find(i => i.value === autoRefreshInterval) || REFRESH_INTERVALS[4]; // default 30s

  // Update countdown every 100ms for smooth display
  React.useEffect(() => {
    if (!autoRefreshEnabled || !nextRefreshTime) {
      setCountdown(null);
      return;
    }

    const updateCountdown = () => {
      const remaining = Math.max(0, nextRefreshTime - Date.now());
      setCountdown(remaining);
    };

    updateCountdown();
    const timer = setInterval(updateCountdown, 100);
    return () => clearInterval(timer);
  }, [autoRefreshEnabled, nextRefreshTime]);

  const handleIntervalChange = (interval: number) => {
    stopPolling();
    
    if (interval === 0) {
      setAutoRefreshEnabled(false);
      setAutoRefreshInterval(0);
      setNextRefreshTime(null);
    } else {
      setAutoRefreshEnabled(true);
      setAutoRefreshInterval(interval);
      // Immediately reset countdown with new interval
      setNextRefreshTime(Date.now() + interval);
      // Start polling with the new interval directly (bypass stale closure)
      startPolling(interval);
    }
  };

  const handleManualRefresh = async () => {
    if (connected) {
      await refreshAll();
      // Reset countdown after manual refresh
      if (autoRefreshEnabled && autoRefreshInterval > 0) {
        stopPolling();
        setNextRefreshTime(Date.now() + autoRefreshInterval);
        startPolling(autoRefreshInterval);
      }
    }
  };

  // Format countdown for display
  const formatCountdown = (ms: number) => {
    if (ms <= 0) return '0.0s';
    const seconds = ms / 1000;
    if (seconds < 10) {
      return `${seconds.toFixed(1)}s`;
    }
    return `${Math.round(seconds)}s`;
  };

  return (
    <div className="flex items-center gap-1">
      {/* Manual Refresh Button */}
      <Button
        variant="ghost"
        size="sm"
        onClick={handleManualRefresh}
        disabled={!connected || isRefreshing}
        className="h-8 px-2 text-muted-foreground hover:text-foreground"
        title="Refresh now"
      >
        <RefreshCw className={cn('h-4 w-4', isRefreshing && 'animate-spin')} />
      </Button>

      {/* Countdown Display */}
      {autoRefreshEnabled && countdown !== null && (
        <div className="hidden sm:flex items-center gap-1 text-xs text-muted-foreground px-2 min-w-[60px]">
          <Timer className="h-3 w-3" />
          <span className="font-mono tabular-nums">{formatCountdown(countdown)}</span>
        </div>
      )}

      {/* Interval Selector */}
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button
            variant="outline"
            size="sm"
            className={cn(
              'h-8 gap-1 text-xs font-medium',
              autoRefreshEnabled && 'border-primary/50 text-primary'
            )}
            disabled={!connected}
          >
            {autoRefreshEnabled && (
              <span className="relative flex h-2 w-2">
                <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-primary opacity-75"></span>
                <span className="relative inline-flex rounded-full h-2 w-2 bg-primary"></span>
              </span>
            )}
            {autoRefreshEnabled ? currentInterval.label : 'Off'}
            <ChevronDown className="h-3 w-3 opacity-50" />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end" className="w-28">
          {REFRESH_INTERVALS.map((interval) => (
            <DropdownMenuItem
              key={interval.value}
              onClick={() => handleIntervalChange(interval.value)}
              className={cn(
                'text-sm',
                (autoRefreshEnabled ? autoRefreshInterval : 0) === interval.value && 'bg-accent'
              )}
            >
              {interval.label}
            </DropdownMenuItem>
          ))}
          <DropdownMenuSeparator />
          <div className="px-2 py-1.5 text-[10px] text-muted-foreground">
            Auto-refresh interval
          </div>
        </DropdownMenuContent>
      </DropdownMenu>
    </div>
  );
}