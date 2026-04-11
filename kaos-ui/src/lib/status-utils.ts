/**
 * Shared status utility functions extracted from overview/pods components.
 */

import type { Agent } from '@/types/kubernetes';

/**
 * Check whether an agent is configured for autonomous execution.
 */
export function isAutonomousAgent(agent: Agent): boolean {
  return !!agent.spec.config?.autonomous?.goal;
}

/**
 * Maps a resource phase/status string to a badge variant.
 * Used by AgentOverview, ModelAPIOverview, MCPServerOverview, etc.
 */
export function getStatusVariant(phase?: string): string {
  switch (phase) {
    case 'Running':
    case 'Ready':
      return 'success';
    case 'Pending':
    case 'Waiting':
      return 'warning';
    case 'Error':
    case 'Failed':
      return 'destructive';
    default:
      return 'secondary';
  }
}

interface PodStatusInfo {
  status: string;
  isRolling: boolean;
  isTerminating: boolean;
}

interface PodLike {
  metadata: { deletionTimestamp?: string };
  status?: {
    phase?: string;
    containerStatuses?: Array<{
      ready: boolean;
      state?: { waiting?: { reason?: string } };
    }>;
  };
}

/**
 * Determines the display status, rolling-update flag, and terminating flag for a pod.
 * Extracted from AgentPods / MCPServerPods / ModelAPIPods.
 */
export function getPodStatusInfo(pod: PodLike): PodStatusInfo {
  const phase = pod.status?.phase || 'Unknown';
  const deletionTimestamp = pod.metadata.deletionTimestamp;
  const containerStatuses = pod.status?.containerStatuses || [];

  if (deletionTimestamp) {
    return { status: 'Terminating', isRolling: true, isTerminating: true };
  }

  const notReady = containerStatuses.some((c) => !c.ready);
  if (phase === 'Running' && notReady) {
    return { status: 'ContainerNotReady', isRolling: true, isTerminating: false };
  }

  if (phase === 'Pending') {
    const containerWaiting = containerStatuses.find((c) => c.state?.waiting);
    const reason = containerWaiting?.state?.waiting?.reason || 'Pending';
    return { status: reason, isRolling: true, isTerminating: false };
  }

  return { status: phase, isRolling: false, isTerminating: false };
}
