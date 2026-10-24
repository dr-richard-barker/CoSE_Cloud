// CoSE's browser analysis tools, from the AstroBotany calibration database's registry (src/tools.ts there).
// In M1 they open in a new tab; handing a catalog image to a tool (?open= / ?image=) is the draft's job, and the
// database itself is listed first because it owns image viewing and marker analysis.
export interface ToolLink { id: string; name: string; sub: string; url: string }

export const TOOLS: ToolLink[] = [
  { id: 'astrobotany-db', name: 'AstroBotany calibration database', sub: 'Images, marker scale and colour calibration',
    url: 'https://dr-richard-barker.github.io/AstroBotany_calibration_image_sharing_and_analysis/' },
  { id: 'fiji', name: 'FIJI Bench', sub: 'ImageJ in the browser, SmartRoot, FAIR export', url: 'https://dr-richard-barker.github.io/cose-fiji/' },
  { id: 'astroroot', name: 'AstroRoot', sub: 'Root tracing', url: 'https://dr-richard-barker.github.io/astroroot/' },
  { id: 'leaf-pigment-size', name: 'Leaf Pigment & Size', sub: 'Pigment and leaf area', url: 'https://dr-richard-barker.github.io/Anthocyanin-Image-analysis/' },
  { id: 'germinator-ai', name: 'Germinator AI', sub: 'Seed germination from time-lapse', url: 'https://dr-richard-barker.github.io/germinator-ai/' },
  { id: 'astroroot-painter', name: 'AstroRoot Painter', sub: 'Train a root model (RootPainter)', url: 'https://dr-richard-barker.github.io/astroroot-painter/' },
];
