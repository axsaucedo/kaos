import { describe, it, expect } from 'vitest';
import { getStatusVariant, getPodStatusInfo } from '@/lib/status-utils';

describe('getStatusVariant', () => {
  it('returns "success" for Running', () => {
    expect(getStatusVariant('Running')).toBe('success');
  });

  it('returns "success" for Ready', () => {
    expect(getStatusVariant('Ready')).toBe('success');
  });

  it('returns "warning" for Pending', () => {
    expect(getStatusVariant('Pending')).toBe('warning');
  });

  it('returns "warning" for Waiting', () => {
    expect(getStatusVariant('Waiting')).toBe('warning');
  });

  it('returns "destructive" for Error', () => {
    expect(getStatusVariant('Error')).toBe('destructive');
  });

  it('returns "destructive" for Failed', () => {
    expect(getStatusVariant('Failed')).toBe('destructive');
  });

  it('returns "secondary" for unknown status', () => {
    expect(getStatusVariant('SomethingElse')).toBe('secondary');
  });

  it('returns "secondary" for undefined', () => {
    expect(getStatusVariant(undefined)).toBe('secondary');
  });
});

describe('getPodStatusInfo', () => {
  it('detects terminating pods via deletionTimestamp', () => {
    const pod = {
      metadata: { deletionTimestamp: '2024-01-01T00:00:00Z' },
      status: { phase: 'Running', containerStatuses: [{ ready: true }] },
    };
    const result = getPodStatusInfo(pod);
    expect(result).toEqual({ status: 'Terminating', isRolling: true, isTerminating: true });
  });

  it('detects running pods with not-ready containers as rolling update', () => {
    const pod = {
      metadata: {},
      status: {
        phase: 'Running',
        containerStatuses: [{ ready: true }, { ready: false }],
      },
    };
    const result = getPodStatusInfo(pod);
    expect(result).toEqual({ status: 'ContainerNotReady', isRolling: true, isTerminating: false });
  });

  it('detects pending pods with waiting container reason', () => {
    const pod = {
      metadata: {},
      status: {
        phase: 'Pending',
        containerStatuses: [
          { ready: false, state: { waiting: { reason: 'ImagePullBackOff' } } },
        ],
      },
    };
    const result = getPodStatusInfo(pod);
    expect(result).toEqual({ status: 'ImagePullBackOff', isRolling: true, isTerminating: false });
  });

  it('returns "Pending" for pending pods without specific waiting reason', () => {
    const pod = {
      metadata: {},
      status: { phase: 'Pending', containerStatuses: [] },
    };
    const result = getPodStatusInfo(pod);
    expect(result).toEqual({ status: 'Pending', isRolling: true, isTerminating: false });
  });

  it('returns normal status for healthy running pods', () => {
    const pod = {
      metadata: {},
      status: {
        phase: 'Running',
        containerStatuses: [{ ready: true }],
      },
    };
    const result = getPodStatusInfo(pod);
    expect(result).toEqual({ status: 'Running', isRolling: false, isTerminating: false });
  });

  it('handles missing status gracefully', () => {
    const pod = { metadata: {} };
    const result = getPodStatusInfo(pod);
    expect(result).toEqual({ status: 'Unknown', isRolling: false, isTerminating: false });
  });
});
