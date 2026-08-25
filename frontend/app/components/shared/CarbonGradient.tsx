/**
 * CarbonGradient - Generates deterministic carbon-themed gradient thumbnails
 * using WebGL with positions derived from a hash of the input name/id.
 * Uses a single shared WebGL context to render each gradient once, captures it
 * as a data URL, and displays as an <img>. This avoids browser WebGL context
 * limits (typically 8-16) that cause blank canvases when many cards are visible.
 */

import { useMemo, memo } from 'react';

// Simplex noise implementation for organic grain
const SIMPLEX_NOISE_GLSL = `
// Simplex 2D noise
vec3 permute(vec3 x) { return mod(((x*34.0)+1.0)*x, 289.0); }

float snoise(vec2 v) {
    const vec4 C = vec4(0.211324865405187, 0.366025403784439,
                        -0.577350269189626, 0.024390243902439);
    vec2 i  = floor(v + dot(v, C.yy));
    vec2 x0 = v - i + dot(i, C.xx);
    vec2 i1;
    i1 = (x0.x > x0.y) ? vec2(1.0, 0.0) : vec2(0.0, 1.0);
    vec4 x12 = x0.xyxy + C.xxzz;
    x12.xy -= i1;
    i = mod(i, 289.0);
    vec3 p = permute(permute(i.y + vec3(0.0, i1.y, 1.0))
                   + i.x + vec3(0.0, i1.x, 1.0));
    vec3 m = max(0.5 - vec3(dot(x0,x0), dot(x12.xy,x12.xy),
                            dot(x12.zw,x12.zw)), 0.0);
    m = m*m;
    m = m*m;
    vec3 x = 2.0 * fract(p * C.www) - 1.0;
    vec3 h = abs(x) - 0.5;
    vec3 ox = floor(x + 0.5);
    vec3 a0 = x - ox;
    m *= 1.79284291400159 - 0.85373472095314 * (a0*a0 + h*h);
    vec3 g;
    g.x = a0.x * x0.x + h.x * x0.y;
    g.yz = a0.yz * x12.xz + h.yz * x12.yw;
    return 130.0 * dot(m, g);
}
`;

const VERTEX_SHADER = `
attribute vec2 a_position;
void main() {
    gl_Position = vec4(a_position, 0.0, 1.0);
}
`;

const FRAGMENT_SHADER = `
precision highp float;

uniform vec2 u_resolution;
uniform float u_seed;
uniform float u_grainIntensity;
uniform float u_grainScale;
uniform float u_blobSize;
uniform float u_blobSoftness;
uniform float u_complexity;
uniform float u_distortion;
uniform float u_opacity;
uniform vec3 u_color1;
uniform vec3 u_color2;
uniform vec3 u_color3;
uniform vec3 u_color4;
uniform vec3 u_color5;
uniform vec3 u_color6;
uniform vec3 u_bgColor;
uniform vec2 u_blob1Pos;
uniform vec2 u_blob2Pos;
uniform vec2 u_blob3Pos;
uniform vec2 u_blob4Pos;
uniform vec2 u_blob5Pos;
uniform vec2 u_blob6Pos;

${SIMPLEX_NOISE_GLSL}

// Fractional Brownian Motion for complex, layered noise
float fbm(vec2 p, float seed, int octaves) {
    float value = 0.0;
    float amplitude = 0.5;
    float frequency = 1.0;
    for (int i = 0; i < 6; i++) {
        if (i >= octaves) break;
        value += amplitude * snoise(p * frequency + seed);
        amplitude *= 0.5;
        frequency *= 2.0;
    }
    return value;
}

// Warped coordinates using noise for liquid effect
vec2 warpUV(vec2 uv, float seed, float amount) {
    float nx = fbm(uv * 2.0 + seed, seed, 4);
    float ny = fbm(uv * 2.0 + seed + 100.0, seed + 50.0, 4);
    return uv + vec2(nx, ny) * amount;
}

// Metaball-style distance with noise distortion for organic shapes
float liquidBlob(vec2 uv, vec2 center, float size, float seed, float distortAmount) {
    vec2 diff = uv - center;
    float angle = atan(diff.y, diff.x);
    float dist = length(diff);
    float edgeNoise = fbm(vec2(angle * 2.0, dist * 3.0) + seed, seed, 4);
    float warpedDist = dist + edgeNoise * distortAmount * size * 0.5;
    return size * size / (warpedDist * warpedDist + 0.001);
}

void main() {
    vec2 uv = gl_FragCoord.xy / u_resolution;
    vec2 aspect = vec2(u_resolution.x / u_resolution.y, 1.0);
    vec2 uvAspect = uv * aspect;

    vec2 warpedUV = warpUV(uvAspect, u_seed, u_distortion * 0.15);

    float field1 = liquidBlob(warpedUV, u_blob1Pos * aspect, u_blobSize * 0.50, u_seed, u_complexity);
    float field2 = liquidBlob(warpedUV, u_blob2Pos * aspect, u_blobSize * 0.45, u_seed + 10.0, u_complexity);
    float field3 = liquidBlob(warpedUV, u_blob3Pos * aspect, u_blobSize * 0.42, u_seed + 20.0, u_complexity);
    float field4 = liquidBlob(warpedUV, u_blob4Pos * aspect, u_blobSize * 0.38, u_seed + 30.0, u_complexity);
    float field5 = liquidBlob(warpedUV, u_blob5Pos * aspect, u_blobSize * 0.35, u_seed + 40.0, u_complexity);
    float field6 = liquidBlob(warpedUV, u_blob6Pos * aspect, u_blobSize * 0.32, u_seed + 50.0, u_complexity);

    float threshold = 1.0;
    float smoothness = u_blobSoftness * 2.0;

    float totalField = field1 + field2 + field3 + field4 + field5 + field6;

    float w1 = field1 / (totalField + 0.001);
    float w2 = field2 / (totalField + 0.001);
    float w3 = field3 / (totalField + 0.001);
    float w4 = field4 / (totalField + 0.001);
    float w5 = field5 / (totalField + 0.001);
    float w6 = field6 / (totalField + 0.001);

    vec3 blobColor = u_color1 * w1 + u_color2 * w2 + u_color3 * w3 + u_color4 * w4 + u_color5 * w5 + u_color6 * w6;

    float blobPresence = smoothstep(threshold * 0.3 - smoothness, threshold, totalField);

    vec3 color = mix(u_bgColor, blobColor, blobPresence * u_opacity);

    float swirl = fbm(warpedUV * 3.0, u_seed * 2.0, 3) * 0.5 + 0.5;
    color = mix(color, color * (0.9 + swirl * 0.2), blobPresence * 0.3);

    float grain = 0.0;
    grain += snoise(uv * u_grainScale * 100.0 + u_seed) * 0.5;
    grain += snoise(uv * u_grainScale * 200.0 + u_seed * 2.0) * 0.3;
    grain += snoise(uv * u_grainScale * 400.0 + u_seed * 3.0) * 0.2;

    color += grain * u_grainIntensity;
    color = clamp(color, 0.0, 1.0);

    gl_FragColor = vec4(color, 1.0);
}
`;

// Carbon color scheme - sleek dark monochrome gradient
const CARBON_COLORS = {
    color1: '#1c1c1c',
    color2: '#2d2d2d',
    color3: '#3d3d3d',
    color4: '#505050',
    color5: '#262626',
    color6: '#454545',
    bgColor: '#0f0f0f',
};

function hexToRgb(hex: string): [number, number, number] {
    const result = /^#?([a-f\d]{2})([a-f\d]{2})([a-f\d]{2})$/i.exec(hex);
    if (result) {
        return [
            parseInt(result[1], 16) / 255,
            parseInt(result[2], 16) / 255,
            parseInt(result[3], 16) / 255,
        ];
    }
    return [0, 0, 0];
}

/**
 * Generate a deterministic hash from a string
 * Returns a number between 0 and 1
 */
function hashString(str: string): number {
    let hash = 0;
    for (let i = 0; i < str.length; i++) {
        const char = str.charCodeAt(i);
        hash = ((hash << 5) - hash) + char;
        hash = hash & hash; // Convert to 32bit integer
    }
    // Normalize to 0-1 range
    return Math.abs(hash) / 2147483647;
}

/**
 * Generate deterministic blob positions from a string hash
 * Returns 6 blob positions { x, y } based on the input string
 */
function generateBlobPositions(identifier: string): { x: number; y: number }[] {
    const positions: { x: number; y: number }[] = [];

    for (let i = 0; i < 6; i++) {
        // Use different hash seeds for each blob and coordinate
        const xHash = hashString(`${identifier}-blob${i}-x`);
        const yHash = hashString(`${identifier}-blob${i}-y`);

        // Map to different regions of the canvas for visual variety
        // Each blob gets a different quadrant bias
        const regions = [
            { xMin: 0.1, xMax: 0.4, yMin: 0.1, yMax: 0.4 },   // top-left
            { xMin: 0.6, xMax: 0.9, yMin: 0.1, yMax: 0.4 },   // top-right
            { xMin: 0.3, xMax: 0.7, yMin: 0.5, yMax: 0.9 },   // bottom-center
            { xMin: 0.6, xMax: 0.9, yMin: 0.5, yMax: 0.9 },   // bottom-right
            { xMin: 0.2, xMax: 0.5, yMin: 0.3, yMax: 0.7 },   // center-left
            { xMin: 0.5, xMax: 0.8, yMin: 0.2, yMax: 0.6 },   // center-right
        ];

        const region = regions[i];
        positions.push({
            x: region.xMin + xHash * (region.xMax - region.xMin),
            y: region.yMin + yHash * (region.yMax - region.yMin),
        });
    }

    return positions;
}

function createShader(
    gl: WebGLRenderingContext,
    type: number,
    source: string
): WebGLShader | null {
    const shader = gl.createShader(type);
    if (!shader) return null;
    gl.shaderSource(shader, source);
    gl.compileShader(shader);
    if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) {
        console.error('Shader compile error:', gl.getShaderInfoLog(shader));
        gl.deleteShader(shader);
        return null;
    }
    return shader;
}

function createProgram(
    gl: WebGLRenderingContext,
    vertexShader: WebGLShader,
    fragmentShader: WebGLShader
): WebGLProgram | null {
    const program = gl.createProgram();
    if (!program) return null;
    gl.attachShader(program, vertexShader);
    gl.attachShader(program, fragmentShader);
    gl.linkProgram(program);
    if (!gl.getProgramParameter(program, gl.LINK_STATUS)) {
        console.error('Program link error:', gl.getProgramInfoLog(program));
        gl.deleteProgram(program);
        return null;
    }
    return program;
}

// ============================================================================
// Shared WebGL renderer — single context, renders to cached data URLs
// ============================================================================

const gradientCache = new Map<string, string>();

let sharedGL: {
    canvas: HTMLCanvasElement;
    gl: WebGLRenderingContext;
    program: WebGLProgram;
} | null = null;

function getSharedGL(): typeof sharedGL {
    if (sharedGL) return sharedGL;

    const canvas = document.createElement('canvas');
    const gl = canvas.getContext('webgl', { preserveDrawingBuffer: true });
    if (!gl) return null;

    const vertexShader = createShader(gl, gl.VERTEX_SHADER, VERTEX_SHADER);
    const fragmentShader = createShader(gl, gl.FRAGMENT_SHADER, FRAGMENT_SHADER);
    if (!vertexShader || !fragmentShader) return null;

    const program = createProgram(gl, vertexShader, fragmentShader);
    if (!program) return null;

    // Set up geometry (full-screen quad)
    const positionBuffer = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, positionBuffer);
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 1, -1, -1, 1, 1, 1]), gl.STATIC_DRAW);

    const positionLocation = gl.getAttribLocation(program, 'a_position');
    gl.enableVertexAttribArray(positionLocation);
    gl.vertexAttribPointer(positionLocation, 2, gl.FLOAT, false, 0, 0);

    sharedGL = { canvas, gl, program };
    return sharedGL;
}

function renderToDataURL(identifier: string, width: number, height: number): string {
    const cacheKey = `${identifier}-${width}x${height}`;
    const cached = gradientCache.get(cacheKey);
    if (cached) return cached;

    const ctx = getSharedGL();
    if (!ctx) return '';

    const { canvas, gl, program } = ctx;
    canvas.width = width;
    canvas.height = height;

    const seed = hashString(identifier) * 1000;
    const blobPositions = generateBlobPositions(identifier);

    gl.viewport(0, 0, width, height);
    gl.useProgram(program);

    // Set uniforms
    gl.uniform2f(gl.getUniformLocation(program, 'u_resolution'), width, height);
    gl.uniform1f(gl.getUniformLocation(program, 'u_seed'), seed);
    gl.uniform1f(gl.getUniformLocation(program, 'u_grainIntensity'), 0.04);
    gl.uniform1f(gl.getUniformLocation(program, 'u_grainScale'), 2.5);
    gl.uniform1f(gl.getUniformLocation(program, 'u_blobSize'), 2.8);
    gl.uniform1f(gl.getUniformLocation(program, 'u_blobSoftness'), 0.85);
    gl.uniform1f(gl.getUniformLocation(program, 'u_complexity'), 0.4);
    gl.uniform1f(gl.getUniformLocation(program, 'u_distortion'), 0.8);
    gl.uniform1f(gl.getUniformLocation(program, 'u_opacity'), 1.0);

    // Set carbon colors
    const [bgR, bgG, bgB] = hexToRgb(CARBON_COLORS.bgColor);
    gl.uniform3f(gl.getUniformLocation(program, 'u_bgColor'), bgR, bgG, bgB);

    const colorKeys = ['color1', 'color2', 'color3', 'color4', 'color5', 'color6'] as const;
    colorKeys.forEach((key, i) => {
        const [r, g, b] = hexToRgb(CARBON_COLORS[key]);
        gl.uniform3f(gl.getUniformLocation(program, `u_${key}`), r, g, b);
    });

    // Set blob positions
    blobPositions.forEach((pos, i) => {
        gl.uniform2f(gl.getUniformLocation(program, `u_blob${i + 1}Pos`), pos.x, pos.y);
    });

    gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4);

    const dataURL = canvas.toDataURL('image/png');
    gradientCache.set(cacheKey, dataURL);
    return dataURL;
}

// ============================================================================
// React component — renders a cached <img> instead of a live <canvas>
// ============================================================================

interface CarbonGradientProps {
    /** Unique identifier used to generate deterministic blob positions */
    identifier: string;
    /** Width of the canvas */
    width?: number;
    /** Height of the canvas */
    height?: number;
    /** Additional CSS class names */
    className?: string;
}

/**
 * CarbonGradient renders a WebGL gradient thumbnail with carbon colors.
 * Uses a single shared WebGL context to render once per unique identifier,
 * captures the result as a data URL, and displays it as an <img>.
 */
function CarbonGradientComponent({
    identifier,
    width = 320,
    height = 180,
    className = '',
}: CarbonGradientProps) {
    const src = useMemo(() => renderToDataURL(identifier, width, height), [identifier, width, height]);

    return (
        <img
            src={src}
            width={width}
            height={height}
            className={className}
            style={{ backgroundColor: '#0f0f0f' }}
            alt=""
        />
    );
}

// Memoize to prevent unnecessary re-renders
export const CarbonGradient = memo(CarbonGradientComponent);
