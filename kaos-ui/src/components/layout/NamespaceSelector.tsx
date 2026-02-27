import { ChevronDown, Loader2 } from 'lucide-react';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
  DropdownMenuSeparator,
  DropdownMenuLabel,
} from '@/components/ui/dropdown-menu';
import { Button } from '@/components/ui/button';
import { useKubernetesConnection } from '@/contexts/KubernetesConnectionContext';
import { cn } from '@/lib/utils';

export function NamespaceSelector() {
  const { connected, connecting, namespace, namespaces, switchNamespace } = useKubernetesConnection();

  if (!connected) {
    return (
      <div className="flex items-center gap-2 px-3 py-1.5 text-sm text-muted-foreground">
        <span className="text-xs">ns:</span>
        <span className="text-muted-foreground/50">disconnected</span>
      </div>
    );
  }

  if (connecting) {
    return (
      <div className="flex items-center gap-2 px-3 py-1.5 text-sm text-muted-foreground">
        <Loader2 className="h-3 w-3 animate-spin" />
        <span>connecting...</span>
      </div>
    );
  }

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button
          variant="ghost"
          size="sm"
          className="h-8 gap-1 px-2 font-mono text-sm hover:bg-muted"
        >
          <span className="text-muted-foreground">ns:</span>
          <span className="font-medium">{namespace}</span>
          <ChevronDown className="h-3 w-3 text-muted-foreground" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-48 bg-popover border border-border z-[100]">
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
              onClick={() => switchNamespace(ns)}
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
