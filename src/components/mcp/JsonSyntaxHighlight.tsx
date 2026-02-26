import React from 'react';

interface JsonSyntaxHighlightProps {
  json: string;
  className?: string;
}

/**
 * Simple JSON syntax highlighter using regex-based tokenization.
 * Renders colored spans for keys, strings, numbers, booleans, and null values.
 */
export function JsonSyntaxHighlight({ json, className = '' }: JsonSyntaxHighlightProps) {
  const highlighted = json
    // Keys
    .replace(/"([^"]+)"(?=\s*:)/g, '<span class="text-sky-400">"$1"</span>')
    // String values
    .replace(/:\s*"([^"]*?)"/g, (match, val) => `: <span class="text-emerald-400">"${val}"</span>`)
    // Numbers
    .replace(/:\s*(-?\d+\.?\d*)/g, ': <span class="text-amber-400">$1</span>')
    // Booleans
    .replace(/:\s*(true|false)/g, ': <span class="text-purple-400">$1</span>')
    // Null
    .replace(/:\s*(null)/g, ': <span class="text-red-400">$1</span>');

  return (
    <pre
      className={`text-xs font-mono whitespace-pre-wrap break-all ${className}`}
      dangerouslySetInnerHTML={{ __html: highlighted }}
    />
  );
}
