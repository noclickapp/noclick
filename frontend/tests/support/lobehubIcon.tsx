// Stands in for every @lobehub/icons icon in unit tests (vitest.config.ts). The real
// ones bring antd with them through antd-style, loaded again for each test file: about
// a third of the suite's time. No test reads the artwork; tsc and the build still
// resolve every icon's own path.
const variant = () => null;
const Icon = Object.assign(variant, {
    Avatar: variant,
    Color: variant,
    Combine: variant,
    Mono: variant,
    Text: variant,
    Brand: variant,
    BrandColor: variant,
    colorPrimary: '#000',
    title: '',
});
export default Icon;
