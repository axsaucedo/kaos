import { existsSync, mkdirSync, readdirSync, statSync, writeFileSync } from 'node:fs';
import { join, relative } from 'node:path';

const repoRoot = join(process.cwd(), '..');
const testResultsDir = join(process.cwd(), 'test-results');
const outputDir = join(repoRoot, 'tmp');
const outputPath = join(outputDir, 'visual-failure-comment.md');
const runUrl = process.env.ACTIONS_RUN_URL || 'the Visual Tests workflow run';

function walkFiles(dir) {
  if (!existsSync(dir)) return [];

  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const fullPath = join(dir, entry.name);
    if (entry.isDirectory()) return walkFiles(fullPath);
    if (!entry.isFile()) return [];
    return fullPath;
  });
}

function listImageFiles(suffix) {
  return walkFiles(testResultsDir)
    .filter((file) => file.endsWith(suffix))
    .sort()
    .map((file) => relative(repoRoot, file));
}

const diffImages = listImageFiles('-diff.png');
const actualImages = listImageFiles('-actual.png');
const expectedImages = listImageFiles('-expected.png');
const failedDirs = existsSync(testResultsDir)
  ? readdirSync(testResultsDir)
      .map((name) => join(testResultsDir, name))
      .filter((path) => statSync(path).isDirectory())
      .map((path) => relative(repoRoot, path))
      .sort()
  : [];

function bulletList(items, emptyText) {
  if (items.length === 0) return `- ${emptyText}`;
  return items.map((item) => `- \`${item}\``).join('\n');
}

const body = `## Visual tests failed

The KAOS UI visual regression suite failed. Review the image artifacts before deciding whether this is a regression or an intentional UI change.

**Workflow run:** ${runUrl}

**Artifacts to download from the run:**
- \`visual-playwright-report\`
- \`visual-test-results\`

**Failed result directories:**
${bulletList(failedDirs, 'No test-result directories were found. Check the workflow log.')}

**Diff images:**
${bulletList(diffImages, 'No diff images were found. Check the Playwright report artifact.')}

**Actual images:**
${bulletList(actualImages, 'No actual images were found.')}

**Expected images:**
${bulletList(expectedImages, 'No expected images were found.')}

**Local debug commands:**
\`\`\`bash
cd kaos-ui
npm run test:visual
npx playwright show-report playwright-report/visual
\`\`\`

If the UI change is intentional, update and commit the affected snapshots:

\`\`\`bash
cd kaos-ui
npm run test:visual:update
npm run test:visual
\`\`\`

Only update snapshots after confirming the diffs match the intended UI change.
`;

mkdirSync(outputDir, { recursive: true });
writeFileSync(outputPath, body);
console.log(`Wrote ${relative(repoRoot, outputPath)}`);
