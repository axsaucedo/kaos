import { useState, useEffect, useCallback } from 'react';
import type { Pod, Deployment, ConfigMap } from '@/types/kubernetes';

export function useKAOSResources(connected: boolean, baseUrl: string, kaosNamespace: string) {
  const [operatorPods, setOperatorPods] = useState<Pod[]>([]);
  const [operatorDeployments, setOperatorDeployments] = useState<Deployment[]>([]);
  const [operatorConfig, setOperatorConfig] = useState<ConfigMap | null>(null);
  const [mcpRuntimes, setMcpRuntimes] = useState<ConfigMap | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selectedPod, setSelectedPod] = useState<Pod | null>(null);

  const fetchKAOSResources = useCallback(async () => {
    if (!connected || !baseUrl) return;
    
    setLoading(true);
    setError(null);
    
    try {
      const podsResponse = await fetch(`${baseUrl}/api/v1/namespaces/${kaosNamespace}/pods`, {
        headers: {
          'bypass-tunnel-reminder': '1',
          'X-Requested-With': 'XMLHttpRequest',
        },
      });
      
      if (!podsResponse.ok) {
        if (podsResponse.status === 404) {
          setError(`Namespace "${kaosNamespace}" not found`);
          setOperatorPods([]);
          return;
        }
        throw new Error(`Failed to fetch pods: ${podsResponse.statusText}`);
      }
      
      const podsData = await podsResponse.json();
      const kaosPods = (podsData.items || []).filter((pod: Pod) => 
        pod.metadata.name.includes('kaos') || 
        pod.metadata.labels?.['app.kubernetes.io/name']?.includes('kaos') ||
        pod.metadata.labels?.['app']?.includes('kaos')
      );
      setOperatorPods(kaosPods);
      
      if (kaosPods.length > 0 && !selectedPod) {
        setSelectedPod(kaosPods[0]);
      }
      
      const deploymentsResponse = await fetch(`${baseUrl}/apis/apps/v1/namespaces/${kaosNamespace}/deployments`, {
        headers: {
          'bypass-tunnel-reminder': '1',
          'X-Requested-With': 'XMLHttpRequest',
        },
      });
      
      if (deploymentsResponse.ok) {
        const deploymentsData = await deploymentsResponse.json();
        const kaosDeployments = (deploymentsData.items || []).filter((d: Deployment) =>
          d.metadata.name.includes('kaos')
        );
        setOperatorDeployments(kaosDeployments);
      }
      
      try {
        const configResponse = await fetch(`${baseUrl}/api/v1/namespaces/${kaosNamespace}/configmaps/kaos-operator-config`, {
          headers: {
            'bypass-tunnel-reminder': '1',
            'X-Requested-With': 'XMLHttpRequest',
          },
        });
        if (configResponse.ok) {
          setOperatorConfig(await configResponse.json());
        } else {
          setOperatorConfig(null);
        }
      } catch {
        setOperatorConfig(null);
      }
      
      try {
        const runtimesResponse = await fetch(`${baseUrl}/api/v1/namespaces/${kaosNamespace}/configmaps/kaos-mcp-runtimes`, {
          headers: {
            'bypass-tunnel-reminder': '1',
            'X-Requested-With': 'XMLHttpRequest',
          },
        });
        if (runtimesResponse.ok) {
          setMcpRuntimes(await runtimesResponse.json());
        } else {
          setMcpRuntimes(null);
        }
      } catch {
        setMcpRuntimes(null);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to fetch KAOS resources');
    } finally {
      setLoading(false);
    }
  }, [connected, baseUrl, kaosNamespace, selectedPod]);

  useEffect(() => {
    fetchKAOSResources();
  }, [fetchKAOSResources]);

  return {
    operatorPods,
    operatorDeployments,
    operatorConfig,
    mcpRuntimes,
    loading,
    error,
    selectedPod,
    setSelectedPod,
    fetchKAOSResources,
  };
}
