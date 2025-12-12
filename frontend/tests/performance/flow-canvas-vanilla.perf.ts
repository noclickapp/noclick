// Vanilla React Flow performance test - establishes the performance ceiling.
// This tests raw ReactFlow with default nodes to see what's achievable.

import { test, expect, Page } from '@playwright/test';

// Inject the drag tracker into the page
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

async function cleanupDragTracker(page: Page): Promise<void> {
    await page.evaluate(() => {
        const metrics = (window as any).__dragMetrics;
        if (metrics?.rafId) {
            cancelAnimationFrame(metrics.rafId);
        }
        delete (window as any).__dragMetrics;
    });
}

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

    const mousePositions: { x: number; y: number }[] = [];
    for (let i = 0; i <= totalSteps; i++) {
        const angle = (i / stepsPerRevolution) * 2 * Math.PI;
        mousePositions.push({
            x: Math.round(nodeX + radius * Math.cos(angle)),
            y: Math.round(nodeY + radius * Math.sin(angle)),
        });
    }

    await injectDragLagTracker(page);
    await page.mouse.move(nodeX, nodeY);
    await page.waitForTimeout(100);

    await page.evaluate(() => {
        const metrics = (window as any).__dragMetrics;
        const node = document.querySelector('.react-flow__node') as HTMLElement;
        if (node) {
            const rect = node.getBoundingClientRect();
            metrics.lastNodeX = rect.left + rect.width / 2;
            metrics.lastNodeY = rect.top + rect.height / 2;
        }
    });

    await cdpSession.send('Input.dispatchMouseEvent', {
        type: 'mousePressed',
        x: nodeX,
        y: nodeY,
        button: 'left',
        clickCount: 1,
    });

    await page.waitForTimeout(50);

    await page.evaluate(() => {
        const metrics = (window as any).__dragMetrics;
        metrics.isTracking = true;
        metrics.frameCount = 0;
        metrics.stalledFrames = 0;
        metrics.startTime = performance.now();
    });

    const INTERVAL_MS = 25;

    for (let i = 0; i < mousePositions.length; i++) {
        const pos = mousePositions[i];
        cdpSession.send('Input.dispatchMouseEvent', {
            type: 'mouseMoved',
            x: pos.x,
            y: pos.y,
            button: 'left',
        });

        if (i < mousePositions.length - 1) {
            await new Promise(resolve => setTimeout(resolve, INTERVAL_MS));
        }
    }

    await page.waitForTimeout(100);

    const lastPos = mousePositions[mousePositions.length - 1];
    await cdpSession.send('Input.dispatchMouseEvent', {
        type: 'mouseReleased',
        x: lastPos.x,
        y: lastPos.y,
        button: 'left',
        clickCount: 1,
    });

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

test.describe('Vanilla ReactFlow Performance (Ceiling)', () => {
    test.beforeEach(async ({ page }) => {
        await page.goto('/test/flow-perf-vanilla?nodes=25');

        await page.waitForFunction(
            () => (window as any).__perfTest?.isReady?.() === true,
            { timeout: 10000 }
        );

        await page.waitForSelector('.react-flow__node', { timeout: 5000 });
        await page.waitForTimeout(500);

        const canvas = await page.locator('.react-flow').first();
        const canvasBox = await canvas.boundingBox();
        if (canvasBox) {
            await page.mouse.move(
                canvasBox.x + canvasBox.width / 2,
                canvasBox.y + canvasBox.height / 2
            );
            await page.mouse.wheel(0, 300);
            await page.waitForTimeout(300);
        }
    });

    test('vanilla ReactFlow at 1x CPU throttle (ceiling)', async ({ page, context }) => {
        const cdpSession = await context.newCDPSession(page);
        await cdpSession.send('Emulation.setCPUThrottlingRate', { rate: 1 });

        const node = await page.locator('.react-flow__node').first();
        const box = await node.boundingBox();
        expect(box).toBeTruthy();

        const nodeX = box!.x + box!.width / 2;
        const nodeY = box!.y + box!.height / 2;

        const results = await measureCircularDragSmoothness(page, cdpSession, {
            nodeX,
            nodeY,
            radius: 200,
            revolutions: 3,
            stepsPerRevolution: 40,
        });

        console.log('VANILLA 1x throttle results:', results);
        await cdpSession.send('Emulation.setCPUThrottlingRate', { rate: 1 });
        expect(results.frameCount).toBeGreaterThan(10);
    });

    test('vanilla ReactFlow at 4x CPU throttle (ceiling)', async ({ page, context }) => {
        const cdpSession = await context.newCDPSession(page);
        await cdpSession.send('Emulation.setCPUThrottlingRate', { rate: 4 });

        const node = await page.locator('.react-flow__node').first();
        const box = await node.boundingBox();
        expect(box).toBeTruthy();

        const nodeX = box!.x + box!.width / 2;
        const nodeY = box!.y + box!.height / 2;

        const results = await measureCircularDragSmoothness(page, cdpSession, {
            nodeX,
            nodeY,
            radius: 200,
            revolutions: 3,
            stepsPerRevolution: 40,
        });

        console.log('VANILLA 4x throttle results:', results);
        await cdpSession.send('Emulation.setCPUThrottlingRate', { rate: 1 });
        expect(results.frameCount).toBeGreaterThan(0);
    });

    test('vanilla ReactFlow at 6x CPU throttle (ceiling)', async ({ page, context }) => {
        const cdpSession = await context.newCDPSession(page);
        await cdpSession.send('Emulation.setCPUThrottlingRate', { rate: 6 });

        const node = await page.locator('.react-flow__node').first();
        const box = await node.boundingBox();
        expect(box).toBeTruthy();

        const nodeX = box!.x + box!.width / 2;
        const nodeY = box!.y + box!.height / 2;

        const results = await measureCircularDragSmoothness(page, cdpSession, {
            nodeX,
            nodeY,
            radius: 200,
            revolutions: 3,
            stepsPerRevolution: 40,
        });

        console.log('VANILLA 6x throttle results:', results);
        await cdpSession.send('Emulation.setCPUThrottlingRate', { rate: 1 });
        expect(results.frameCount).toBeGreaterThan(0);
    });

    test('vanilla ReactFlow at 20x CPU throttle (ceiling)', async ({ page, context }) => {
        const cdpSession = await context.newCDPSession(page);
        await cdpSession.send('Emulation.setCPUThrottlingRate', { rate: 20 });

        const node = await page.locator('.react-flow__node').first();
        const box = await node.boundingBox();
        expect(box).toBeTruthy();

        const nodeX = box!.x + box!.width / 2;
        const nodeY = box!.y + box!.height / 2;

        const results = await measureCircularDragSmoothness(page, cdpSession, {
            nodeX,
            nodeY,
            radius: 200,
            revolutions: 3,
            stepsPerRevolution: 40,
        });

        console.log('VANILLA 20x throttle results:', results);
        await cdpSession.send('Emulation.setCPUThrottlingRate', { rate: 1 });
        expect(results.frameCount).toBeGreaterThan(0);
    });
});
