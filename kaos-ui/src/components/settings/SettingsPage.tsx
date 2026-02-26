import { useState } from 'react';
import { Settings, Wifi, Palette } from 'lucide-react';
import { cn } from '@/lib/utils';
import { ConnectionSettings } from './ConnectionSettings';
import { AppearanceSettings } from './AppearanceSettings';

type SettingsSection = 'connectivity' | 'appearance';

interface SettingsNavItem {
  id: SettingsSection;
  label: string;
  icon: React.ElementType;
  description: string;
}

const settingsNavItems: SettingsNavItem[] = [
  { 
    id: 'connectivity', 
    label: 'Connectivity', 
    icon: Wifi,
    description: 'Kubernetes cluster connection settings'
  },
  { 
    id: 'appearance', 
    label: 'Appearance', 
    icon: Palette,
    description: 'Theme and visual preferences'
  },
];

export function SettingsPage() {
  const [activeSection, setActiveSection] = useState<SettingsSection>('connectivity');

  const renderContent = () => {
    switch (activeSection) {
      case 'connectivity':
        return <ConnectionSettings />;
      case 'appearance':
        return <AppearanceSettings />;
      default:
        return <ConnectionSettings />;
    }
  };

  return (
    <div className="p-6">
      <div className="flex items-center gap-4 mb-6">
        <div className="h-12 w-12 rounded-xl bg-muted flex items-center justify-center">
          <Settings className="h-6 w-6 text-muted-foreground" />
        </div>
        <div>
          <h1 className="text-2xl font-bold text-foreground">Settings</h1>
          <p className="text-muted-foreground">Configure your operator dashboard</p>
        </div>
      </div>

      <div className="flex gap-6">
        {/* Settings Navigation */}
        <nav className="w-56 shrink-0 space-y-1">
          {settingsNavItems.map((item) => {
            const Icon = item.icon;
            const isActive = activeSection === item.id;
            return (
              <button
                key={item.id}
                onClick={() => setActiveSection(item.id)}
                className={cn(
                  'flex items-center gap-3 w-full px-3 py-2.5 rounded-lg transition-all duration-200 text-left',
                  isActive
                    ? 'bg-primary/10 text-primary border border-primary/20'
                    : 'text-muted-foreground hover:text-foreground hover:bg-muted/50'
                )}
              >
                <Icon className={cn('h-5 w-5 flex-shrink-0', isActive && 'text-primary')} />
                <div>
                  <span className="text-sm font-medium block">{item.label}</span>
                  <span className="text-xs text-muted-foreground">{item.description}</span>
                </div>
              </button>
            );
          })}
        </nav>

        {/* Settings Content */}
        <div className="flex-1 min-w-0">
          {renderContent()}
        </div>
      </div>
    </div>
  );
}
