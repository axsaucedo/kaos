import { useState, useEffect, useMemo } from 'react';
import { Search, X, Box, Server, Bot, Boxes } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { Input } from '@/components/ui/input';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { ScrollArea } from '@/components/ui/scroll-area';
import { useKubernetesStore } from '@/stores/kubernetesStore';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';

interface SearchResult {
  type: 'modelapi' | 'mcpserver' | 'agent' | 'pod';
  name: string;
  namespace: string;
  status?: string;
}

export function GlobalSearch() {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState('');
  const navigate = useNavigate();
  const { modelAPIs, mcpServers, agents, pods, setActiveTab } = useKubernetesStore();

  // Handle keyboard shortcut
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
        e.preventDefault();
        setOpen(true);
      }
      if (e.key === 'Escape') {
        setOpen(false);
      }
    };

    document.addEventListener('keydown', handleKeyDown);
    return () => document.removeEventListener('keydown', handleKeyDown);
  }, []);

  const results = useMemo<SearchResult[]>(() => {
    if (!query.trim()) return [];

    const lowerQuery = query.toLowerCase();
    const matches: SearchResult[] = [];

    // Search ModelAPIs
    modelAPIs.forEach((api) => {
      if (
        api.metadata.name.toLowerCase().includes(lowerQuery) ||
        api.metadata.namespace?.toLowerCase().includes(lowerQuery) ||
        api.spec.mode?.toLowerCase().includes(lowerQuery)
      ) {
        matches.push({
          type: 'modelapi',
          name: api.metadata.name,
          namespace: api.metadata.namespace || 'default',
          status: api.status?.phase,
        });
      }
    });

    // Search MCPServers
    mcpServers.forEach((server) => {
      if (
        server.metadata.name.toLowerCase().includes(lowerQuery) ||
        server.metadata.namespace?.toLowerCase().includes(lowerQuery) ||
        server.spec.type?.toLowerCase().includes(lowerQuery)
      ) {
        matches.push({
          type: 'mcpserver',
          name: server.metadata.name,
          namespace: server.metadata.namespace || 'default',
          status: server.status?.phase,
        });
      }
    });

    // Search Agents
    agents.forEach((agent) => {
      if (
        agent.metadata.name.toLowerCase().includes(lowerQuery) ||
        agent.metadata.namespace?.toLowerCase().includes(lowerQuery) ||
        agent.spec.modelAPI?.toLowerCase().includes(lowerQuery)
      ) {
        matches.push({
          type: 'agent',
          name: agent.metadata.name,
          namespace: agent.metadata.namespace || 'default',
          status: agent.status?.phase,
        });
      }
    });

    // Search Pods
    pods.forEach((pod) => {
      if (
        pod.metadata.name.toLowerCase().includes(lowerQuery) ||
        pod.metadata.namespace?.toLowerCase().includes(lowerQuery)
      ) {
        matches.push({
          type: 'pod',
          name: pod.metadata.name,
          namespace: pod.metadata.namespace || 'default',
          status: pod.status?.phase,
        });
      }
    });

    return matches.slice(0, 20); // Limit results
  }, [query, modelAPIs, mcpServers, agents, pods]);

  const handleSelect = (result: SearchResult) => {
    setOpen(false);
    setQuery('');

    switch (result.type) {
      case 'modelapi':
        navigate(`/modelapis/${result.namespace}/${result.name}`);
        break;
      case 'mcpserver':
        navigate(`/mcpservers/${result.namespace}/${result.name}`);
        break;
      case 'agent':
        navigate(`/agents/${result.namespace}/${result.name}`);
        break;
      case 'pod':
        setActiveTab('pods');
        break;
    }
  };

  const getIcon = (type: SearchResult['type']) => {
    switch (type) {
      case 'modelapi': return Box;
      case 'mcpserver': return Server;
      case 'agent': return Bot;
      case 'pod': return Boxes;
    }
  };

  const getTypeLabel = (type: SearchResult['type']) => {
    switch (type) {
      case 'modelapi': return 'ModelAPI';
      case 'mcpserver': return 'MCPServer';
      case 'agent': return 'Agent';
      case 'pod': return 'Pod';
    }
  };

  const getStatusVariant = (status?: string) => {
    switch (status) {
      case 'Running':
      case 'Ready': return 'success';
      case 'Pending':
      case 'Waiting': return 'warning';
      case 'Error':
      case 'Failed': return 'destructive';
      default: return 'secondary';
    }
  };

  return (
    <>
      {/* Search Trigger */}
      <div className="flex-1 max-w-md">
        <div 
          className="relative cursor-pointer"
          onClick={() => setOpen(true)}
        >
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
          <Input
            placeholder="Search resources... (Ctrl+K)"
            className="pl-9 bg-muted/50 border-transparent focus:border-primary h-9 cursor-pointer"
            readOnly
            value=""
          />
        </div>
      </div>

      {/* Search Dialog */}
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="sm:max-w-[550px] p-0">
          <DialogHeader className="p-4 pb-0">
            <DialogTitle className="sr-only">Search Resources</DialogTitle>
            <div className="relative">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
              <Input
                placeholder="Search ModelAPIs, MCPServers, Agents, Pods..."
                className="pl-9 pr-9"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                autoFocus
              />
              {query && (
                <Button
                  variant="ghost"
                  size="icon"
                  className="absolute right-1 top-1/2 -translate-y-1/2 h-7 w-7"
                  onClick={() => setQuery('')}
                >
                  <X className="h-4 w-4" />
                </Button>
              )}
            </div>
          </DialogHeader>

          <div className="border-t">
            {query.trim() === '' ? (
              <div className="p-8 text-center text-muted-foreground">
                <Search className="h-8 w-8 mx-auto mb-2 opacity-50" />
                <p className="text-sm">Start typing to search resources</p>
              </div>
            ) : results.length === 0 ? (
              <div className="p-8 text-center text-muted-foreground">
                <p className="text-sm">No results found for "{query}"</p>
              </div>
            ) : (
              <ScrollArea className="max-h-[400px]">
                <div className="p-2">
                  {results.map((result, index) => {
                    const Icon = getIcon(result.type);
                    return (
                      <button
                        key={`${result.type}-${result.namespace}-${result.name}-${index}`}
                        className="w-full flex items-center gap-3 p-3 rounded-lg hover:bg-muted/50 text-left transition-colors"
                        onClick={() => handleSelect(result)}
                      >
                        <div className="h-8 w-8 rounded-lg bg-muted flex items-center justify-center flex-shrink-0">
                          <Icon className="h-4 w-4 text-muted-foreground" />
                        </div>
                        <div className="flex-1 min-w-0">
                          <div className="flex items-center gap-2">
                            <span className="font-medium text-sm truncate">{result.name}</span>
                            <Badge variant="outline" className="text-[10px] shrink-0">
                              {getTypeLabel(result.type)}
                            </Badge>
                          </div>
                          <p className="text-xs text-muted-foreground font-mono">{result.namespace}</p>
                        </div>
                        {result.status && (
                          <Badge variant={getStatusVariant(result.status) as any} className="shrink-0">
                            {result.status}
                          </Badge>
                        )}
                      </button>
                    );
                  })}
                </div>
              </ScrollArea>
            )}
          </div>
        </DialogContent>
      </Dialog>
    </>
  );
}