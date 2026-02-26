import React, { useState, useMemo } from 'react';
import { Copy, Check, FileCode } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { ScrollArea } from '@/components/ui/scroll-area';

interface YamlViewerProps {
  resource: unknown;
  title?: string;
  maxHeight?: string;
}

// Fields to exclude from YAML output (internal K8s managed fields)
const EXCLUDED_FIELDS = ['managedFields', 'selfLink', 'generation'];

// Clean the resource by removing excluded fields
function cleanResource(obj: unknown): unknown {
  if (obj === null || obj === undefined) {
    return obj;
  }
  
  if (Array.isArray(obj)) {
    return obj.map(cleanResource);
  }
  
  if (typeof obj === 'object') {
    const cleaned: Record<string, unknown> = {};
    for (const [key, value] of Object.entries(obj as Record<string, unknown>)) {
      if (!EXCLUDED_FIELDS.includes(key)) {
        cleaned[key] = cleanResource(value);
      }
    }
    return cleaned;
  }
  
  return obj;
}

// Convert resource to YAML format
function toYaml(obj: unknown, indent = 0): string {
  const spaces = '  '.repeat(indent);
  
  if (obj === null || obj === undefined) {
    return 'null';
  }
  
  if (typeof obj === 'string') {
    // Multi-line strings
    if (obj.includes('\n')) {
      const lines = obj.split('\n');
      const indentedLines = lines.map(line => '  '.repeat(indent + 1) + line);
      return '|\n' + indentedLines.join('\n');
    }
    // Strings that need quoting
    if (obj.includes(':') || obj.includes('#') || obj.startsWith(' ') || obj.endsWith(' ') || obj === '' || obj.includes('"')) {
      return `"${obj.replace(/\\/g, '\\\\').replace(/"/g, '\\"')}"`;
    }
    return obj;
  }
  
  if (typeof obj === 'number' || typeof obj === 'boolean') {
    return String(obj);
  }
  
  if (Array.isArray(obj)) {
    if (obj.length === 0) return '[]';
    
    const items = obj.map(item => {
      if (typeof item === 'object' && item !== null && !Array.isArray(item)) {
        // For object items in array, format as "- key: value" style
        const innerYaml = toYaml(item, 0);
        const lines = innerYaml.split('\n').filter(l => l.trim());
        if (lines.length === 0) return `${spaces}- {}`;
        // First line goes after the dash, rest are indented
        const firstLine = lines[0].trim();
        const restLines = lines.slice(1).map(l => spaces + '  ' + l.trim()).join('\n');
        return `${spaces}- ${firstLine}${restLines ? '\n' + restLines : ''}`;
      }
      return `${spaces}- ${toYaml(item, indent + 1)}`;
    });
    return '\n' + items.join('\n');
  }
  
  if (typeof obj === 'object') {
    const entries = Object.entries(obj as Record<string, unknown>).filter(
      ([, v]) => v !== undefined
    );
    if (entries.length === 0) return '{}';
    
    const lines = entries.map(([key, value]) => {
      if (value === null || value === undefined) {
        return `${spaces}${key}: null`;
      }
      if (typeof value === 'object' && value !== null) {
        const inner = toYaml(value, indent + 1);
        if (Array.isArray(value)) {
          if (value.length === 0) return `${spaces}${key}: []`;
          return `${spaces}${key}:${inner}`;
        }
        if (Object.keys(value).length === 0) return `${spaces}${key}: {}`;
        return `${spaces}${key}:\n${inner}`;
      }
      return `${spaces}${key}: ${toYaml(value, indent)}`;
    });
    return lines.join('\n');
  }
  
  return String(obj);
}

// Syntax highlighting for YAML
function highlightYaml(yaml: string): React.ReactNode[] {
  const lines = yaml.split('\n');
  
  return lines.map((line, index) => {
    // Match key: value patterns
    const keyValueMatch = line.match(/^(\s*)([a-zA-Z0-9_-]+)(:)(.*)$/);
    if (keyValueMatch) {
      const [, indent, key, colon, value] = keyValueMatch;
      const trimmedValue = value.trim();
      
      // Determine value color
      let valueElement: React.ReactNode = value;
      if (trimmedValue.startsWith('"') || trimmedValue.startsWith("'") || trimmedValue === '|') {
        valueElement = <span className="text-green-500 dark:text-green-400">{value}</span>;
      } else if (trimmedValue === 'true' || trimmedValue === 'false' || trimmedValue === 'null') {
        valueElement = <span className="text-orange-500 dark:text-orange-400">{value}</span>;
      } else if (/^\s*-?\d+(\.\d+)?$/.test(trimmedValue)) {
        valueElement = <span className="text-blue-500 dark:text-blue-400">{value}</span>;
      } else if (value) {
        valueElement = <span className="text-foreground">{value}</span>;
      }
      
      return (
        <div key={index}>
          {indent}
          <span className="text-purple-500 dark:text-purple-400">{key}</span>
          <span className="text-muted-foreground">{colon}</span>
          {valueElement}
        </div>
      );
    }
    
    // Match list items with key-value after dash
    const listKeyValueMatch = line.match(/^(\s*)(-)(\s+)([a-zA-Z0-9_-]+)(:)(.*)$/);
    if (listKeyValueMatch) {
      const [, indent, dash, space, key, colon, value] = listKeyValueMatch;
      const trimmedValue = value.trim();
      
      let valueElement: React.ReactNode = value;
      if (trimmedValue.startsWith('"') || trimmedValue.startsWith("'")) {
        valueElement = <span className="text-green-500 dark:text-green-400">{value}</span>;
      } else if (trimmedValue === 'true' || trimmedValue === 'false' || trimmedValue === 'null') {
        valueElement = <span className="text-orange-500 dark:text-orange-400">{value}</span>;
      } else if (/^\s*-?\d+(\.\d+)?$/.test(trimmedValue)) {
        valueElement = <span className="text-blue-500 dark:text-blue-400">{value}</span>;
      } else if (value) {
        valueElement = <span className="text-foreground">{value}</span>;
      }
      
      return (
        <div key={index}>
          {indent}
          <span className="text-muted-foreground">{dash}</span>
          {space}
          <span className="text-purple-500 dark:text-purple-400">{key}</span>
          <span className="text-muted-foreground">{colon}</span>
          {valueElement}
        </div>
      );
    }
    
    // Match simple list items
    const listMatch = line.match(/^(\s*)(-)(.*)$/);
    if (listMatch) {
      const [, indent, dash, rest] = listMatch;
      return (
        <div key={index}>
          {indent}
          <span className="text-muted-foreground">{dash}</span>
          <span className="text-foreground">{rest}</span>
        </div>
      );
    }
    
    // Multi-line string content (indented text after |)
    if (line.match(/^\s{2,}\S/)) {
      return <div key={index} className="text-green-500 dark:text-green-400">{line}</div>;
    }
    
    return <div key={index}>{line}</div>;
  });
}

export function YamlViewer({ resource, title = 'YAML', maxHeight = '500px' }: YamlViewerProps) {
  const [copied, setCopied] = useState(false);

  const { yaml, highlightedYaml } = useMemo(() => {
    const cleanedResource = cleanResource(resource);
    const yamlString = toYaml(cleanedResource);
    return {
      yaml: yamlString,
      highlightedYaml: highlightYaml(yamlString),
    };
  }, [resource]);

  const handleCopy = async () => {
    await navigator.clipboard.writeText(yaml);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <Card>
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between">
          <CardTitle className="text-base flex items-center gap-2">
            <FileCode className="h-4 w-4 text-muted-foreground" />
            {title}
          </CardTitle>
          <Button variant="ghost" size="sm" onClick={handleCopy}>
            {copied ? (
              <>
                <Check className="h-4 w-4 mr-1 text-green-500" />
                Copied
              </>
            ) : (
              <>
                <Copy className="h-4 w-4 mr-1" />
                Copy
              </>
            )}
          </Button>
        </div>
      </CardHeader>
      <CardContent className="p-0">
        <ScrollArea className="rounded-lg border bg-muted/30" style={{ height: maxHeight, maxHeight }}>
          <pre className="p-4 text-xs font-mono whitespace-pre overflow-x-auto">
            {highlightedYaml}
          </pre>
        </ScrollArea>
      </CardContent>
    </Card>
  );
}
