import React from 'react';
import { Wrench, Users, Loader2, CheckCircle2 } from 'lucide-react';
import { cn } from '@/lib/utils';

export interface ProgressStep {
  type: 'progress';
  step: number;
  max_steps: number;
  action: string; // 'tool_call' | 'delegate'
  target: string;
  completed?: boolean;
}

interface ReasoningStepsProps {
  steps: ProgressStep[];
  isActive: boolean; // Whether the agent is still processing
}

export function ReasoningSteps({ steps, isActive }: ReasoningStepsProps) {
  if (steps.length === 0) return null;

  return (
    <div className="px-4 py-3 bg-muted/20 border-b border-border/50">
      <div className="flex items-center gap-2 mb-2">
        <span className="text-xs font-medium text-muted-foreground uppercase tracking-wider">
          Reasoning
        </span>
        {isActive && (
          <Loader2 className="h-3 w-3 animate-spin text-agent" />
        )}
      </div>
      <div className="space-y-1.5">
        {steps.map((step, idx) => {
          const isLast = idx === steps.length - 1;
          const isCompleted = step.completed || !isLast || !isActive;
          const Icon = step.action === 'tool_call' ? Wrench : Users;
          const actionLabel = step.action === 'tool_call' ? 'Tool' : 'Delegate';

          return (
            <div
              key={`${step.step}-${step.target}`}
              className={cn(
                'flex items-center gap-2 text-xs',
                isCompleted ? 'text-muted-foreground' : 'text-foreground'
              )}
            >
              <div className={cn(
                'h-5 w-5 rounded flex items-center justify-center shrink-0',
                isCompleted ? 'bg-muted' : 'bg-agent/20'
              )}>
                {isCompleted ? (
                  <CheckCircle2 className="h-3 w-3 text-green-500" />
                ) : (
                  <Icon className={cn('h-3 w-3', isActive ? 'text-agent animate-pulse' : 'text-muted-foreground')} />
                )}
              </div>
              <span className="font-mono">
                Step {step.step}/{step.max_steps}
              </span>
              <span className="text-muted-foreground">•</span>
              <span className={cn(
                'font-medium',
                step.action === 'tool_call' ? 'text-blue-400' : 'text-purple-400'
              )}>
                {actionLabel}
              </span>
              <span className="font-mono text-foreground/80 truncate">
                {step.target}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}
