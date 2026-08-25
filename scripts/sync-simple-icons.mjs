#!/usr/bin/env node

/**
 * Rebuild the reviewed integration-icon directory.
 *
 * `asset-provenance.json` is the allowlist. Every shipped file is either a
 * pinned Simple Icons asset, an in-repository neutral monogram, or an explicit
 * custom-asset exception with a reviewed hash and license. Unknown files fail
 * the check instead of silently acquiring an assumed provenance.
 *
 * Usage:
 *   npm ci
 *   npm run assets:sync
 *   npm run assets:check
 */

import { createHash } from 'node:crypto';
import {
  copyFile,
  mkdir,
  readFile,
  readdir,
  unlink,
  writeFile,
} from 'node:fs/promises';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const checkOnly = process.argv.slice(2).includes('--check');
const unexpectedArgs = process.argv.slice(2).filter((arg) => arg !== '--check');
if (unexpectedArgs.length > 0) {
  throw new Error(`Unknown arguments: ${unexpectedArgs.join(', ')}`);
}

const require = createRequire(import.meta.url);
const catalog = require('simple-icons');
const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const outputRoot = path.resolve(scriptDir, '..');
const isOverrideSource =
  path.basename(outputRoot) === 'overrides' &&
  path.basename(path.dirname(outputRoot)) === 'oss';
const inventoryRoot = isOverrideSource
  ? path.resolve(outputRoot, '..', '..')
  : outputRoot;
const manifestPath = path.join(scriptDir, 'asset-provenance.json');
const manifest = JSON.parse(await readFile(manifestPath, 'utf8'));
const inventoryDir = path.join(inventoryRoot, manifest.scope);
const outputDir = path.join(outputRoot, manifest.scope);

const simplePackage = JSON.parse(
  await readFile(
    path.join(path.dirname(require.resolve('simple-icons')), 'package.json'),
    'utf8',
  ),
);
if (
  simplePackage.version !== manifest.simpleIcons.version ||
  simplePackage.license !== manifest.simpleIcons.license
) {
  throw new Error(
    `simple-icons package metadata drift: expected ${manifest.simpleIcons.version} ` +
      `(${manifest.simpleIcons.license}), found ${simplePackage.version} ` +
      `(${simplePackage.license})`,
  );
}

const bySlug = new Map(Object.values(catalog).map((icon) => [icon.slug, icon]));
const simpleAssets = manifest.simpleIcons.assets;
const monogramAssets = new Set(manifest.generatedMonograms);
const customAssets = new Map(
  manifest.reviewedCustomAssets.map((asset) => [path.basename(asset.path), asset]),
);
const excludedSourceAssets = new Set(
  manifest.excludedSourceAssets.map((asset) => path.basename(asset.path)),
);
const declared = [
  ...Object.keys(simpleAssets),
  ...monogramAssets,
  ...customAssets.keys(),
];

if (new Set(declared).size !== declared.length) {
  throw new Error('asset-provenance.json declares an asset more than once');
}
for (const asset of [
  ...manifest.reviewedCustomAssets,
  ...manifest.excludedSourceAssets,
]) {
  const normalized = path.posix.normalize(asset.path);
  if (
    normalized !== asset.path ||
    !normalized.startsWith(`${manifest.scope}/`) ||
    normalized.includes('/../')
  ) {
    throw new Error(`Asset manifest path escapes its reviewed scope: ${asset.path}`);
  }
}
for (const name of declared) {
  if (name !== path.basename(name)) {
    throw new Error(`Integration asset must be a filename, not a path: ${name}`);
  }
}

const {
  files: inventoryFiles,
  rejected: rejectedInventoryEntries,
} = await inspectAssetDirectory(inventoryDir);
if (rejectedInventoryEntries.length > 0) {
  throw new Error(
    'Integration asset scope must contain top-level regular files only; ' +
      `rejected entries: ${rejectedInventoryEntries.join(', ')}`,
  );
}
const permittedInventory = new Set(declared);
if (isOverrideSource) {
  for (const excluded of excludedSourceAssets) permittedInventory.add(excluded);
}
const undeclaredInventory = inventoryFiles.filter(
  (name) => !permittedInventory.has(name),
);
const missingInventory = declared.filter(
  (name) => !inventoryFiles.includes(name),
);
if (undeclaredInventory.length > 0 || missingInventory.length > 0) {
  throw new Error(
    [
      undeclaredInventory.length > 0
        ? `unreviewed integration assets: ${undeclaredInventory.join(', ')}`
        : '',
      missingInventory.length > 0
        ? `manifest assets missing from inventory: ${missingInventory.join(', ')}`
        : '',
    ]
      .filter(Boolean)
      .join('; '),
  );
}

const expected = new Map();
for (const [filename, slug] of Object.entries(simpleAssets).sort()) {
  const icon = bySlug.get(slug);
  if (!icon) throw new Error(`Simple Icons has no ${slug} icon`);
  expected.set(
    filename,
    [
      `<!-- Source: Simple Icons ${manifest.simpleIcons.version} ` +
        `(${manifest.simpleIcons.license}); trademarks belong to their owners. -->`,
      `<svg role="img" aria-label="${escapeXml(icon.title)}" ` +
        'viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">',
      `<path fill="#${icon.hex}" d="${icon.path}"/>`,
      '</svg>',
      '',
    ].join('\n'),
  );
}

for (const filename of [...monogramAssets].sort()) {
  const stem = filename.slice(0, -path.extname(filename).length);
  const title = stem
    .replace(/-(light|marker|wordmark)$/g, '')
    .split('-')
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(' ');
  const initials = title
    .split(/\s+/)
    .map((part) => part[0])
    .join('')
    .slice(0, 2);
  const hue = [...stem].reduce(
    (value, char) => value + char.charCodeAt(0),
    0,
  ) % 360;
  expected.set(
    filename,
    [
      '<!-- Generated by scripts/sync-simple-icons.mjs; no third-party artwork. -->',
      `<svg role="img" aria-label="${escapeXml(title)}" viewBox="0 0 24 24" ` +
        'xmlns="http://www.w3.org/2000/svg">',
      `<circle cx="12" cy="12" r="11" fill="hsl(${hue} 45% 38%)"/>`,
      `<text x="12" y="12.4" fill="white" ` +
        'font-family="ui-sans-serif,system-ui,sans-serif" font-size="8" ' +
        `font-weight="700" text-anchor="middle" dominant-baseline="middle">${escapeXml(initials)}</text>`,
      '</svg>',
      '',
    ].join('\n'),
  );
}

for (const [filename, asset] of [...customAssets.entries()].sort()) {
  if (!asset.source || !asset.license || !asset.sha256) {
    throw new Error(
      `Custom asset ${filename} must declare source, license, and sha256`,
    );
  }
  const sourcePath = path.join(inventoryRoot, asset.path);
  const content = await readFile(sourcePath);
  const digest = createHash('sha256').update(content).digest('hex');
  if (digest !== asset.sha256) {
    throw new Error(
      `Custom asset hash drift for ${filename}: expected ${asset.sha256}, found ${digest}`,
    );
  }
  expected.set(filename, content);
}

await mkdir(outputDir, { recursive: true });
if (checkOnly) {
  await verifyOutput(outputDir, expected);
  console.log(`Verified ${expected.size} reviewed integration assets.`);
} else {
  const {
    files: outputFiles,
    rejected: rejectedOutputEntries,
  } = await inspectAssetDirectory(outputDir);
  if (rejectedOutputEntries.length > 0) {
    throw new Error(
      'Generated asset directory must contain top-level regular files only; ' +
        `rejected entries: ${rejectedOutputEntries.join(', ')}`,
    );
  }
  for (const filename of outputFiles) {
    if (!expected.has(filename)) await unlink(path.join(outputDir, filename));
  }
  for (const [filename, content] of expected) {
    const destination = path.join(outputDir, filename);
    if (Buffer.isBuffer(content)) {
      await copyFile(path.join(inventoryRoot, customAssets.get(filename).path), destination);
    } else {
      await writeFile(destination, content, 'utf8');
    }
  }
  await verifyOutput(outputDir, expected);
  console.log(`Wrote ${expected.size} reviewed integration assets.`);
}

function escapeXml(value) {
  return value
    .replaceAll('&', '&amp;')
    .replaceAll('"', '&quot;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;');
}

async function verifyOutput(directory, expectedFiles) {
  const {
    files: actualNames,
    rejected: rejectedOutputEntries,
  } = await inspectAssetDirectory(directory);
  if (rejectedOutputEntries.length > 0) {
    throw new Error(
      'Generated asset directory must contain top-level regular files only; ' +
        `rejected entries: ${rejectedOutputEntries.join(', ')}`,
    );
  }
  const expectedNames = [...expectedFiles.keys()].sort();
  if (JSON.stringify(actualNames) !== JSON.stringify(expectedNames)) {
    throw new Error(
      `Generated asset inventory drift: expected ${expectedNames.join(', ')}, ` +
        `found ${actualNames.join(', ')}`,
    );
  }
  for (const filename of expectedNames) {
    const actual = await readFile(path.join(directory, filename));
    const wanted = expectedFiles.get(filename);
    const wantedBuffer = Buffer.isBuffer(wanted) ? wanted : Buffer.from(wanted);
    if (!actual.equals(wantedBuffer)) {
      throw new Error(`Generated asset is stale: ${path.join(manifest.scope, filename)}`);
    }
  }
}

async function inspectAssetDirectory(directory) {
  const files = [];
  const rejected = [];

  async function walk(current, prefix = '') {
    const entries = await readdir(current, { withFileTypes: true });
    for (const entry of entries) {
      const relative = prefix
        ? path.posix.join(prefix, entry.name)
        : entry.name;
      if (entry.isFile()) {
        files.push(relative);
      } else if (entry.isDirectory()) {
        // Walk it so a diagnostic inventories every hidden nested input, but
        // reject the directory itself because manifest entries are filenames.
        rejected.push(`${relative}/`);
        await walk(path.join(current, entry.name), relative);
      } else {
        // Symlinks and special files can point outside the reviewed scope.
        rejected.push(relative);
      }
    }
  }

  await walk(directory);
  return {
    files: files.sort(),
    rejected: rejected.sort(),
  };
}
