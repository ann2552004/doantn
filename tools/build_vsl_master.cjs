const fs = require('fs');
const path = require('path');

const ROOT = 'C:\\do an';
const OUT = path.join(ROOT, 'BIEU_DO_VSL_UML_A4_MUI_TEN_CHUAN');
const NODE_MODULES = 'C:\\Users\\pc\\.cache\\codex-runtimes\\codex-primary-runtime\\dependencies\\node\\node_modules';
const sharp = require(path.join(NODE_MODULES, '.pnpm', 'sharp@0.34.5', 'node_modules', 'sharp'));

const groups = {
  usecase: path.join(OUT, 'USE_CASE'),
  sequence: path.join(OUT, 'SEQUENCE'),
  activityA4: path.join(OUT, 'ACTIVITY', 'BAN_A4'),
  activityFull: path.join(OUT, 'ACTIVITY', 'BAN_DAY_DU'),
};

for (const base of Object.values(groups)) {
  fs.mkdirSync(path.join(base, 'EXCALIDRAW'), { recursive: true });
  fs.mkdirSync(path.join(base, 'SVG'), { recursive: true });
  fs.mkdirSync(path.join(base, 'PNG'), { recursive: true });
}
fs.mkdirSync(path.join(OUT, 'CONTACT_SHEET'), { recursive: true });

function walk(dir) {
  if (!fs.existsSync(dir)) return [];
  const out = [];
  for (const ent of fs.readdirSync(dir, { withFileTypes: true })) {
    const p = path.join(dir, ent.name);
    if (ent.isDirectory()) out.push(...walk(p));
    else if (ent.isFile() && ent.name.toLowerCase().endsWith('.excalidraw')) out.push(p);
  }
  return out;
}

function one(dir, re) {
  const p = walk(dir).find((x) => re.test(path.basename(x)));
  if (!p) throw new Error(`Không tìm thấy tệp theo mẫu ${re} trong ${dir}`);
  return p;
}

const src = {
  usecase: [
    one(path.join(ROOT, 'hinh_2_1_usecase_tong_quat_vsl_ban_lon', 'EXCALIDRAW'), /^hinh_2_1_.*\.excalidraw$/i),
    ...[2,3,4,5,6,7,8,9,10,11,12,13].map((n) => one(path.join(ROOT, 'bieu_do_usecase_phan_ra_vsl_ban_lon_cho_bao_cao', 'EXCALIDRAW'), new RegExp(`^hinh_2_${n}_.*\\.excalidraw$`, 'i'))),
  ],
  sequence: [
    ...[16,17,18,19,20,21,22,23,24,25].map((n) => one(path.join(ROOT, 'bieu_do_tuan_tu_vsl_ban_lon_cho_bao_cao', 'EXCALIDRAW'), new RegExp(`^hinh_2_${n}_.*\\.excalidraw$`, 'i'))),
  ],
  activityA4: walk(path.join(ROOT, 'BIEU_DO_HOAT_DONG_A4_DOC_RO', 'EXCALIDRAW')).filter((x) => /^hinh_2_(26|27|28|29|30)[abc]_.*\.excalidraw$/i.test(path.basename(x))).sort(),
  activityFull: [
    ...[26,27,28,29,30].map((n) => one(path.join(ROOT, 'bieu_do_hoat_dong_vsl_ban_doc_ro_trong_bao_cao', 'BAN_DAY_DU', 'EXCALIDRAW'), new RegExp(`^hinh_2_${n}_.*\\.excalidraw$`, 'i'))),
  ],
};

const titleBy = [
  [/^hinh_2_1_/, 'Biểu đồ use case tổng quát hệ thống VSL'],
  [/^hinh_2_2_/, 'Biểu đồ use case phân rã chức năng đăng nhập'],
  [/^hinh_2_3_/, 'Biểu đồ use case phân rã chức năng quản lý camera'],
  [/^hinh_2_4_/, 'Biểu đồ use case phân rã chức năng lựa chọn nguồn video/camera'],
  [/^hinh_2_5_/, 'Biểu đồ use case phân rã chức năng cấu hình ROI và làn đường'],
  [/^hinh_2_6_/, 'Biểu đồ use case phân rã chức năng nhận diện phương tiện'],
  [/^hinh_2_7_/, 'Biểu đồ use case phân rã chức năng theo dõi và đếm phương tiện'],
  [/^hinh_2_8_/, 'Biểu đồ use case phân rã chức năng đo tốc độ phương tiện'],
  [/^hinh_2_9_/, 'Biểu đồ use case phân rã chức năng thiết lập thời tiết và sự cố'],
  [/^hinh_2_10_/, 'Biểu đồ use case phân rã chức năng tính tốc độ VSL'],
  [/^hinh_2_11_/, 'Biểu đồ use case phân rã chức năng gửi lệnh điều khiển biển báo'],
  [/^hinh_2_12_/, 'Biểu đồ use case phân rã chức năng báo cáo và tra cứu lịch sử'],
  [/^hinh_2_13_/, 'Biểu đồ use case phân rã chức năng kiểm thử và đánh giá hệ thống'],
  [/^hinh_2_16_/, 'Biểu đồ tuần tự đăng nhập'],
  [/^hinh_2_17_/, 'Biểu đồ tuần tự chọn video/camera'],
  [/^hinh_2_18_/, 'Biểu đồ tuần tự cấu hình ROI và làn đường'],
  [/^hinh_2_19_/, 'Biểu đồ tuần tự nhận diện, theo dõi và đếm phương tiện'],
  [/^hinh_2_20_/, 'Biểu đồ tuần tự đo tốc độ phương tiện'],
  [/^hinh_2_21_/, 'Biểu đồ tuần tự tính tốc độ VSL tự động'],
  [/^hinh_2_22_/, 'Biểu đồ tuần tự can thiệp VSL thủ công'],
  [/^hinh_2_23_/, 'Biểu đồ tuần tự gửi lệnh điều khiển biển báo qua MQTT'],
  [/^hinh_2_24_/, 'Biểu đồ tuần tự xuất báo cáo và tra cứu lịch sử'],
  [/^hinh_2_25_/, 'Biểu đồ tuần tự xử lý đồng thời nhiều camera'],
  [/^hinh_2_26_/, 'Biểu đồ hoạt động phân tích video và giám sát giao thông'],
  [/^hinh_2_27_/, 'Biểu đồ hoạt động cấu hình ROI và làn đường'],
  [/^hinh_2_28_/, 'Biểu đồ hoạt động đo tốc độ phương tiện'],
  [/^hinh_2_29_/, 'Biểu đồ hoạt động tính tốc độ VSL'],
  [/^hinh_2_30_/, 'Biểu đồ hoạt động xử lý thời tiết và sự cố'],
];
const panelTitleBy = [
  [/^hinh_2_26a_/, 'Biểu đồ hoạt động khởi tạo và xử lý khung hình'],
  [/^hinh_2_26b_/, 'Biểu đồ hoạt động xử lý từng phương tiện'],
  [/^hinh_2_26c_/, 'Biểu đồ hoạt động tổng hợp, tính VSL và kết thúc phiên'],
  [/^hinh_2_27a_/, 'Biểu đồ hoạt động chọn và điều chỉnh thành phần'],
  [/^hinh_2_27b_/, 'Biểu đồ hoạt động kiểm tra, xem trước và lưu cấu hình'],
  [/^hinh_2_28a_/, 'Biểu đồ hoạt động ghi nhận thời điểm qua vạch A/B'],
  [/^hinh_2_28b_/, 'Biểu đồ hoạt động tính toán, kiểm tra và lưu tốc độ'],
  [/^hinh_2_29a_/, 'Biểu đồ hoạt động thu nhận, chuẩn hóa và phân loại dữ liệu'],
  [/^hinh_2_29b_/, 'Biểu đồ hoạt động điều chỉnh VSL theo điều kiện giao thông'],
  [/^hinh_2_29c_/, 'Biểu đồ hoạt động can thiệp thủ công và gửi biển báo'],
  [/^hinh_2_30a_/, 'Biểu đồ hoạt động xác định thời tiết và sự cố'],
  [/^hinh_2_30b_/, 'Biểu đồ hoạt động kết hợp ảnh hưởng và cập nhật VSL'],
];

function baseName(p) { return path.basename(p, '.excalidraw'); }
function titleFor(p) {
  const b = baseName(p);
  const panel = panelTitleBy.find(([re]) => re.test(b));
  if (panel) return panel[1];
  const row = titleBy.find(([re]) => re.test(b));
  if (row) return row[1];
  return b.replace(/^hinh_\d+_/, '').replace(/_/g, ' ');
}
function kindFor(p) {
  const b = baseName(p);
  if (/^hinh_2_(1|2|3|4|5|6|7|8|9|10|11|12|13)_/.test(b)) return 'usecase';
  if (/^hinh_2_(16|17|18|19|20|21|22|23|24|25)_/.test(b)) return 'sequence';
  return 'activity';
}
function svgPathFor(p) {
  const dir = path.dirname(p).replace(/EXCALIDRAW/i, 'SVG');
  const b = baseName(p);
  const same = path.join(dir, b + '.svg');
  if (fs.existsSync(same)) return same;
  const matches = walk(path.dirname(path.dirname(p))).filter((x) => path.basename(x).toLowerCase() === (b + '.svg').toLowerCase());
  return matches[0] || null;
}

function sceneBounds(elements) {
  let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
  for (const e of elements) {
    if (!e || typeof e.x !== 'number' || typeof e.y !== 'number') continue;
    let x1 = e.x, y1 = e.y, x2 = e.x + Math.abs(e.width || 0), y2 = e.y + Math.abs(e.height || 0);
    if (Array.isArray(e.points) && e.points.length) {
      for (const pt of e.points) {
        if (Array.isArray(pt)) {
          x1 = Math.min(x1, e.x + pt[0]); x2 = Math.max(x2, e.x + pt[0]);
          y1 = Math.min(y1, e.y + pt[1]); y2 = Math.max(y2, e.y + pt[1]);
        }
      }
    }
    minX = Math.min(minX, x1); minY = Math.min(minY, y1);
    maxX = Math.max(maxX, x2); maxY = Math.max(maxY, y2);
  }
  if (!Number.isFinite(minX)) return { minX: 0, minY: 0, maxX: 100, maxY: 100, width: 100, height: 100 };
  return { minX, minY, maxX, maxY, width: maxX - minX, height: maxY - minY };
}

function stripFigurePrefix(s) {
  return String(s)
    .replace(/^\s*(?:Hình|Figure)\s*2\.\d+[a-z]?\s*[.:–-]\s*/i, '')
    .replace(/^\s*2\.\d+[a-z]?\s*[.:–-]\s*/i, '')
    .trim();
}

function normalizeScene(scene, p) {
  const kind = kindFor(p);
  const title = titleFor(p);
  const els = Array.isArray(scene.elements) ? scene.elements : [];
  let titleEl = null;
  for (const e of els) {
    if (!e) continue;
    delete e.locked;
    if (e.type === 'text') {
      const old = String(e.text || '');
      const looksTitle = /(?:Hình|Figure)\s*2\.\d+|Biểu đồ/i.test(old) || e.id === 'title' || e.id === 'text-e250965ab3';
      if (looksTitle && !titleEl) {
        titleEl = e;
        e.text = title;
        e.originalText = title;
        e.fontSize = 42;
        e.fontFamily = 2;
        e.fontWeight = 700;
        e.textAlign = 'center';
      } else {
        e.text = stripFigurePrefix(old);
        e.originalText = e.text;
        e.fontFamily = 2;
        const relation = /<<\s*(?:include|extend)\s*>>|\[[^\]]+\]/i.test(e.text);
        const floor = relation ? 24 : (kind === 'activity' ? 30 : (kind === 'sequence' ? 26 : 27));
        e.fontSize = Math.max(Number(e.fontSize) || 0, floor);
        if (relation) e.fontWeight = 700;
      }
    }
    if (['rectangle', 'ellipse', 'diamond', 'line', 'arrow', 'freedraw'].includes(e.type)) {
      const floor = kind === 'activity' ? 3.5 : 2.8;
      e.strokeWidth = Math.max(Number(e.strokeWidth) || 0, floor);
      e.strokeColor = '#111111';
    }
    if (kind === 'activity' && (e.type === 'arrow' || e.type === 'line') && !(String(e.id || '').toLowerCase().includes('lifeline'))) {
      e.endArrowhead = 'triangle';
      e.startArrowhead = null;
      e.strokeStyle = 'solid';
    }
    if (kind === 'sequence' && String(e.id || '').toLowerCase().includes('lifeline')) {
      e.startArrowhead = null; e.endArrowhead = null; e.strokeStyle = 'dashed';
    }
  }
  if (titleEl) {
    const bb = sceneBounds(els);
    titleEl.x = bb.minX + (bb.width - Math.max(titleEl.width || 0, 800)) / 2;
  }
  const bb = sceneBounds(els);
  const margin = 60;
  const dx = margin - bb.minX, dy = margin - bb.minY;
  for (const e of els) {
    if (typeof e.x === 'number') e.x += dx;
    if (typeof e.y === 'number') e.y += dy;
  }
  scene.appState = Object.assign({}, scene.appState || {}, {
    viewBackgroundColor: '#ffffff',
    exportWithDarkMode: false,
    exportBackground: true,
    currentItemFontFamily: 2,
  });
  scene.files = scene.files || {};
  return { scene, bounds: { width: bb.width + margin * 2, height: bb.height + margin * 2 } };
}

function xmlEscape(s) {
  return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

function cleanSvg(raw, title) {
  let svg = String(raw).replace(/<\?xml[^>]*>/g, '');
  const opens = [...svg.matchAll(/<svg\b[^>]*>/g)];
  if (opens.length > 1) svg = svg.slice(opens[1].index);
  const root = svg.match(/<svg\b[^>]*>/);
  if (!root) throw new Error('SVG không có thẻ gốc hợp lệ');
  const view = root[0].match(/viewBox\s*=\s*"([^"]+)"/i);
  const nums = view ? view[1].trim().split(/\s+/).map(Number) : [0, 0, 3400, 2200];
  const cx = nums[0] + nums[2] / 2;
  const firstTitle = [...svg.matchAll(/<text\b[^>]*>[\s\S]*?<\/text>/g)].find((m) => /(?:Hình|Figure|Biểu đồ|Biá»ƒu)/i.test(m[0]));
  const titleXml = `<text x="${cx}" y="68" text-anchor="middle" font-family="Times New Roman, Times, serif" font-size="42px" font-weight="bold" fill="#111111"><tspan x="${cx}" y="68">${xmlEscape(title)}</tspan></text>`;
  if (firstTitle) svg = svg.slice(0, firstTitle.index) + titleXml + svg.slice(firstTitle.index + firstTitle[0].length);
  else svg = svg.replace(root[0], root[0] + titleXml);
  svg = svg.replace(/stroke-width="2\.2"/g, 'stroke-width="2.8"');
  svg = svg.replace(/stroke="#000"/g, 'stroke="#111111"');
  svg = svg.replace(/font-family:\"Times New Roman\",\s*Times,\s*serif/g, "font-family:'Times New Roman', Times, serif");
  return svg;
}

async function makePng(svg, outFile, kind) {
  const target = kind === 'usecase' ? 4200 : (kind === 'sequence' ? 4400 : 3400);
  try {
    await sharp(Buffer.from(svg)).flatten({ background: '#ffffff' }).resize({ width: target }).png().toFile(outFile);
    return true;
  } catch (err) {
    console.error(`PNG fallback cho ${outFile}: ${err.message}`);
    return false;
  }
}

function pathD(e) {
  const pts = Array.isArray(e.points) && e.points.length ? e.points : [[0, 0], [e.width || 0, e.height || 0]];
  return 'M ' + pts.map((pt) => `${(e.x + pt[0]).toFixed(1)},${(e.y + pt[1]).toFixed(1)}`).join(' L ');
}

function setLineGeometry(e, points) {
  e.points = points;
  const xs = points.map((p) => p[0]), ys = points.map((p) => p[1]);
  e.width = Math.max(...xs) - Math.min(...xs);
  e.height = Math.max(...ys) - Math.min(...ys);
}

async function tidyGeneralUseCase() {
  // The previous general-use-case draft used long bus-like routes for the
  // operator and camera associations. Replace only those routes with compact
  // orthogonal paths; all use cases and relationship semantics stay intact.
  const b = 'hinh_2_1_usecase_tong_quat_he_thong_vsl';
  const ex = path.join(groups.usecase, 'EXCALIDRAW', b + '.excalidraw');
  const sv = path.join(groups.usecase, 'SVG', b + '.svg');
  const scene = JSON.parse(fs.readFileSync(ex, 'utf8'));
  const overrides = {
    'operator-login': [[0,0],[45,0],[45,-870],[240,-870]],
    'operator-source': [[0,0],[45,0],[45,-240],[240,-240]],
    'operator-roi': [[0,0],[75,0],[75,-80],[240,-80]],
    'operator-monitor': [[0,0],[45,0],[45,300],[1525,300],[1525,-547]],
    'operator-manual': [[0,0],[60,0],[60,400],[1790,400],[1790,-190]],
    'operator-report': [[0,0],[2040,0],[2040,-40]],
    'video-to-source': [[0,0],[0,85],[-455,85],[-455,1020]],
  };
  const old = {};
  for (const e of scene.elements) {
    if (overrides[e.id]) {
      old[e.id] = pathD(e);
      setLineGeometry(e, overrides[e.id]);
    }
  }
  fs.writeFileSync(ex, JSON.stringify(scene, null, 2), 'utf8');
  let svg = fs.readFileSync(sv, 'utf8');
  for (const e of scene.elements) {
    if (!old[e.id]) continue;
    const replacement = `<path d="${pathD(e)}" fill="none" stroke="#111111" stroke-width="3"/>`;
    const oldTag = `<path d="${old[e.id]}" fill="none" stroke="#111111" stroke-width="3"/>`;
    if (svg.includes(oldTag)) svg = svg.replace(oldTag, replacement);
  }
  fs.writeFileSync(sv, svg, 'utf8');
  await makePng(svg, path.join(groups.usecase, 'PNG', b + '.png'), 'usecase');
}

const results = [];
async function processGroup(groupName, files) {
  const base = groupName === 'usecase' ? groups.usecase : groupName === 'sequence' ? groups.sequence : groupName === 'activityA4' ? groups.activityA4 : groups.activityFull;
  for (const p of files) {
    const b = baseName(p), kind = kindFor(p), title = titleFor(p);
    const scene = JSON.parse(fs.readFileSync(p, 'utf8'));
    const normalized = normalizeScene(scene, p);
    const exOut = path.join(base, 'EXCALIDRAW', b + '.excalidraw');
    fs.writeFileSync(exOut, JSON.stringify(normalized.scene, null, 2), 'utf8');
    const companion = svgPathFor(p);
    let svg;
    if (companion && fs.existsSync(companion)) svg = cleanSvg(fs.readFileSync(companion, 'utf8'), title);
    else throw new Error(`Thiếu SVG đi kèm: ${p}`);
    const svgOut = path.join(base, 'SVG', b + '.svg');
    fs.writeFileSync(svgOut, svg, 'utf8');
    const pngOut = path.join(base, 'PNG', b + '.png');
    const pngOk = await makePng(svg, pngOut, kind);
    results.push({ group: groupName, base: b, title, source: p, svg: svgOut, png: pngOut, pngOk, bounds: normalized.bounds, elementCount: normalized.scene.elements.length });
  }
}

function metadataFromSvg(file) {
  const s = fs.readFileSync(file, 'utf8');
  const m = s.match(/viewBox\s*=\s*"([^"]+)"/i);
  const nums = m ? m[1].trim().split(/\s+/).map(Number) : [0, 0, 0, 0];
  return { width: nums[2] || 0, height: nums[3] || 0, hasNumberInTitle: /<text[^>]*>[^<]*(?:Hình|Figure)\s*2\.\d+/i.test(s) };
}

function reportFiles() {
  const rows = results.map((r) => {
    const s = metadataFromSvg(r.svg);
    const w = Math.round(s.width), h = Math.round(s.height);
    const target = r.group === 'usecase' ? 4200 : r.group === 'sequence' ? 4400 : 3400;
    const minFont = r.group === 'activityA4' ? '30' : r.group === 'sequence' ? '26' : '27';
    return `| ${r.base} | ${r.group} | ${w} × ${h} | ${target} px wide | ${minFont} px | ${s.hasNumberInTitle ? 'FAIL' : 'PASS'} | ${r.pngOk ? 'PASS' : 'FAIL'} |`;
  }).join('\n');
  const missing = ['hinh_2_14', 'hinh_2_15'];
  fs.writeFileSync(path.join(OUT, 'BAO_CAO_KIEM_TRA_UML.md'), `# Báo cáo kiểm tra UML\n\nĐã chuẩn hóa ${results.length} tệp Excalidraw nguồn hiện có theo đúng loại biểu đồ, giữ số thứ tự trong tên tệp và loại bỏ số hình khỏi tiêu đề hiển thị.\n\n## Kiểm tra theo tệp\n\n| Tệp | Nhóm | ViewBox SVG | Chiều rộng PNG | Font nội dung tối thiểu đặt trong scene | Tiêu đề không có số hình | PNG |\n|---|---|---:|---:|---:|---|---|\n${rows}\n\n## Ghi chú phạm vi\n\n- Không tìm thấy tệp Excalidraw Hình 2.14 và Hình 2.15 trong workspace hiện tại; không tự tạo nội dung thay thế.\n- Các tệp hoạt động được xuất cả bản A4 chia panel và bản đầy đủ theo nguồn hiện có.\n`, 'utf8');
  fs.writeFileSync(path.join(OUT, 'BAO_CAO_KIEM_TRA_A4.md'), `# Báo cáo kiểm tra A4\n\n- Nền SVG/PNG: trắng.\n- Tiêu đề: Times New Roman, đậm, 42 px, không ghi số hình.\n- Use case: PNG mục tiêu 4200 px.\n- Sequence: PNG mục tiêu 4400 px.\n- Activity panel: PNG mục tiêu 3400 px.\n- Scene Excalidraw đã xóa trạng thái khóa, tăng cỡ chữ nhỏ và crop bounds với lề 60 px.\n- SVG được giữ dạng vector, chữ là phần tử text và viewBox theo bản SVG nguồn đã crop.\n`, 'utf8');
  fs.writeFileSync(path.join(OUT, 'HUONG_DAN_CHEN_WORD.md'), `# Hướng dẫn chèn vào Word\n\n1. Tạo Section Break trước và sau biểu đồ.\n2. Chuyển trang chứa biểu đồ sang Landscape với lề 1,5 cm.\n3. Chèn tệp SVG trong thư mục tương ứng thay vì chụp màn hình.\n4. Đặt chiều rộng 24,5–25,5 cm cho use case và sequence; với activity panel dọc, đặt chiều rộng 15,5–16 cm hoặc chọn Landscape nếu cần.\n5. Khóa tỷ lệ, căn giữa ảnh và đặt chú thích bằng Insert Caption bên ngoài ảnh.\n6. Không thêm số hình vào bản vẽ; số hình được quản lý bởi Caption của Word.\n`, 'utf8');
}

async function makeContactSheet(name, items, cols = 2) {
  const thumbs = [];
  for (const r of items) {
    const meta = await sharp(r.png).metadata();
    const buf = await sharp(r.png).resize({ width: 820, height: 560, fit: 'inside' }).png().toBuffer();
    const m = await sharp(buf).metadata();
    thumbs.push({ buf, width: m.width, height: m.height, original: meta });
  }
  const cellW = 860, cellH = 610, rows = Math.ceil(thumbs.length / cols);
  const composites = thumbs.map((t, i) => ({ input: t.buf, left: i % cols * cellW + Math.floor((cellW - t.width) / 2), top: Math.floor(i / cols) * cellH + 30 }));
  const out = path.join(OUT, 'CONTACT_SHEET', name + '.png');
  await sharp({ create: { width: cols * cellW, height: rows * cellH, channels: 4, background: '#ffffff' } }).composite(composites).png().toFile(out);
}

(async () => {
  await processGroup('usecase', src.usecase);
  await tidyGeneralUseCase();
  await processGroup('sequence', src.sequence);
  await processGroup('activityA4', src.activityA4);
  await processGroup('activityFull', src.activityFull);
  reportFiles();
  await makeContactSheet('USE_CASE', results.filter((r) => r.group === 'usecase'), 2);
  await makeContactSheet('SEQUENCE', results.filter((r) => r.group === 'sequence'), 2);
  await makeContactSheet('ACTIVITY_A4', results.filter((r) => r.group === 'activityA4'), 2);
  await makeContactSheet('ACTIVITY_FULL', results.filter((r) => r.group === 'activityFull'), 2);
  await makeContactSheet('ALL', results, 2);
  console.log(JSON.stringify({ out: OUT, counts: { usecase: src.usecase.length, sequence: src.sequence.length, activityA4: src.activityA4.length, activityFull: src.activityFull.length }, total: results.length }, null, 2));
})().catch((err) => { console.error(err.stack || err); process.exitCode = 1; });
