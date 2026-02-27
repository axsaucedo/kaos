import React, { useState, useEffect } from 'react';
import { ChevronUp, Tag } from 'lucide-react';
import { cn } from '@/lib/utils';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';

interface VersionSwitcherProps {
  collapsed?: boolean;
}

interface VersionInfo {
  versions: string[];
  latest: string;
}

/**
 * Get the current version from the URL path
 * e.g., /kaos-ui/v1.0.0/ -> "v1.0.0", /kaos-ui/dev/ -> "dev"
 */
function getCurrentVersion(): string {
  const path = window.location.pathname;
  // Match patterns like /kaos-ui/v1.0.0/ or /kaos-ui/dev/
  const match = path.match(/\/kaos-ui\/(v[0-9.]+|dev|latest)\//);
  if (match) {
    return match[1];
  }
  // Default to dev for local development
  return 'dev';
}

/**
 * Navigate to a different version of the docs
 */
function navigateToVersion(version: string) {
  const basePath = version === 'latest' ? '/kaos-ui/latest/' : 
                   version === 'dev' ? '/kaos-ui/dev/' : 
                   `/kaos-ui/${version}/`;
  
  // In production, navigate to the versioned URL
  if (window.location.hostname !== 'localhost') {
    window.location.href = `${window.location.origin}${basePath}`;
  } else {
    // In development, show a message since all versions aren't available locally
    console.log(`Would navigate to ${basePath} in production`);
  }
}

export function VersionSwitcher({ collapsed = false }: VersionSwitcherProps) {
  const [versions, setVersions] = useState<string[]>([]);
  const [latestVersion, setLatestVersion] = useState<string>('');
  const [loading, setLoading] = useState(true);
  const currentVersion = getCurrentVersion();

  useEffect(() => {
    const fetchVersions = async () => {
      try {
        // In production, fetch from the gh-pages root
        const baseUrl = window.location.hostname === 'localhost' 
          ? '' // Skip in local dev
          : '/kaos-ui';
        
        if (baseUrl) {
          const response = await fetch(`${baseUrl}/versions.json`);
          if (response.ok) {
            const data: VersionInfo = await response.json();
            setVersions(data.versions);
            setLatestVersion(data.latest);
          } else {
            // versions.json doesn't exist yet, use defaults
            console.debug('versions.json not found, using defaults');
            setVersions([]);
            setLatestVersion('');
          }
        } else {
          // Local development - no versions.json available
          setVersions([]);
          setLatestVersion('');
        }
      } catch (error) {
        console.debug('Failed to fetch versions:', error);
        setVersions([]);
        setLatestVersion('');
      } finally {
        setLoading(false);
      }
    };

    fetchVersions();
  }, []);

  // Don't show if no versions available and in dev mode
  const hasVersions = versions.length > 0 || !loading;
  
  const displayVersion = currentVersion === 'latest' && latestVersion 
    ? `latest (${latestVersion})` 
    : currentVersion;

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <button
          className={cn(
            'flex items-center gap-2 text-xs transition-colors w-full',
            'text-muted-foreground hover:text-foreground',
            'focus:outline-none',
            collapsed && 'justify-center'
          )}
          title={`Current version: ${displayVersion}`}
        >
          <Tag className="h-3.5 w-3.5 flex-shrink-0" />
          {!collapsed && (
            <>
              <span className="flex-1 text-left">
                Current version: <span className="font-mono">{displayVersion}</span>
              </span>
              <ChevronUp className="h-3 w-3 opacity-50" />
            </>
          )}
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent 
        align="start" 
        side="top" 
        className="w-48"
        sideOffset={8}
      >
        {/* Dev version */}
        <DropdownMenuItem 
          onClick={() => navigateToVersion('dev')}
          className={cn(
            'font-mono text-xs cursor-pointer',
            currentVersion === 'dev' && 'bg-primary/10 text-primary'
          )}
        >
          <span className="flex items-center gap-2">
            <span className="h-1.5 w-1.5 rounded-full bg-yellow-500" />
            dev
          </span>
          {currentVersion === 'dev' && (
            <span className="ml-auto text-[10px] text-muted-foreground">(current)</span>
          )}
        </DropdownMenuItem>

        {/* Latest version */}
        {latestVersion && (
          <DropdownMenuItem 
            onClick={() => navigateToVersion('latest')}
            className={cn(
              'font-mono text-xs cursor-pointer',
              currentVersion === 'latest' && 'bg-primary/10 text-primary'
            )}
          >
            <span className="flex items-center gap-2">
              <span className="h-1.5 w-1.5 rounded-full bg-green-500" />
              latest ({latestVersion})
            </span>
            {currentVersion === 'latest' && (
              <span className="ml-auto text-[10px] text-muted-foreground">(current)</span>
            )}
          </DropdownMenuItem>
        )}

        {versions.length > 0 && <DropdownMenuSeparator />}

        {/* All versioned releases */}
        {versions.map((version) => (
          <DropdownMenuItem 
            key={version}
            onClick={() => navigateToVersion(`v${version}`)}
            className={cn(
              'font-mono text-xs cursor-pointer',
              currentVersion === `v${version}` && 'bg-primary/10 text-primary'
            )}
          >
            <span className="flex items-center gap-2">
              <span className="h-1.5 w-1.5 rounded-full bg-blue-500" />
              v{version}
            </span>
            {currentVersion === `v${version}` && (
              <span className="ml-auto text-[10px] text-muted-foreground">(current)</span>
            )}
          </DropdownMenuItem>
        ))}

        {!loading && versions.length === 0 && !latestVersion && (
          <DropdownMenuItem disabled className="text-xs text-muted-foreground">
            No releases yet
          </DropdownMenuItem>
        )}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
