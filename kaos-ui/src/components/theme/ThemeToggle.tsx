import { Moon, Sun } from "lucide-react";
import { useTheme } from "next-themes";
import { useEffect, useState } from "react";
import { cn } from "@/lib/utils";

export function ThemeToggle({ className }: { className?: string }) {
  const { theme, setTheme, resolvedTheme } = useTheme();
  const [mounted, setMounted] = useState(false);

  // Avoid hydration mismatch
  useEffect(() => {
    setMounted(true);
  }, []);

  if (!mounted) {
    return (
      <div className={cn("flex items-center gap-1 p-1 rounded-full bg-muted border border-border", className)}>
        <div className="h-7 w-7 rounded-full" />
        <div className="h-7 w-7 rounded-full" />
      </div>
    );
  }

  const currentTheme = theme === 'system' ? resolvedTheme : theme;
  const isDark = currentTheme === 'dark';

  const toggleTheme = () => {
    setTheme(isDark ? 'light' : 'dark');
  };

  return (
    <button
      onClick={toggleTheme}
      className={cn(
        "flex items-center gap-1 p-1 rounded-full bg-muted border border-border cursor-pointer hover:bg-muted/80 transition-colors",
        className
      )}
      title={`Switch to ${isDark ? 'light' : 'dark'} mode`}
    >
      <div
        className={cn(
          "h-7 w-7 rounded-full flex items-center justify-center transition-colors",
          !isDark && "bg-background shadow-sm"
        )}
      >
        <Sun className="h-4 w-4" />
      </div>
      <div
        className={cn(
          "h-7 w-7 rounded-full flex items-center justify-center transition-colors",
          isDark && "bg-background shadow-sm"
        )}
      >
        <Moon className="h-4 w-4" />
      </div>
    </button>
  );
}
