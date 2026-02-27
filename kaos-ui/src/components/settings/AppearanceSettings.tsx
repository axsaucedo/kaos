import { useTheme } from 'next-themes';
import { useEffect, useState } from 'react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Label } from '@/components/ui/label';
import { cn } from '@/lib/utils';
import { Sun, Moon, Monitor } from 'lucide-react';

export function AppearanceSettings() {
  const { theme, setTheme, resolvedTheme } = useTheme();
  const [mounted, setMounted] = useState(false);

  // Avoid hydration mismatch
  useEffect(() => {
    setMounted(true);
  }, []);

  const themes = [
    {
      id: 'light',
      label: 'Light',
      icon: Sun,
      description: 'Light background with dark text',
    },
    {
      id: 'dark',
      label: 'Dark',
      icon: Moon,
      description: 'Dark background with light text',
    },
    {
      id: 'system',
      label: 'System',
      icon: Monitor,
      description: 'Follow system preferences',
    },
  ];

  const currentTheme = theme === 'system' ? resolvedTheme : theme;

  return (
    <div className="space-y-6 max-w-2xl">
      <Card>
        <CardHeader>
          <CardTitle>Theme</CardTitle>
          <CardDescription>
            Select your preferred color theme for the dashboard
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid gap-3">
            {themes.map((t) => {
              const Icon = t.icon;
              const isActive = theme === t.id;
              return (
                <button
                  key={t.id}
                  onClick={() => setTheme(t.id)}
                  className={cn(
                    'flex items-center gap-4 p-4 rounded-lg border transition-all duration-200 text-left',
                    isActive
                      ? 'border-primary bg-primary/5'
                      : 'border-border hover:border-primary/50 hover:bg-muted/50'
                  )}
                >
                  <div className={cn(
                    'h-10 w-10 rounded-lg flex items-center justify-center',
                    isActive ? 'bg-primary text-primary-foreground' : 'bg-muted text-muted-foreground'
                  )}>
                    <Icon className="h-5 w-5" />
                  </div>
                  <div className="flex-1">
                    <Label className="text-sm font-medium cursor-pointer">{t.label}</Label>
                    <p className="text-xs text-muted-foreground">{t.description}</p>
                  </div>
                  <div className={cn(
                    'h-4 w-4 rounded-full border-2 transition-colors',
                    isActive ? 'border-primary bg-primary' : 'border-muted-foreground'
                  )} />
                </button>
              );
            })}
          </div>
        </CardContent>
      </Card>

      {/* Theme Preview */}
      <Card>
        <CardHeader>
          <CardTitle>Preview</CardTitle>
          <CardDescription>
            See how the current theme looks
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className="rounded-lg border overflow-hidden">
            <div className="bg-sidebar p-4 border-b border-sidebar-border">
              <div className="flex items-center gap-2">
                <div className="h-6 w-6 rounded bg-primary/20" />
                <span className="text-sm font-medium text-sidebar-foreground">KAOS Dashboard</span>
              </div>
            </div>
            <div className="bg-background p-4">
              <div className="flex gap-4">
                <div className="w-1/3 space-y-2">
                  <div className="h-3 w-full bg-muted rounded" />
                  <div className="h-3 w-3/4 bg-muted rounded" />
                  <div className="h-3 w-1/2 bg-muted rounded" />
                </div>
                <div className="flex-1">
                  <div className="bg-card p-3 rounded-lg border">
                    <div className="flex items-center gap-2 mb-2">
                      <div className="h-2 w-2 rounded-full bg-success" />
                      <span className="text-xs text-foreground">Running</span>
                    </div>
                    <div className="h-2 w-full bg-muted rounded mb-1" />
                    <div className="h-2 w-2/3 bg-muted rounded" />
                  </div>
                </div>
              </div>
            </div>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
