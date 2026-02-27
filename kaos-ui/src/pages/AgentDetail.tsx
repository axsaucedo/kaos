import React, { useEffect, useState, useCallback, useRef } from 'react';
import { useParams, useNavigate, useSearchParams } from 'react-router-dom';
import { ArrowLeft, Bot, Edit, Trash2, RefreshCw, Box, FileCode } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from '@/components/ui/alert-dialog';
import { useToast } from '@/hooks/use-toast';
import { useKubernetesStore } from '@/stores/kubernetesStore';
import { useKubernetesConnection } from '@/contexts/KubernetesConnectionContext';
import { AgentChat } from '@/components/agent/AgentChat';
import { AgentOverview } from '@/components/agent/AgentOverview';
import { AgentMemory } from '@/components/agent/AgentMemory';
import { AgentPods } from '@/components/agent/AgentPods';
import { AgentEditDialog } from '@/components/resources/AgentEditDialog';
import { YamlViewer } from '@/components/shared/YamlViewer';
import type { Agent } from '@/types/kubernetes';
import type { ChatMessage } from '@/hooks/useAgentChat';

// Storage key for persisting chat sessions per agent
const getChatStorageKey = (namespace: string, name: string) => `agent-chat-${namespace}-${name}`;

export default function AgentDetail() {
  const { namespace, name } = useParams<{ namespace: string; name: string }>();
  const [searchParams, setSearchParams] = useSearchParams();
  const navigate = useNavigate();
  const { toast } = useToast();
  const { agents } = useKubernetesStore();
  const { deleteAgent, refreshAll, connected } = useKubernetesConnection();
  
  const [agent, setAgent] = useState<Agent | null>(null);
  const [editDialogOpen, setEditDialogOpen] = useState(false);
  const [isDeleting, setIsDeleting] = useState(false);
  
  // Handler for closing edit dialog - refresh data to get latest state
  const handleEditDialogClose = async () => {
    setEditDialogOpen(false);
    // Refresh all resources to get the updated agent
    await refreshAll();
  };
  
  // Get initial tab from URL params (for returning from logs page)
  const initialTab = searchParams.get('tab') || 'overview';
  const [currentTab, setCurrentTab] = useState(initialTab);
  
  // Chat state lifted here to persist across tab switches
  const [sessionId, setSessionId] = useState<string>('');
  const [chatMessages, setChatMessages] = useState<ChatMessage[]>([]);
  const sessionIdRef = useRef<string>('');
  const isInitialized = useRef(false);
  
  // Load persisted chat on mount
  useEffect(() => {
    if (namespace && name && !isInitialized.current) {
      isInitialized.current = true;
      const storageKey = getChatStorageKey(namespace, name);
      try {
        const stored = localStorage.getItem(storageKey);
        if (stored) {
          const { sessionId: storedSessionId, messages } = JSON.parse(stored);
          if (storedSessionId) setSessionId(storedSessionId);
          if (messages?.length > 0) {
            // Restore messages with Date objects
            setChatMessages(messages.map((m: ChatMessage) => ({
              ...m,
              timestamp: new Date(m.timestamp),
            })));
          }
          sessionIdRef.current = storedSessionId || '';
        }
      } catch (e) {
        console.warn('Failed to restore chat session:', e);
      }
    }
  }, [namespace, name]);
  
  // Persist chat when messages change
  useEffect(() => {
    if (namespace && name && isInitialized.current && (chatMessages.length > 0 || sessionId)) {
      const storageKey = getChatStorageKey(namespace, name);
      try {
        localStorage.setItem(storageKey, JSON.stringify({
          sessionId,
          messages: chatMessages,
        }));
      } catch (e) {
        console.warn('Failed to persist chat session:', e);
      }
    }
  }, [namespace, name, sessionId, chatMessages]);
  
  const handleNewSession = useCallback(() => {
    setSessionId('');
    setChatMessages([]);
    sessionIdRef.current = '';
    // Also clear from storage
    if (namespace && name) {
      const storageKey = getChatStorageKey(namespace, name);
      localStorage.removeItem(storageKey);
    }
  }, [namespace, name]);
  
  const handleSessionChange = useCallback((newSessionId: string) => {
    setSessionId(newSessionId);
    sessionIdRef.current = newSessionId;
  }, []);

  // Find agent from store
  useEffect(() => {
    const found = agents.find(
      (a) => a.metadata.name === name && (a.metadata.namespace || 'default') === namespace
    );
    setAgent(found || null);
  }, [agents, name, namespace]);

  const handleDelete = async () => {
    if (!agent) return;
    
    setIsDeleting(true);
    try {
      await deleteAgent(agent.metadata.name, agent.metadata.namespace);
      toast({
        title: 'Agent deleted',
        description: `${agent.metadata.name} has been deleted.`,
      });
      navigate('/');
    } catch (error) {
      toast({
        variant: 'destructive',
        title: 'Failed to delete agent',
        description: error instanceof Error ? error.message : 'Unknown error',
      });
    } finally {
      setIsDeleting(false);
    }
  };

  if (!connected) {
    return (
      <div className="flex flex-col items-center justify-center h-full p-8">
        <div className="text-center">
          <h2 className="text-xl font-semibold mb-2">Not Connected</h2>
          <p className="text-muted-foreground mb-4">
            Please connect to a Kubernetes cluster first.
          </p>
          <Button onClick={() => navigate('/')}>Go to Dashboard</Button>
        </div>
      </div>
    );
  }

  if (!agent) {
    return (
      <div className="flex flex-col items-center justify-center h-full p-8">
        <div className="text-center">
          <h2 className="text-xl font-semibold mb-2">Agent Not Found</h2>
          <p className="text-muted-foreground mb-4">
            The agent "{name}" in namespace "{namespace}" could not be found.
          </p>
          <div className="flex gap-2 justify-center">
            <Button variant="outline" onClick={() => refreshAll()}>
              <RefreshCw className="h-4 w-4 mr-2" />
              Refresh
            </Button>
            <Button onClick={() => navigate('/')}>Go to Dashboard</Button>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="p-6 space-y-6 animate-fade-in">
      {/* Page Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-4">
          <Button
            variant="ghost"
            size="icon"
            onClick={() => navigate('/')}
            className="shrink-0"
          >
            <ArrowLeft className="h-5 w-5" />
          </Button>
          
          <div className="flex items-center gap-3">
            <div className="h-12 w-12 rounded-xl bg-agent/10 flex items-center justify-center">
              <Bot className="h-6 w-6 text-agent" />
            </div>
            <div>
              <h1 className="text-2xl font-bold text-foreground">{agent.metadata.name}</h1>
              <div className="flex items-center gap-2 text-sm text-muted-foreground">
                <span className="font-mono">{agent.metadata.namespace || 'default'}</span>
                <Badge
                  variant={agent.status?.phase === 'Running' ? 'success' : 'secondary'}
                  className="text-xs"
                >
                  {agent.status?.phase || 'Unknown'}
                </Badge>
              </div>
            </div>
          </div>
        </div>

        <div className="flex items-center gap-2">
          <Button
            variant="outline"
            size="sm"
            onClick={() => setEditDialogOpen(true)}
          >
            <Edit className="h-4 w-4 mr-2" />
            Edit
          </Button>
          
          <AlertDialog>
            <AlertDialogTrigger asChild>
              <Button variant="destructive" size="sm" disabled={isDeleting}>
                <Trash2 className="h-4 w-4 mr-2" />
                Delete
              </Button>
            </AlertDialogTrigger>
            <AlertDialogContent>
              <AlertDialogHeader>
                <AlertDialogTitle>Delete Agent?</AlertDialogTitle>
                <AlertDialogDescription>
                  This will permanently delete the agent "{agent.metadata.name}".
                  This action cannot be undone.
                </AlertDialogDescription>
              </AlertDialogHeader>
              <AlertDialogFooter>
                <AlertDialogCancel>Cancel</AlertDialogCancel>
                <AlertDialogAction
                  onClick={handleDelete}
                  className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
                >
                  Delete
                </AlertDialogAction>
              </AlertDialogFooter>
            </AlertDialogContent>
          </AlertDialog>
        </div>
      </div>

      {/* Tabs Content */}
      <Tabs value={currentTab} onValueChange={setCurrentTab} className="space-y-6">
        <TabsList className="grid w-full max-w-2xl grid-cols-5">
          <TabsTrigger value="overview">Overview</TabsTrigger>
          <TabsTrigger value="chat">Chat</TabsTrigger>
          <TabsTrigger value="memory">Memory</TabsTrigger>
          <TabsTrigger value="pods" className="flex items-center gap-1">
            <Box className="h-3 w-3" />
            Pods
          </TabsTrigger>
          <TabsTrigger value="yaml" className="flex items-center gap-1">
            <FileCode className="h-3 w-3" />
            YAML
          </TabsTrigger>
        </TabsList>

        <TabsContent value="overview" className="space-y-6">
          <AgentOverview agent={agent} />
        </TabsContent>

        {/* Chat is always mounted but hidden when not active to preserve streaming state */}
        <div className={currentTab === 'chat' ? 'h-[calc(100vh-320px)]' : 'hidden'}>
          <AgentChat 
            agent={agent}
            sessionId={sessionId}
            messages={chatMessages}
            onSessionChange={handleSessionChange}
            onMessagesChange={setChatMessages}
            onNewSession={handleNewSession}
          />
        </div>

        <TabsContent value="memory" className="space-y-6">
          <AgentMemory agent={agent} />
        </TabsContent>

        <TabsContent value="pods" className="space-y-6">
          <AgentPods agent={agent} />
        </TabsContent>

        <TabsContent value="yaml" className="space-y-6">
          <YamlViewer resource={agent} title="Agent YAML" maxHeight="calc(100vh - 380px)" />
        </TabsContent>
      </Tabs>

      {/* Edit Dialog */}
      <AgentEditDialog
        agent={agent}
        open={editDialogOpen}
        onClose={handleEditDialogClose}
      />
    </div>
  );
}
