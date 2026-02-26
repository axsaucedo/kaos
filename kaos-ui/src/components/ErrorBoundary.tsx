import React, { Component, ErrorInfo, ReactNode } from 'react';
import { AlertTriangle, Copy, Check, ExternalLink, RefreshCw } from 'lucide-react';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { ScrollArea } from '@/components/ui/scroll-area';

interface Props {
  children: ReactNode;
}

interface State {
  hasError: boolean;
  error: Error | null;
  errorInfo: ErrorInfo | null;
  showDialog: boolean;
  copied: boolean;
}

class ErrorBoundary extends Component<Props, State> {
  constructor(props: Props) {
    super(props);
    this.state = {
      hasError: false,
      error: null,
      errorInfo: null,
      showDialog: false,
      copied: false,
    };
  }

  static getDerivedStateFromError(error: Error): Partial<State> {
    return { hasError: true, error, showDialog: true };
  }

  componentDidCatch(error: Error, errorInfo: ErrorInfo) {
    console.error('ErrorBoundary caught an error:', error, errorInfo);
    this.setState({ errorInfo });
  }

  getErrorReport = (): string => {
    const { error, errorInfo } = this.state;
    const timestamp = new Date().toISOString();
    const userAgent = navigator.userAgent;
    const url = window.location.href;

    return `## Error Report

**Timestamp:** ${timestamp}
**URL:** ${url}
**User Agent:** ${userAgent}

### Error Message
\`\`\`
${error?.message || 'Unknown error'}
\`\`\`

### Stack Trace
\`\`\`
${error?.stack || 'No stack trace available'}
\`\`\`

### Component Stack
\`\`\`
${errorInfo?.componentStack || 'No component stack available'}
\`\`\`

### Console Logs
Check browser console for additional logs.
`;
  };

  copyErrorReport = async () => {
    try {
      await navigator.clipboard.writeText(this.getErrorReport());
      this.setState({ copied: true });
      setTimeout(() => this.setState({ copied: false }), 2000);
    } catch (err) {
      console.error('Failed to copy error report:', err);
    }
  };

  openGitHubIssue = () => {
    const report = this.getErrorReport();
    const title = encodeURIComponent(`[Bug] Application crash: ${this.state.error?.message?.substring(0, 50) || 'Unknown error'}`);
    const body = encodeURIComponent(report);
    const url = `https://github.com/axsaucedo/kaos-ui/issues/new?title=${title}&body=${body}&labels=bug`;
    window.open(url, '_blank');
  };

  handleReload = () => {
    // Clear the error state and navigate to home
    this.setState({ hasError: false, error: null, errorInfo: null, showDialog: false });
    window.location.href = window.location.origin + (import.meta.env.BASE_URL || '/');
  };

  handleContinue = () => {
    // Try to continue without full reload - might not work for all errors
    this.setState({ hasError: false, showDialog: false });
  };

  render() {
    if (this.state.hasError) {
      const { error, errorInfo, showDialog, copied } = this.state;

      return (
        <>
          {/* Fallback UI */}
          <div className="min-h-screen bg-background flex items-center justify-center p-4">
            <div className="text-center max-w-md">
              <div className="h-16 w-16 rounded-full bg-destructive/10 flex items-center justify-center mx-auto mb-4">
                <AlertTriangle className="h-8 w-8 text-destructive" />
              </div>
              <h1 className="text-2xl font-bold mb-2">Something went wrong</h1>
              <p className="text-muted-foreground mb-6">
                The application encountered an unexpected error. We apologize for the inconvenience.
              </p>
              <div className="flex gap-2 justify-center">
                <Button onClick={this.handleReload}>
                  <RefreshCw className="h-4 w-4 mr-2" />
                  Reload App
                </Button>
                <Button variant="outline" onClick={() => this.setState({ showDialog: true })}>
                  View Details
                </Button>
              </div>
            </div>
          </div>

          {/* Error Details Dialog */}
          <Dialog open={showDialog} onOpenChange={(open) => this.setState({ showDialog: open })}>
            <DialogContent className="max-w-2xl max-h-[80vh]">
              <DialogHeader>
                <DialogTitle className="flex items-center gap-2">
                  <AlertTriangle className="h-5 w-5 text-destructive" />
                  Application Error
                </DialogTitle>
                <DialogDescription>
                  An unexpected error occurred. Please report this issue so we can fix it.
                </DialogDescription>
              </DialogHeader>

              <div className="space-y-4">
                {/* Error Message */}
                <div>
                  <h4 className="text-sm font-medium mb-2">Error Message</h4>
                  <div className="bg-destructive/10 border border-destructive/20 rounded-md p-3">
                    <code className="text-sm text-destructive break-all">
                      {error?.message || 'Unknown error'}
                    </code>
                  </div>
                </div>

                {/* Stack Trace */}
                <div>
                  <h4 className="text-sm font-medium mb-2">Stack Trace</h4>
                  <ScrollArea className="h-[200px] rounded-md border bg-muted/50">
                    <pre className="p-3 text-xs font-mono whitespace-pre-wrap break-all">
                      {error?.stack || 'No stack trace available'}
                    </pre>
                  </ScrollArea>
                </div>

                {/* Component Stack (if available) */}
                {errorInfo?.componentStack && (
                  <div>
                    <h4 className="text-sm font-medium mb-2">Component Stack</h4>
                    <ScrollArea className="h-[100px] rounded-md border bg-muted/50">
                      <pre className="p-3 text-xs font-mono whitespace-pre-wrap break-all">
                        {errorInfo.componentStack}
                      </pre>
                    </ScrollArea>
                  </div>
                )}
              </div>

              <DialogFooter className="flex-col sm:flex-row gap-2">
                <Button variant="outline" onClick={this.copyErrorReport} className="gap-2">
                  {copied ? <Check className="h-4 w-4" /> : <Copy className="h-4 w-4" />}
                  {copied ? 'Copied!' : 'Copy Error Report'}
                </Button>
                <Button variant="outline" onClick={this.openGitHubIssue} className="gap-2">
                  <ExternalLink className="h-4 w-4" />
                  Report Issue on GitHub
                </Button>
                <Button onClick={this.handleReload} className="gap-2">
                  <RefreshCw className="h-4 w-4" />
                  Reload Application
                </Button>
              </DialogFooter>
            </DialogContent>
          </Dialog>
        </>
      );
    }

    return this.props.children;
  }
}

export default ErrorBoundary;