
import { ChevronDown, Server } from 'lucide-react';
import { useNavigate, useLocation } from 'react-router-dom';
import { useKubernetesConnection } from '@/contexts/KubernetesConnectionContext';
import { cn } from '@/lib/utils';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
  DropdownMenuSeparator,
  DropdownMenuLabel,
} from '@/components/ui/dropdown-menu';
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '@/components/ui/tooltip';

export function ConnectionStatus() {
  const { connected, connecting, namespace, namespaces, baseUrl, error, switchNamespace } = useKubernetesConnection();
  const navigate = useNavigate();
  const location = useLocation();

  // Truncate baseUrl for display
  const truncatedUrl = baseUrl ? (baseUrl.length > 30 ? baseUrl.slice(0, 30) + '...' : baseUrl) : 'Not connected';

  const statusIndicator = (
    <div className="flex items-center gap-2">
      {connecting ? (
        <div className="h-2 w-2 rounded-full bg-warning animate-pulse" />
      ) : connected ? (
        <div className="relative flex h-2 w-2">
          <span className="relative inline-flex rounded-full h-2 w-2 bg-success"></span>
        </div>
      ) : (
        <div className="h-2 w-2 rounded-full bg-muted-foreground" />
      )}
      
      <span className="font-medium hidden md:inline">
        {connecting ? 'Connecting...' : connected ? namespace : 'Disconnected'}
      </span>
      
      {connected && <ChevronDown className="h-3 w-3 text-muted-foreground" />}
    </div>
  );

  // If not connected, just show status with tooltip
  if (!connected) {
    return (
      <TooltipProvider>
        <Tooltip>
          <TooltipTrigger asChild>
            <div 
              className={cn(
                'flex items-center gap-2 px-3 py-1.5 rounded-md text-xs cursor-default transition-colors',
                'bg-muted text-muted-foreground border border-border'
              )}
            >
              {statusIndicator}
            </div>
          </TooltipTrigger>
          <TooltipContent side="bottom" className="max-w-xs bg-popover border border-border">
            <div className="space-y-1">
              <div className="flex items-center gap-2">
                <Server className="h-3 w-3" />
                <span className="font-medium">
                  {connecting ? 'Connecting' : 'Disconnected'}
                </span>
              </div>
              {error && (
                <div className="text-destructive text-xs">
                  <strong>Error:</strong> {error}
                </div>
              )}
            </div>
          </TooltipContent>
        </Tooltip>
      </TooltipProvider>
    );
  }

  // When connected, show dropdown for namespace switching
  return (
    <DropdownMenu>
      <TooltipProvider>
        <Tooltip>
          <DropdownMenuTrigger asChild>
            <TooltipTrigger asChild>
              <button 
                className={cn(
                  'flex items-center gap-2 px-3 py-1.5 rounded-md text-xs transition-colors',
                  'bg-success/10 text-success border border-success/20 hover:bg-success/20'
                )}
              >
                {statusIndicator}
              </button>
            </TooltipTrigger>
          </DropdownMenuTrigger>
          <TooltipContent side="bottom" className="max-w-xs bg-popover border border-border">
            <div className="space-y-1">
              <div className="flex items-center gap-2">
                <Server className="h-3 w-3" />
                <span className="font-medium">Connected</span>
              </div>
              <div className="text-muted-foreground text-xs">
                <strong>Namespace:</strong> {namespace}
              </div>
              <div className="text-muted-foreground text-xs break-all">
                <strong>URL:</strong> {baseUrl}
              </div>
              <div className="text-muted-foreground text-xs italic">
                Click to switch namespace
              </div>
            </div>
          </TooltipContent>
        </Tooltip>
      </TooltipProvider>
      <DropdownMenuContent align="center" className="w-48 bg-popover border border-border z-[100]">
        <DropdownMenuLabel className="text-xs text-muted-foreground">
          Switch Namespace
        </DropdownMenuLabel>
        <DropdownMenuSeparator />
        {namespaces.length === 0 ? (
          <DropdownMenuItem disabled className="text-muted-foreground">
            No namespaces found
          </DropdownMenuItem>
        ) : (
          namespaces.map((ns) => (
            <DropdownMenuItem
              key={ns}
              onClick={() => {
                switchNamespace(ns);
                // Navigate away from detail pages to prevent viewing stale resources
                const path = location.pathname;
                if (path.startsWith('/agents/')) navigate('/?tab=agents');
                else if (path.startsWith('/mcpservers/')) navigate('/?tab=mcpservers');
                else if (path.startsWith('/modelapis/')) navigate('/?tab=modelapis');
                else if (path.startsWith('/pods/')) navigate('/?tab=pods');
              }}
              className={cn(
                "font-mono text-sm cursor-pointer",
                ns === namespace && "bg-accent text-accent-foreground"
              )}
            >
              {ns}
            </DropdownMenuItem>
          ))
        )}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}