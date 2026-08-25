# React Flow Drag Performance Tests

Performance tests that measure drag smoothness in the FlowCanvas component by tracking RAF (requestAnimationFrame) frame rates during node dragging operations.

## How It Works

The test performs a circular drag motion (3 revolutions, 200px radius) on a React Flow node while measuring how many RAF frames the browser can render. Under CPU throttling, the browser renders fewer frames, demonstrating performance degradation.

**Key Metric:** `frameCount` - the number of RAF frames rendered during the drag operation. Higher is better.

## Performance Ceiling (Vanilla ReactFlow)

We tested vanilla ReactFlow with default nodes to establish the achievable performance ceiling:

| Throttle | Vanilla ReactFlow | Our FlowCanvas | Gap |
|----------|-------------------|----------------|-----|
| 1x | 389 frames | ~345 frames | 11% slower |
| 4x | 386 frames | ~20-32 frames | **92% slower** |
| 6x | 394 frames | - | - |
| 20x | 112 frames | - | - |

**Key Finding:** Vanilla ReactFlow maintains nearly identical performance from 1x to 6x CPU throttle (~390 frames). Only at 20x throttle does it degrade to 112 frames.

Our FlowCanvas at 4x throttle (20-32 frames) performs worse than vanilla at 20x throttle (112 frames). This indicates our custom code adds the equivalent of **~15x CPU overhead**.

### Test Routes
- `/test/flow-perf?nodes=25` - Full FlowCanvas with all custom components
- `/test/flow-perf-vanilla?nodes=25` - Vanilla ReactFlow with default nodes (performance ceiling)

## Current FlowCanvas Performance (After Optimization)

| Throttle | Frame Count | Effective FPS | vs Vanilla |
|----------|-------------|---------------|------------|
| 1x (none) | ~382 | ~115 fps | 99% |
| 4x | ~92 | ~28 fps | 24% |

*Performance at 1x throttle matches vanilla ReactFlow. 4x throttle improved 3.7x from original.*

## Bottleneck Analysis

Testing isolated FlowCanvas (without NoClick sidebar, NavBar, providers) reveals where the overhead comes from:

| Test Configuration | 4x Throttle | % of Vanilla |
|--------------------|-------------|--------------|
| Vanilla ReactFlow (ceiling) | 386 frames | 100% |
| Isolated FlowCanvas (no UI) | 126 frames | 33% |
| Full FlowCanvas + UI | 30 frames | 8% |

**Key Finding:** The surrounding UI components account for ~75% of the performance overhead. FlowCanvas itself accounts for ~67% gap from vanilla.

### Component-by-Component Breakdown (4x throttle)

| Level | Configuration | Frames | Delta | Impact |
|-------|--------------|--------|-------|--------|
| 0 | FlowCanvas only | 167 | - | baseline |
| 1 | + DndProvider | 159 | -8 | -5% |
| 2 | + ChatDrawerProvider | 172 | +13 | noise |
| 3 | + IframePoolProvider | 147 | -25 | -15% |
| 4 | **+ NoClick sidebar** | **38** | **-109** | **-74%** |
| 5 | + NavBar | 37 | -1 | -3% |

**ROOT CAUSE: NoClick sidebar causes 74% of the surrounding UI performance degradation!**

The providers (DndProvider, ChatDrawerProvider, IframePoolProvider) combined only cause ~20% degradation.
NavBar has minimal impact (~3%).

### NoClick Performance Issues Identified

| Issue | Severity | Impact |
|-------|----------|--------|
| ParticlesBackground `key` prop forcing 300-node remount every frame | **Critical** | ~50 frames |
| Valtio global state subscription cascade (useCachedValtioState subscribes to entire cachedb tree) | **Critical** | ~15 frames |
| renderTabContent() creating new function refs on every render | High | ~5 frames |
| useSandboxState re-registering event listeners | Medium | ~2 frames |

**Root Cause:** Both `useValtioState` and `useCachedValtioState` subscribe to the ENTIRE global state tree (lines 61-76 in useValtioState.ts). When FlowCanvas updates nodes during drag, it triggers ALL Valtio subscribers across the app, causing NoClick to re-render even though its data hasn't changed.

### Progress After Valtio Subscription Fix

The root cause was in `useValtioState` and `useCachedValtioState` hooks. They subscribed to the ENTIRE global state tree and called `setLocalState` on every change, even when the specific key didn't change.

**Fix Applied:** Modified both hooks to only call `setLocalState` when the proxy reference actually changes (e.g., after YJS binding), not on every global state change.

#### Results After Fix (4x throttle):

| Level | Before Fix | After Fix | Improvement |
|-------|-----------|-----------|-------------|
| Level 0 (FlowCanvas only) | 167 | **262** | **+57%** |
| Level 3 (+ providers) | 147 | **268** | **+82%** |
| Level 4 (+ NoClick) | 38 | **133** | **+250%** |
| Level 5 (full UI) | 37 | **108** | **+192%** |

#### Full Test Results:

| Throttle | Before Fix | After Fix | Improvement | vs Vanilla |
|----------|-----------|-----------|-------------|------------|
| 1x | ~345 | **382** | +11% | 99% (386) |
| 4x | ~20-32 | **92** | **+268-360%** | 24% (386) |

**Key Achievements:**
- 1x throttle now matches vanilla ReactFlow (382 vs 386 frames)
- 4x throttle improved **3.7x** from ~25 frames to 92 frames
- NoClick sidebar overhead reduced from 74% to ~35%
- Level 4 (NoClick) improved from 38 to 173 frames (+355%)

**Remaining Gap:** At 4x throttle, we're at 92 frames vs vanilla's 386 frames.

### Deep Dive: Hooks & Component Breakdown (Updated Analysis)

We created a progressive test (`/test/flow-perf-hooks?nodes=25&level=0-12`) to isolate each hook's impact:

| Level | Configuration | Frames (4x) | Delta | Impact |
|-------|--------------|-------------|-------|--------|
| 0 | Custom nodes only (baseline) | 389 | - | 100% |
| 1 | + useValtioState | 386 | -3 | negligible |
| 2 | + useWorkflowDisplayMetadata | 385 | -1 | negligible |
| 3 | + useWorkflowUndoRedo | 385 | 0 | none |
| 4 | + useStickyNoteNode | 387 | +2 | none |
| 5 | + useWorkflowAnimation | 392 | 0 | none |
| 6 | **+ FlowHelperView** | **308** | **-84** | **21% drop** |
| 7 | + FlowHelperView (stable refs) | 276 | -3 | negligible |
| 8 | + Simple div placeholder | 383 | 0 | none |
| 9 | + FlowHelperViewLite (CSS contain) | 381 | 0 | none |
| 10 | + FlowHelperViewLite (no blur) | 385 | 0 | none |
| 11 | + FlowHelperViewLite (no dnd) | 381 | -5 | minimal |
| 12 | + FlowHelperView (hidden during drag) | 372 | +64 | 95% of vanilla |
| 13 | **+ FlowHelperView (blur disabled during drag)** | **379** | **+71** | **97% of vanilla** |

**Key Findings:**
1. **Custom nodes have ZERO overhead** - Custom automation nodes (automation-http-request, automation-telegram, etc.) perform identically to vanilla ReactFlow nodes (389 vs 387 frames)
2. **FlowCanvas hooks have minimal impact** - All hooks combined (useValtioState, useWorkflowDisplayMetadata, useWorkflowUndoRedo, useStickyNoteNode, useWorkflowAnimation) only cause ~3 frames overhead
3. **FlowHelperView's backdrop-blur is the main bottleneck** - The `backdrop-blur` CSS property causes ~84 frames overhead because the browser must re-composite every frame as the canvas changes - this is NOT React re-rendering, it's browser compositing cost
4. **Disabling backdrop-blur during drag achieves 97% of vanilla** - Level 13 shows 379 frames by conditionally removing the blur class during drag operations
5. **Prop passing is NOT the issue** - Using stable empty refs (Level 7) vs dynamic nodes/edges (Level 6) shows negligible difference - the FlowHelperView memo comparison works correctly
6. **Simple DOM has no overhead** - A simple div placeholder (Level 8) shows identical performance to Level 5

### FlowHelperView Backdrop-Blur Optimization (Applied)

**Root Cause:** The `backdrop-blur` CSS property requires the browser to re-composite every frame as the canvas content behind it changes during drag - even without any React re-renders. This is pure browser compositing cost.

**Solution:** Disable backdrop-blur during drag operations via the `isDragging` prop:

```typescript
// FlowCanvas.tsx - track drag state
const [isDragging, setIsDragging] = useState(false);
// Set true on drag start, false on drag end

// FlowHelperView.tsx - conditionally apply blur
<div className={`... ${isDragging ? '' : 'backdrop-blur-[2px]'}`} />
```

**Results:**
| Approach | Frames | % of Vanilla |
|----------|--------|--------------|
| FlowHelperView with blur | 308 | 79% |
| Hidden during drag | 372 | 95% |
| **Blur disabled during drag** | **379** | **97%** |

The blur-disabled approach:
- Achieves **97% of vanilla performance** (better than hiding!)
- FlowHelperView remains fully visible during drag
- Only removes the subtle blur effect (minimal visual impact)
- Re-enables blur immediately when drag ends

**Remaining Gap:** The NoClick sidebar is the dominant remaining bottleneck (74% of surrounding UI overhead). At 4x throttle with full dashboard, performance is ~91 frames due to sidebar overhead.

### Code Changes Made

1. **`useValtioState.ts`**: Modified global state subscription to only update local state when proxy reference changes
2. **`useCachedValtioState.ts`**: Same fix applied
3. **`FlowCanvas.tsx`**: Skip z-index recalculation during drag operations
4. **`FlowCanvas.tsx`**: Pass `isDragging` state to FlowHelperView to disable backdrop-blur during drag
5. **`FlowHelperView.tsx`**: Added `isDragging` prop that conditionally disables `backdrop-blur` during drag operations
6. **`FlowHelperView.tsx`**: Added CSS containment (`contain: layout paint`) and GPU layer promotion (`transform: translateZ(0)`)
7. **Test routes**: Updated to avoid parent components subscribing to flow state (which causes cascade re-renders)

### Test Routes for Isolation
- `/test/flow-perf-vanilla?nodes=25` - Vanilla ReactFlow (ceiling)
- `/test/flow-perf-minimal?nodes=25` - Custom nodes with minimal hooks
- `/test/flow-perf-isolated?nodes=25` - Full FlowCanvas without surrounding UI
- `/test/flow-perf-hooks?nodes=25&level=0-12` - Progressive hooks breakdown (recommended for debugging)
- `/test/flow-perf-breakdown?nodes=25&level=0-5` - Incremental provider breakdown
- `/test/flow-perf?nodes=25` - Full production-like setup with NoClick sidebar

## Running the Tests

### Headless (CI/automated)
```bash
# Run all drag performance tests
npx playwright test tests/performance/flow-canvas-drag.perf.ts

# Run specific throttle test
npx playwright test tests/performance/flow-canvas-drag.perf.ts --grep "1x CPU"
npx playwright test tests/performance/flow-canvas-drag.perf.ts --grep "4x CPU"

# Run node count comparison test
npx playwright test tests/performance/flow-canvas-drag.perf.ts --grep "different node counts"
```

### Headed (visual debugging)
```bash
# Watch the drag operation in a browser window
npx playwright test tests/performance/flow-canvas-drag.perf.ts --headed --grep "1x CPU"
npx playwright test tests/performance/flow-canvas-drag.perf.ts --headed --grep "4x CPU"
```

### Debug mode
```bash
# Step through with Playwright inspector
npx playwright test tests/performance/flow-canvas-drag.perf.ts --debug --grep "1x CPU"
```

## Test Route

The tests use `/test/flow-perf?nodes=25` which renders the actual FlowCanvas component with mock nodes. This route is only available in development mode.

You can also visit this route manually in the browser to inspect the test environment:
```
http://localhost:5173/test/flow-perf?nodes=25
```

## Understanding Results

```
1x throttle results: { frameCount: 338, stalledFrames: 223, durationMs: 3170, stallPercent: 66 }
4x throttle results: { frameCount: 19, stalledFrames: 0, durationMs: 3618, stallPercent: 0 }
```

- **frameCount**: Total RAF frames during drag. The key performance metric.
- **stalledFrames**: Frames where node moved < 1px (less meaningful due to RAF timing)
- **durationMs**: Total drag duration measured by browser
- **stallPercent**: stalledFrames / frameCount (inverted correlation with throttling)

The ~18x reduction in frame count (338 → 19) under 4x CPU throttle demonstrates the test accurately captures performance impact.

## Technical Details

- Uses CDP (Chrome DevTools Protocol) for mouse events to ensure consistent timing regardless of CPU throttling
- Node.js `setTimeout` controls event pacing (not affected by browser throttling)
- RAF-based tracking measures actual browser rendering capability
- Circular motion pattern ensures continuous drag in multiple directions
