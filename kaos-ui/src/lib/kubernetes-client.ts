/**
 * Real Kubernetes API Client
 *
 * Re-exports from modular k8s/ directory for backward compatibility.
 * All implementations live in src/lib/k8s/.
 */

export { KubernetesClient, k8sClient } from './k8s';
export type { K8sClientConfig } from './k8s';
