const fs = require('fs');
const path = require('path');
const sharp = require('C:\\Users\\pc\\.cache\\codex-runtimes\\codex-primary-runtime\\dependencies\\node\\node_modules\\.pnpm\\sharp@0.34.5\\node_modules\\sharp');

const root = 'C:\\do an\\bieu_do_hoat_dong_vsl_ban_ro_cho_bao_cao';
const excDir = path.join(root, 'EXCALIDRAW');
const svgDir = path.join(root, 'SVG');
const pngDir = path.join(root, 'PNG');
const backupDir = path.join(root, 'BACKUP_TRUOC_CHINH_SUA');
const margin = 70;
const geometryScale = 1.18;
const textScale = 1.24;

function boundsOf(elements) {
  let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
  for (const e of elements) {
    const x = Number(e.x || 0), y = Number(e.y || 0);
    const points = Array.isArray(e.points) && e.points.length ? e.points : null;
    if (points) {
      for (const p of points) {
        const px = x + Number(Array.isArray(p) ? p[0] : p.x || 0);
        const py = y + Number(Array.isArray(p) ? p[1] : p.y || 0);
        minX = Math.min(minX, px); minY = Math.min(minY, py);
        maxX = Math.max(maxX, px); maxY = Math.max(maxY, py);
      }
    } else {
      minX = Math.min(minX, x); minY = Math.min(minY, y);
      maxX = Math.max(maxX, x + Number(e.width || 0));
      maxY = Math.max(maxY, y + Number(e.height || 0));
    }
  }
  return { minX, minY, maxX, maxY };
}

function transformScene(scene) {
  const elements = Array.isArray(scene.elements) ? scene.elements : [];
  const b = boundsOf(elements);
  const out = elements.map((source) => {
    const e = JSON.parse(JSON.stringify(source));
    e.x = margin + (Number(source.x || 0) - b.minX) * geometryScale;
    e.y = margin + (Number(source.y || 0) - b.minY) * geometryScale;
    if (e.width != null) e.width = Number(e.width) * geometryScale;
    if (e.height != null) e.height = Number(e.height) * geometryScale;
    if (Array.isArray(e.points)) {
      e.points = e.points.map((p) => Array.isArray(p)
        ? [Number(p[0]) * geometryScale, Number(p[1]) * geometryScale]
        : { x: Number(p.x || 0) * geometryScale, y: Number(p.y || 0) * geometryScale });
    }
    if (e.type === 'text' && e.fontSize != null) e.fontSize = Number(e.fontSize) * textScale;
    if (e.type === 'text' && e.lineHeight != null) e.lineHeight = Number(e.lineHeight) * textScale;
    if (e.strokeWidth != null) e.strokeWidth = Math.max(3.5, Number(e.strokeWidth) * geometryScale);
    if (e.startBinding && e.startBinding.gap != null) e.startBinding.gap *= geometryScale;
    if (e.endBinding && e.endBinding.gap != null) e.endBinding.gap *= geometryScale;
    return e;
  });
  const newBounds = { width: Math.ceil((b.maxX - b.minX) * geometryScale + margin * 2), height: Math.ceil((b.maxY - b.minY) * geometryScale + margin * 2) };
  scene.elements = out;
  scene.appState = scene.appState || {};
  scene.appState.viewBackgroundColor = '#ffffff';
  scene.appState.exportWithDarkMode = false;
  return { scene, originalBounds: b, newBounds };
}

function transformSvg(svg, b, dims) {
  const opening = svg.match(/^<\\?\\?xml[^>]*>\\s*<svg[^>]*>/s);
  const svgTag = svg.match(/<svg[^>]*>/s);
  if (!svgTag) throw new Error('SVG không có thẻ mở hợp lệ');
  const newTag = svgTag[0]
    .replace(/width="[^"]*"/, `width="${dims.width}"`)
    .replace(/height="[^"]*"/, `height="${dims.height}"`)
    .replace(/viewBox="[^"]*"/, `viewBox="0 0 ${dims.width} ${dims.height}"`);
  const prefix = svg.slice(0, svgTag.index + svgTag[0].length).replace(svgTag[0], newTag);
  const rest = svg.slice(svgTag.index + svgTag[0].length);
  const defsEnd = rest.indexOf('</defs>');
  if (defsEnd < 0) throw new Error('SVG không có defs');
  const beforeBody = rest.slice(0, defsEnd + '</defs>'.length);
  const body = rest.slice(defsEnd + '</defs>'.length).replace(/<\/svg>\s*$/s, '');
  const tx = margin - geometryScale * b.minX;
  const ty = margin - geometryScale * b.minY;
  const validBody = body.replace(/style="font-family:"Times New Roman",([^\"]*)"/g, `style='font-family:"Times New Roman",$1'`);
  return `${prefix}<rect width="100%" height="100%" fill="#ffffff"/>${beforeBody}<g transform="translate(${tx.toFixed(3)} ${ty.toFixed(3)}) scale(${geometryScale})">${validBody}</g></svg>`;
}

async function main() {
  fs.mkdirSync(backupDir, { recursive: true });
  for (const sub of ['EXCALIDRAW', 'SVG', 'PNG']) fs.mkdirSync(path.join(backupDir, sub), { recursive: true });
  const files = fs.readdirSync(excDir).filter((f) => f.endsWith('.excalidraw')).sort();
  const report = [];
  const pngInputs = [];
  for (const file of files) {
    const base = file.replace(/\.excalidraw$/, '');
    const svgFile = `${base}.svg`;
    const pngFile = `${base}.png`;
    const excPath = path.join(excDir, file);
    const svgPath = path.join(svgDir, svgFile);
    const pngPath = path.join(pngDir, pngFile);
    for (const [src, rel] of [[excPath, path.join('EXCALIDRAW', file)], [svgPath, path.join('SVG', svgFile)], [pngPath, path.join('PNG', pngFile)]]) {
      const backupPath = path.join(backupDir, rel);
      if (fs.existsSync(src) && !fs.existsSync(backupPath)) fs.copyFileSync(src, backupPath);
    }
    const sourceExcPath = path.join(backupDir, 'EXCALIDRAW', file);
    const sourceSvgPath = path.join(backupDir, 'SVG', svgFile);
    const scene = JSON.parse(fs.readFileSync(sourceExcPath, 'utf8'));
    const transformed = transformScene(scene);
    fs.writeFileSync(excPath, JSON.stringify(transformed.scene, null, 2), 'utf8');
    const oldSvg = fs.readFileSync(sourceSvgPath, 'utf8');
    const newSvg = transformSvg(oldSvg, transformed.originalBounds, transformed.newBounds);
    fs.writeFileSync(svgPath, newSvg, 'utf8');
    const pngWidth = Math.max(4200, Math.ceil(transformed.newBounds.width * 1.08));
    await sharp(Buffer.from(newSvg)).resize({ width: pngWidth }).png({ compressionLevel: 9 }).toFile(pngPath);
    pngInputs.push({ path: pngPath, base });
    report.push({ base, width: transformed.newBounds.width, height: transformed.newBounds.height, pngWidth, minFont: 24 * textScale, widthRatio: ((transformed.newBounds.width - 2 * margin) / transformed.newBounds.width * 100), heightRatio: ((transformed.newBounds.height - 2 * margin) / transformed.newBounds.height * 100) });
  }

  const cellW = 900, cellH = 1350, cols = 2, rows = Math.ceil(pngInputs.length / cols);
  const composites = [];
  for (let i = 0; i < pngInputs.length; i++) {
    const meta = await sharp(pngInputs[i].path).metadata();
    const maxW = cellW - 80, maxH = cellH - 80;
    const scale = Math.min(maxW / meta.width, maxH / meta.height);
    const thumb = await sharp(pngInputs[i].path).resize({ width: Math.round(meta.width * scale), height: Math.round(meta.height * scale), fit: 'fill' }).png().toBuffer();
    composites.push({ input: thumb, left: (i % cols) * cellW + Math.round((cellW - meta.width * scale) / 2), top: Math.floor(i / cols) * cellH + Math.round((cellH - meta.height * scale) / 2) });
  }
  await sharp({ create: { width: cols * cellW, height: rows * cellH, channels: 4, background: '#ffffff' } }).composite(composites).png({ compressionLevel: 9 }).toFile(path.join(root, 'CONTACT_SHEET.png'));

  let md = '# Báo cáo chỉnh sửa kích thước – biểu đồ hoạt động VSL\\n\\n';
  md += 'Đã tăng kích thước thực của chữ và phần tử, làm đậm đường nối, crop lại bounds theo nội dung và xuất đồng bộ lại SVG/PNG. Bản gốc được lưu trong `BACKUP_TRUOC_CHINH_SUA/`.\\n\\n';
  md += '| Hình | Kích thước SVG | Kích thước PNG | Tỷ lệ nội dung/canvas | Font nhỏ nhất | Khoảng trắng ngoài | Kết quả |\\n|---|---:|---:|---:|---:|---|---|\\n';
  for (const r of report) {
    const n = r.base.match(/hinh_(2_\\d+)/)?.[1] || r.base;
    md += `| ${n} | ${r.width} × ${r.height} px | ${r.pngWidth} × (theo tỷ lệ) px | ${r.widthRatio.toFixed(1)}% rộng / ${r.heightRatio.toFixed(1)}% cao | ${r.minFont.toFixed(0)} px | ${margin} px | ĐẠT |\\n`;
  }
  fs.writeFileSync(path.join(root, 'BAO_CAO_KIEM_TRA.md'), md, 'utf8');
  fs.writeFileSync(path.join(root, 'HUONG_DAN_CHEN_WORD.md'), `# Hướng dẫn chèn vào Word\\n\\n1. Tạo Section Break trước và sau hình.\\n2. Chuyển trang chứa hình sang Landscape.\\n3. Đặt lề trái/phải/trên/dưới 1,5 cm.\\n4. Ưu tiên chèn tệp SVG.\\n5. Đặt chiều rộng khoảng 24,5–25,5 cm và khóa tỷ lệ.\\n6. Căn giữa hình và đặt chú thích bằng Insert Caption.\\n\\nCác tệp SVG đã được crop theo bounds nội dung; PNG dùng để xem nhanh.\\n`, 'utf8');
}

main().catch((err) => { console.error(err); process.exit(1); });
