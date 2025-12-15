// Performance test for React Flow drag operations.
// Measures drag smoothness by tracking stalled frames during node dragging.
// Uses the actual FlowCanvas component via the /test/flow-perf route.

import { test, expect, Page } from '@playwright/test';

// Inject the drag tracker into the page - measures frame count and stalled frames
async function injectDragLagTracker(page: Page): Promise<void> {
    await page.evaluate(() => {
        (window as any).__dragMetrics = {
            frameCount: 0,
            stalledFrames: 0,
            lastNodeX: 0,
            lastNodeY: 0,
            isTracking: false,
            startTime: 0,
            rafId: 0,
        };

        // Continuous RAF-based frame counter
        const measureFrames = () => {
            const metrics = (window as any).__dragMetrics;

            if (!metrics.isTracking) {
                metrics.rafId = requestAnimationFrame(measureFrames);
                return;
            }

            const node = document.querySelector('.react-flow__node') as HTMLElement;
            if (node) {
                const rect = node.getBoundingClientRect();
                const nodeX = rect.left + rect.width / 2;
                const nodeY = rect.top + rect.height / 2;

                const deltaX = nodeX - metrics.lastNodeX;
                const deltaY = nodeY - metrics.lastNodeY;
                const moved = Math.sqrt(deltaX * deltaX + deltaY * deltaY);

                metrics.frameCount++;

                // Count stalled frames (node moved less than 1px)
                if (moved < 1 && metrics.frameCount > 1) {
                    metrics.stalledFrames++;
                }

                metrics.lastNodeX = nodeX;
                metrics.lastNodeY = nodeY;
            }

            metrics.rafId = requestAnimationFrame(measureFrames);
        };

        (window as any).__dragMetrics.rafId = requestAnimationFrame(measureFrames);
    });
}

// Start tracking drag with initial mouse position
async function startDragTracking(page: Page, mouseX: number): Promise<void> {
    await page.evaluate((startMouseX) => {
        const metrics = (window as any).__dragMetrics;
        const node = document.querySelector('.react-flow__node') as HTMLElement;
        if (node) {
            const rect = node.getBoundingClientRect();
            metrics.startNodeScreenX = rect.left + rect.width / 2;
            metrics.lastNodeScreenX = metrics.startNodeScreenX;
        }
        metrics.startMouseX = startMouseX;
        metrics.currentExpectedX = metrics.startNodeScreenX;
        metrics.isTracking = true;
        metrics.samples = [];
        metrics.stalledFrames = 0;
    }, mouseX);
}

// Update expected position based on mouse movement
async function recordDragSample(page: Page, mouseX: number): Promise<void> {
    await page.evaluate((currentMouseX) => {
        const metrics = (window as any).__dragMetrics;
        const mouseDelta = currentMouseX - metrics.startMouseX;
        metrics.currentExpectedX = metrics.startNodeScreenX + mouseDelta;
    }, mouseX);
}

// Stop tracking and return results
async function stopDragTracking(page: Page): Promise<{
    sampleCount: number;
    stalledFrames: number;
    avgLag: number;
    maxLag: number;
}> {
    return await page.evaluate(() => {
        const metrics = (window as any).__dragMetrics;
        metrics.isTracking = false;

        const samples = metrics.samples;
        if (samples.length === 0) {
            return { sampleCount: 0, stalledFrames: 0, avgLag: 0, maxLag: 0 };
        }

        const lags = samples.map((s: any) => s.lag);
        const avgLag = lags.reduce((a: number, b: number) => a + b, 0) / lags.length;
        const maxLag = Math.max(...lags);

        return {
            sampleCount: samples.length,
            stalledFrames: metrics.stalledFrames,
            avgLag,
            maxLag,
        };
    });
}

// Clean up tracker
async function cleanupDragTracker(page: Page): Promise<void> {
    await page.evaluate(() => {
        const metrics = (window as any).__dragMetrics;
        if (metrics?.rafId) {
            cancelAnimationFrame(metrics.rafId);
        }
        delete (window as any).__dragMetrics;
    });
}

// Perform circular drag - fires all CDP events without waiting, then measures
async function measureCircularDragSmoothness(
    page: Page,
    cdpSession: any,
    options: {
        nodeX: number;
        nodeY: number;
        radius: number;
        revolutions: number;
        stepsPerRevolution: number;
    }
): Promise<{ stalledFrames: number; frameCount: number; durationMs: number; stallPercent: number }> {
    const { nodeX, nodeY, radius, revolutions, stepsPerRevolution } = options;
    const totalSteps = revolutions * stepsPerRevolution;

    // Pre-calculate ALL mouse positions
    const mousePositions: { x: number; y: number }[] = [];
    for (let i = 0; i <= totalSteps; i++) {
        const angle = (i / stepsPerRevolution) * 2 * Math.PI;
        mousePositions.push({
            x: Math.round(nodeX + radius * Math.cos(angle)),
            y: Math.round(nodeY + radius * Math.sin(angle)),
        });
    }

    // Inject tracker
    await injectDragLagTracker(page);

    // Move to node and prepare
    await page.mouse.move(nodeX, nodeY);
    await page.waitForTimeout(100);

    // Initialize node position for tracking
    await page.evaluate(() => {
        const metrics = (window as any).__dragMetrics;
        const node = document.querySelector('.react-flow__node') as HTMLElement;
        if (node) {
            const rect = node.getBoundingClientRect();
            metrics.lastNodeX = rect.left + rect.width / 2;
            metrics.lastNodeY = rect.top + rect.height / 2;
        }
    });

    // Mouse down via CDP
    await cdpSession.send('Input.dispatchMouseEvent', {
        type: 'mousePressed',
        x: nodeX,
        y: nodeY,
        button: 'left',
        clickCount: 1,
    });

    await page.waitForTimeout(50);

    // Start tracking
    await page.evaluate(() => {
        const metrics = (window as any).__dragMetrics;
        metrics.isTracking = true;
        metrics.frameCount = 0;
        metrics.stalledFrames = 0;
        metrics.startTime = performance.now();
    });

    // Fire mouse move events with timing - pace at ~40fps (25ms intervals)
    // Use a simple loop with delays controlled by Node.js (not browser)
    const sendStart = Date.now();
    const INTERVAL_MS = 25; // ~40fps pacing

    for (let i = 0; i < mousePositions.length; i++) {
        const pos = mousePositions[i];
        // Fire event without waiting for browser response
        cdpSession.send('Input.dispatchMouseEvent', {
            type: 'mouseMoved',
            x: pos.x,
            y: pos.y,
            button: 'left',
        });

        // Small Node.js delay (not affected by browser throttling)
        if (i < mousePositions.length - 1) {
            await new Promise(resolve => setTimeout(resolve, INTERVAL_MS));
        }
    }

    const sendEnd = Date.now();
    console.log(`Fired ${mousePositions.length} events in ${sendEnd - sendStart}ms (target: ${mousePositions.length * INTERVAL_MS}ms)`);

    // Brief wait for last events to be processed
    await page.waitForTimeout(100);

    // Mouse up
    const lastPos = mousePositions[mousePositions.length - 1];
    await cdpSession.send('Input.dispatchMouseEvent', {
        type: 'mouseReleased',
        x: lastPos.x,
        y: lastPos.y,
        button: 'left',
        clickCount: 1,
    });

    // Get results
    const results = await page.evaluate(() => {
        const metrics = (window as any).__dragMetrics;
        metrics.isTracking = false;
        const endTime = performance.now();
        const frameCount = metrics.frameCount || 0;
        const stalledFrames = metrics.stalledFrames || 0;
        return {
            frameCount,
            stalledFrames,
            durationMs: Math.round(endTime - (metrics.startTime || endTime)),
            stallPercent: frameCount > 0 ? Math.round((stalledFrames / frameCount) * 100) : 0,
        };
    });

    await cleanupDragTracker(page);
    return results;
}

test.describe('FlowCanvas Drag Performance', () => {
    test.beforeEach(async ({ page }) => {
        // Navigate to perf test route
        await page.goto('/test/flow-perf?nodes=25');

        // Wait for test API to be ready
        await page.waitForFunction(
            () => (window as any).__perfTest?.isReady?.() === true,
            { timeout: 10000 }
        );

        // Wait for nodes to render
        await page.waitForSelector('.react-flow__node', { timeout: 5000 });
        await page.waitForTimeout(500);

        // Zoom out the canvas to see more nodes (use mouse wheel on the canvas)
        const canvas = await page.locator('.react-flow').first();
        const canvasBox = await canvas.boundingBox();
        if (canvasBox) {
            // Move mouse to center of canvas
            await page.mouse.move(
                canvasBox.x + canvasBox.width / 2,
                canvasBox.y + canvasBox.height / 2
            );
            // Zoom out with mouse wheel (positive deltaY = zoom out)
            await page.mouse.wheel(0, 300); // Zoom out a bit
            await page.waitForTimeout(300);
        }
    });

    test('measures drag smoothness at 1x CPU throttle', async ({ page, context }) => {
        // Get CDP session for throttling
        const cdpSession = await context.newCDPSession(page);
        await cdpSession.send('Emulation.setCPUThrottlingRate', { rate: 1 });

        // Find first node and use it as center for circular drag
        const node = await page.locator('.react-flow__node').first();
        const box = await node.boundingBox();
        expect(box).toBeTruthy();

        const nodeX = box!.x + box!.width / 2;
        const nodeY = box!.y + box!.height / 2;

        // Perform circular drag - 3 revolutions, big radius, slower pace
        const results = await measureCircularDragSmoothness(page, cdpSession, {
            nodeX,
            nodeY,
            radius: 200,
            revolutions: 3,
            stepsPerRevolution: 40,
        });

        console.log('1x throttle results:', results);

        // Disable throttling
        await cdpSession.send('Emulation.setCPUThrottlingRate', { rate: 1 });

        // Assert test collected data
        expect(results.frameCount).toBeGreaterThan(10);
    });

    test('measures drag smoothness at 4x CPU throttle', async ({ page, context }) => {
        // Get CDP session for throttling
        const cdpSession = await context.newCDPSession(page);
        await cdpSession.send('Emulation.setCPUThrottlingRate', { rate: 4 });

        // Find first node
        const node = await page.locator('.react-flow__node').first();
        const box = await node.boundingBox();
        expect(box).toBeTruthy();

        const nodeX = box!.x + box!.width / 2;
        const nodeY = box!.y + box!.height / 2;

        // Perform circular drag - 3 revolutions, big radius, slower pace
        const results = await measureCircularDragSmoothness(page, cdpSession, {
            nodeX,
            nodeY,
            radius: 200,
            revolutions: 3,
            stepsPerRevolution: 40,
        });

        console.log('4x throttle results:', results);

        // Disable throttling
        await cdpSession.send('Emulation.setCPUThrottlingRate', { rate: 1 });

        // Performance gate: At 4x throttle with warmup scroll, we must maintain minimum frames
        // This ensures drag performance doesn't regress below acceptable levels.
        // Local baseline: ~370 frames (native macOS)
        // Docker/act baseline: ~150 frames (virtualization overhead)
        // GitHub Actions baseline: ~56 frames (shared runners have high contention)
        // CI threshold of 40 provides buffer while catching significant regressions.
        expect(results.frameCount).toBeGreaterThanOrEqual(45);
    });

    test('compares performance with different node counts', async ({ page, context }) => {
        const cdpSession = await context.newCDPSession(page);
        await cdpSession.send('Emulation.setCPUThrottlingRate', { rate: 2 });

        const nodeCounts = [10, 50, 100];
        const results: Record<number, { stalledFrames: number; sampleCount: number }> = {};

        for (const count of nodeCounts) {
            // Inject new node count
            await page.evaluate((nodeCount) => {
                (window as any).__perfTest.injectNodes(nodeCount);
            }, count);

            await page.waitForTimeout(500);

            // Find first node
            const node = await page.locator('.react-flow__node').first();
            const box = await node.boundingBox();
            if (!box) continue;

            const nodeX = box.x + box.width / 2;
            const nodeY = box.y + box.height / 2;

            // Measure circular drag with slower pace
            const measurement = await measureCircularDragSmoothness(page, cdpSession, {
                nodeX,
                nodeY,
                radius: 200,
                revolutions: 3,
                stepsPerRevolution: 40,
            });

            results[count] = measurement;
            console.log(`${count} nodes:`, measurement);
        }

        // Disable throttling
        await cdpSession.send('Emulation.setCPUThrottlingRate', { rate: 1 });

        // Log comparison
        console.log('Performance comparison:', results);
    });
});
