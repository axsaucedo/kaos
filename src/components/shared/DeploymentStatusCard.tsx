import { Activity, CheckCircle, AlertCircle, Clock, RefreshCw } from 'lucide-react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Progress } from '@/components/ui/progress';
import type { DeploymentStatusInfo } from '@/types/kubernetes';

interface DeploymentStatusCardProps {
  deployment?: DeploymentStatusInfo;
  className?: string;
}

export function DeploymentStatusCard({ deployment, className }: DeploymentStatusCardProps) {
  if (!deployment) {
    return null;
  }

  const { replicas = 0, readyReplicas = 0, availableReplicas = 0, updatedReplicas = 0, conditions = [] } = deployment;
  
  // Calculate progress for rolling update
  const updateProgress = replicas > 0 ? Math.round((updatedReplicas / replicas) * 100) : 0;
  const readyProgress = replicas > 0 ? Math.round((readyReplicas / replicas) * 100) : 0;
  
  // Determine if there's a rolling update in progress
  const isRollingUpdate = updatedReplicas < replicas && replicas > 0;
  
  // Get condition status
  const getConditionBadge = (status: string, type: string) => {
    if (status === 'True') {
      return <Badge variant="success" className="text-xs">{type}</Badge>;
    } else if (status === 'False') {
      return <Badge variant="destructive" className="text-xs">{type}</Badge>;
    }
    return <Badge variant="secondary" className="text-xs">{type}</Badge>;
  };

  return (
    <Card className={className}>
      <CardHeader className="pb-3">
        <CardTitle className="text-base flex items-center gap-2">
          <Activity className="h-4 w-4 text-primary" />
          Deployment Status
          {isRollingUpdate && (
            <Badge variant="warning" className="ml-2 text-xs">
              <RefreshCw className="h-3 w-3 mr-1 animate-spin" />
              Rolling Update
            </Badge>
          )}
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        {/* Replica counts */}
        <div className="grid grid-cols-4 gap-4 text-center">
          <div className="space-y-1">
            <div className="text-2xl font-bold">{replicas}</div>
            <div className="text-xs text-muted-foreground">Total</div>
          </div>
          <div className="space-y-1">
            <div className="text-2xl font-bold text-success">{readyReplicas}</div>
            <div className="text-xs text-muted-foreground">Ready</div>
          </div>
          <div className="space-y-1">
            <div className="text-2xl font-bold text-primary">{availableReplicas}</div>
            <div className="text-xs text-muted-foreground">Available</div>
          </div>
          <div className="space-y-1">
            <div className="text-2xl font-bold text-info">{updatedReplicas}</div>
            <div className="text-xs text-muted-foreground">Updated</div>
          </div>
        </div>

        {/* Progress bars */}
        {replicas > 0 && (
          <div className="space-y-3">
            <div className="space-y-1">
              <div className="flex justify-between text-xs text-muted-foreground">
                <span>Ready Replicas</span>
                <span>{readyReplicas}/{replicas}</span>
              </div>
              <Progress value={readyProgress} className="h-2" />
            </div>
            
            {isRollingUpdate && (
              <div className="space-y-1">
                <div className="flex justify-between text-xs text-muted-foreground">
                  <span>Update Progress</span>
                  <span>{updatedReplicas}/{replicas}</span>
                </div>
                <Progress value={updateProgress} className="h-2" />
              </div>
            )}
          </div>
        )}

        {/* Conditions */}
        {conditions && conditions.length > 0 && (
          <div className="space-y-2">
            <div className="text-sm text-muted-foreground">Conditions</div>
            <div className="space-y-2">
              {conditions.map((condition, idx) => (
                <div key={idx} className="flex items-start gap-2 p-2 bg-muted/50 rounded-md">
                  {condition.status === 'True' ? (
                    <CheckCircle className="h-4 w-4 text-success mt-0.5 shrink-0" />
                  ) : condition.status === 'False' ? (
                    <AlertCircle className="h-4 w-4 text-destructive mt-0.5 shrink-0" />
                  ) : (
                    <Clock className="h-4 w-4 text-muted-foreground mt-0.5 shrink-0" />
                  )}
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 flex-wrap">
                      {getConditionBadge(condition.status, condition.type)}
                      {condition.reason && (
                        <span className="text-xs font-mono text-muted-foreground">
                          {condition.reason}
                        </span>
                      )}
                    </div>
                    {condition.message && (
                      <p className="text-xs text-muted-foreground mt-1 break-words">
                        {condition.message}
                      </p>
                    )}
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
