import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";

import { cn } from "@/lib/utils";

const badgeVariants = cva(
  "inline-flex items-center rounded-full border px-2.5 py-0.5 text-xs font-semibold transition-colors focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-2",
  {
    variants: {
      variant: {
        default: "border-transparent bg-primary text-primary-foreground hover:bg-primary/80",
        secondary: "border-transparent bg-secondary text-secondary-foreground hover:bg-secondary/80",
        destructive: "border-transparent bg-destructive text-destructive-foreground hover:bg-destructive/80",
        outline: "text-foreground",
        // Status variants
        success: "border-transparent bg-success/20 text-success",
        warning: "border-transparent bg-warning/20 text-warning",
        error: "border-transparent bg-destructive/20 text-destructive",
        // Resource type badges
        modelapi: "border-transparent bg-modelapi/20 text-modelapi",
        mcpserver: "border-transparent bg-mcpserver/20 text-mcpserver",
        agent: "border-transparent bg-agent/20 text-agent",
        pod: "border-transparent bg-pod/20 text-pod",
        deployment: "border-transparent bg-deployment/20 text-deployment",
        volume: "border-transparent bg-volume/20 text-volume",
        // Config badges
        toolmode: "border-transparent bg-purple-500/20 text-purple-500",
        // Status badges
        running: "border-transparent bg-success/20 text-success",
        pending: "border-transparent bg-warning/20 text-warning",
        terminated: "border-transparent bg-muted text-muted-foreground",
        unknown: "border-transparent bg-muted text-muted-foreground",
      },
    },
    defaultVariants: {
      variant: "default",
    },
  }
);

export interface BadgeProps extends React.HTMLAttributes<HTMLDivElement>, VariantProps<typeof badgeVariants> {}

function Badge({ className, variant, ...props }: BadgeProps) {
  return <div className={cn(badgeVariants({ variant }), className)} {...props} />;
}

export { Badge, badgeVariants };
