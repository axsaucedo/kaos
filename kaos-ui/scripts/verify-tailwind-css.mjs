import { existsSync, readdirSync, readFileSync } from 'node:fs';
import { join } from 'node:path';

const cssDir = join(process.cwd(), 'dist', 'assets');

if (!existsSync(cssDir)) {
  throw new Error('Missing dist/assets directory. Run `npm run build` before verifying styles.');
}

const cssFiles = readdirSync(cssDir).filter((file) => /^index-.*\.css$/.test(file));

if (cssFiles.length === 0) {
  throw new Error('No built index CSS asset found in dist/assets.');
}

const css = cssFiles.map((file) => readFileSync(join(cssDir, file), 'utf8')).join('\n');
const requiredSelectors = [
  'p-6',
  'text-sm',
  'shadow-sm',
  'inset-0',
  'bg-background',
  'text-foreground',
  'border-border',
  'flex',
  'grid',
  'gap-4',
];

const missingSelectors = requiredSelectors.filter((selector) => {
  const escapedSelector = selector.replace(/[-/\\^$*+?.()|[\]{}]/g, '\\$&');
  return !new RegExp(`(^|[\\n}])\\s*\\.${escapedSelector}(?=[\\s,.#:{>\\[])`).test(css);
});

if (missingSelectors.length > 0) {
  throw new Error(`Built CSS is missing Tailwind selectors: ${missingSelectors.join(', ')}`);
}

console.log(`Verified Tailwind selectors in ${cssFiles.join(', ')}`);
