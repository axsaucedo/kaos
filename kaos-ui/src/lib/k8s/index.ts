/**
 * Composed KubernetesClient — re-exports the fully-assembled class
 * and singleton for backward compatibility.
 */

export { KubernetesClientWithProxy as KubernetesClient } from './proxy';
export type { K8sClientConfig, K8sListResponse, K8sStatus } from './client';

// Re-export submodule classes for consumers that need finer granularity
export { KubernetesClientBase } from './client';
export { KubernetesClientWithResources } from './resources';
export { KubernetesClientWithCore } from './core';
export { KubernetesClientWithProxy } from './proxy';

import { KubernetesClientWithProxy } from './proxy';

// Singleton instance
export const k8sClient = new KubernetesClientWithProxy();
