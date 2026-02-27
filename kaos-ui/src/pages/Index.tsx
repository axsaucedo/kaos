import { OverviewDashboard } from '@/components/dashboard/OverviewDashboard';
import { VisualMap } from '@/components/dashboard/VisualMap';
import { ModelAPIList } from '@/components/resources/ModelAPIList';
import { MCPServerList } from '@/components/resources/MCPServerList';
import { AgentList } from '@/components/resources/AgentList';
import { AgentDetailDrawer } from '@/components/resources/AgentDetailDrawer';
import { AgentEditDialog } from '@/components/resources/AgentEditDialog';
import { ModelAPIDetailDrawer } from '@/components/resources/ModelAPIDetailDrawer';
import { ModelAPIEditDialog } from '@/components/resources/ModelAPIEditDialog';
import { MCPServerDetailDrawer } from '@/components/resources/MCPServerDetailDrawer';
import { MCPServerEditDialog } from '@/components/resources/MCPServerEditDialog';
import { PodsList } from '@/components/kubernetes/PodsList';
import { SecretsList } from '@/components/kubernetes/SecretsList';
import { SettingsPage } from '@/components/settings/SettingsPage';
import KAOSSystemPage from '@/pages/KAOSSystemPage';
import KAOSMonitoringPage from '@/pages/KAOSMonitoringPage';
import { useKubernetesStore } from '@/stores/kubernetesStore';
import type { Agent, ModelAPI, MCPServer } from '@/types/kubernetes';

function IndexContent() {
  const { activeTab, selectedResource, selectedResourceMode, setSelectedResource, setSelectedResourceMode } = useKubernetesStore();

  const handleCloseResource = () => {
    setSelectedResource(null);
    setSelectedResourceMode(null);
  };

  const handleSwitchToEdit = () => {
    setSelectedResourceMode('edit');
  };

  const renderContent = () => {
    switch (activeTab) {
      case 'overview': return <OverviewDashboard />;
      // visual-map is rendered separately to preserve pan/zoom state
      case 'visual-map': return null;
      case 'model-apis': return <ModelAPIList />;
      case 'mcp-servers': return <MCPServerList />;
      case 'agents': return <AgentList />;
      case 'pods': return <PodsList />;
      case 'secrets': return <SecretsList />;
      case 'kaos-system': return <KAOSSystemPage />;
      // kaos-monitoring is rendered separately to preserve iframe state
      case 'kaos-monitoring': return null;
      case 'settings': return <SettingsPage />;
      default: return <OverviewDashboard />;
    }
  };

  const isAgentSelected = selectedResource?.kind === 'Agent';
  const isModelAPISelected = selectedResource?.kind === 'ModelAPI';
  const isMCPServerSelected = selectedResource?.kind === 'MCPServer';

  return (
    <>
      <div key={activeTab} className="animate-tab-switch">
        {renderContent()}
      </div>
      
      {/* Visual Map always mounted to preserve pan/zoom state */}
      <div className={activeTab === 'visual-map' ? 'h-full w-full' : 'hidden'}>
        <VisualMap />
      </div>

      {/* KAOS Monitoring is always mounted but hidden when not active to preserve iframe state */}
      <div className={activeTab === 'kaos-monitoring' ? 'h-full w-full' : 'hidden'}>
        <KAOSMonitoringPage />
      </div>

      {/* ModelAPI Detail Drawer */}
      {isModelAPISelected && selectedResourceMode === 'view' && (
        <ModelAPIDetailDrawer
          modelAPI={selectedResource as ModelAPI}
          open={true}
          onClose={handleCloseResource}
          onEdit={handleSwitchToEdit}
        />
      )}

      {/* ModelAPI Edit Dialog */}
      {isModelAPISelected && selectedResourceMode === 'edit' && (
        <ModelAPIEditDialog
          modelAPI={selectedResource as ModelAPI}
          open={true}
          onClose={handleCloseResource}
        />
      )}

      {/* MCPServer Detail Drawer */}
      {isMCPServerSelected && selectedResourceMode === 'view' && (
        <MCPServerDetailDrawer
          mcpServer={selectedResource as MCPServer}
          open={true}
          onClose={handleCloseResource}
          onEdit={handleSwitchToEdit}
        />
      )}

      {/* MCPServer Edit Dialog */}
      {isMCPServerSelected && selectedResourceMode === 'edit' && (
        <MCPServerEditDialog
          mcpServer={selectedResource as MCPServer}
          open={true}
          onClose={handleCloseResource}
        />
      )}

      {/* Agent Detail Drawer */}
      {isAgentSelected && selectedResourceMode === 'view' && (
        <AgentDetailDrawer
          agent={selectedResource as Agent}
          open={true}
          onClose={handleCloseResource}
          onEdit={handleSwitchToEdit}
        />
      )}

      {/* Agent Edit Dialog */}
      {isAgentSelected && selectedResourceMode === 'edit' && (
        <AgentEditDialog
          agent={selectedResource as Agent}
          open={true}
          onClose={handleCloseResource}
        />
      )}
    </>
  );
}

const Index = () => {
  return <IndexContent />;
};

export default Index;
