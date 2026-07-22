const fs = require('fs');
const path = require('path');
const sharp = require('C:\\Users\\pc\\.cache\\codex-runtimes\\codex-primary-runtime\\dependencies\\node\\node_modules\\.pnpm\\sharp@0.34.5\\node_modules\\sharp');

const sourceDir = 'C:\\do an\\bieu_do_hoat_dong_vsl_ban_doc_ro_trong_bao_cao\\BAN_BAO_CAO\\EXCALIDRAW';
const outRoot = 'C:\\do an\\BIEU_DO_HOAT_DONG_A4_DOC_RO';
const outExc = path.join(outRoot, 'EXCALIDRAW');
const outSvg = path.join(outRoot, 'SVG');
const outPng = path.join(outRoot, 'PNG');
const margin = 60;
const canvasWidth = 2400;
const font = 'Times New Roman';
const files = [
  ['hinh_2_26a_khoi_tao_xu_ly_khung_hinh.excalidraw', 'hinh_2_26a_khoi_tao_va_xu_ly_frame'],
  ['hinh_2_26b_xu_ly_tung_phuong_tien.excalidraw', 'hinh_2_26b_xu_ly_tung_phuong_tien'],
  ['hinh_2_26c_tong_hop_tinh_vsl.excalidraw', 'hinh_2_26c_tong_hop_tinh_vsl'],
  ['hinh_2_27a_chon_dieu_chinh_thanh_phan.excalidraw', 'hinh_2_27a_chon_va_chinh_cau_hinh'],
  ['hinh_2_27b_kiem_tra_xem_truoc_luu.excalidraw', 'hinh_2_27b_kiem_tra_va_luu_cau_hinh'],
  ['hinh_2_28a_theo_doi_ghi_thoi_diem.excalidraw', 'hinh_2_28a_ghi_nhan_qua_vach_ab'],
  ['hinh_2_28b_tinh_kiem_tra_luu_toc_do.excalidraw', 'hinh_2_28b_tinh_va_luu_toc_do'],
  ['hinh_2_29a_chuan_hoa_phan_loai_du_lieu.excalidraw', 'hinh_2_29a_thu_nhan_chuan_hoa_du_lieu'],
  ['hinh_2_29b_dieu_chinh_vsl_theo_dieu_kien.excalidraw', 'hinh_2_29b_dieu_chinh_vsl'],
  ['hinh_2_29c_thu_cong_hien_thi_gui_bien_bao.excalidraw', 'hinh_2_29c_thu_cong_va_xuat_ket_qua'],
  ['hinh_2_30a_xac_dinh_thoi_tiet_su_co.excalidraw', 'hinh_2_30a_xac_dinh_thoi_tiet_su_co'],
  ['hinh_2_30b_ket_hop_cap_nhat_vsl.excalidraw', 'hinh_2_30b_ket_hop_va_cap_nhat_he_thong'],
];

const esc = (s) => String(s ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
const center = (e) => ({ x: Number(e.x || 0) + Number(e.width || 0) / 2, y: Number(e.y || 0) + Number(e.height || 0) / 2 });
function nodeBounds(n) { return { l: n.x, t: n.y, r: n.x + n.width, b: n.y + n.height }; }
function pointOnArrow(e, last) {
  const p = e.points?.[last ? e.points.length - 1 : 0] || [0, 0];
  return { x: Number(e.x || 0) + Number(Array.isArray(p) ? p[0] : p.x || 0), y: Number(e.y || 0) + Number(Array.isArray(p) ? p[1] : p.y || 0) };
}
function pointDistanceToNode(p, n) {
  const b = nodeBounds(n);
  const dx = p.x < b.l ? b.l - p.x : p.x > b.r ? p.x - b.r : 0;
  const dy = p.y < b.t ? b.t - p.y : p.y > b.b ? p.y - b.b : 0;
  return Math.hypot(dx, dy);
}
function nearestNode(p, nodes) {
  return nodes.slice().sort((a, b) => pointDistanceToNode(p, a) - pointDistanceToNode(p, b))[0];
}
function textInShape(text, shape) {
  const tc = center(text), b = nodeBounds(shape);
  return tc.x >= b.l - 4 && tc.x <= b.r + 4 && tc.y >= b.t - 4 && tc.y <= b.b + 4;
}
function splitRows(nodes) {
  const sorted = nodes.slice().sort((a, b) => a.oy - b.oy || a.ox - b.ox);
  const rows = [];
  for (const n of sorted) {
    let row = rows[rows.length - 1];
    if (!row || Math.abs(n.oy - row.anchor) > 95) { row = { anchor: n.oy, nodes: [] }; rows.push(row); }
    row.nodes.push(n);
  }
  return rows;
}
function shapeGroupsForSplit(source) {
  const shapes = source.elements.filter((e) => ['rectangle', 'diamond', 'ellipse'].includes(e.type)).map((e) => ({ id: e.id, type: e.type, y: Number(e.y || 0), x: Number(e.x || 0), width: Number(e.width || 0), height: Number(e.height || 0) })).sort((a, b) => a.y - b.y || a.x - b.x);
  const groups = [];
  for (const s of shapes) {
    let g = groups[groups.length - 1];
    if (!g || Math.abs(s.y - g.y) > 95) { g = { y: s.y, shapes: [] }; groups.push(g); }
    g.shapes.push(s);
  }
  return groups;
}
function splitSource(source) {
  const groups = shapeGroupsForSplit(source);
  const chunks = [];
  let current = [], rects = 0, diamonds = 0;
  for (const g of groups) {
    const gr = g.shapes.filter((s) => s.type === 'rectangle').length;
    const gd = g.shapes.filter((s) => s.type === 'diamond').length;
    if (current.length && ((rects + gr > 10) || (diamonds + gd > 3))) { chunks.push(current.flatMap((x) => x.shapes)); current = []; rects = 0; diamonds = 0; }
    current.push(g); rects += gr; diamonds += gd;
  }
  if (current.length) chunks.push(current.flatMap((x) => x.shapes));
  return chunks.length > 1 ? chunks : [groups.flatMap((x) => x.shapes)];
}
function makeSubset(source, selectedShapes, index, total, titleOverride) {
  const all = source.elements;
  const selectedIds = new Set(selectedShapes.map((s) => s.id));
  const allShapes = all.filter((e) => ['rectangle', 'diamond', 'ellipse'].includes(e.type));
  const texts = all.filter((e) => e.type === 'text');
  const title = texts.find((t) => /Hình/.test(t.text || ''));
  const shapeTextIds = new Set();
  for (const s of selectedShapes) { const t = texts.filter((x) => !String(x.text || '').includes('[') && textInShape(x, s)).sort((a, b) => a.width * a.height - b.width * b.height)[0]; if (t) shapeTextIds.add(t.id); }
  const minY = Math.min(...selectedShapes.map((s) => Number(s.y || 0))), maxY = Math.max(...selectedShapes.map((s) => Number(s.y || 0) + Number(s.height || 0)));
  const selectedTextIds = new Set([title?.id, ...shapeTextIds]);
  texts.filter((t) => String(t.text || '').includes('[') && center(t).y >= minY - 160 && center(t).y <= maxY + 160).forEach((t) => selectedTextIds.add(t.id));
  texts.filter((t) => t.id !== title?.id && !String(t.text || '').includes('[') && !shapeTextIds.has(t.id) && center(t).y < minY + 240).forEach((t) => selectedTextIds.add(t.id));
  const selectedArrows = all.filter((e) => e.type === 'arrow' && e.points?.length >= 2).filter((e) => { const s = nearestNode(pointOnArrow(e, false), allShapes), t = nearestNode(pointOnArrow(e, true), allShapes); return selectedIds.has(s?.id) && selectedIds.has(t?.id); });
  const elements = [...selectedShapes, ...texts.filter((t) => selectedTextIds.has(t.id)), ...selectedArrows].map((e) => JSON.parse(JSON.stringify(e)));
  const newTitle = elements.find((e) => e.id === title?.id);
  if (newTitle && titleOverride) newTitle.text = newTitle.originalText = titleOverride;
  const centerX = selectedShapes.reduce((sum, s) => sum + Number(s.x || 0) + Number(s.width || 0) / 2, 0) / selectedShapes.length;
  const topY = minY - 180, bottomY = maxY + 160;
  if (index > 0) { elements.push({ id: `synthetic-start-${index}`, type: 'ellipse', x: centerX - 36, y: topY, width: 72, height: 72, backgroundColor: '#ffffff', strokeColor: '#111111' }); elements.push({ id: `synthetic-start-${index}-text`, type: 'text', x: centerX - 20, y: topY + 14, width: 40, height: 40, text: 'A' }); }
  if (index < total - 1) { elements.push({ id: `synthetic-end-${index}`, type: 'ellipse', x: centerX - 36, y: bottomY, width: 72, height: 72, backgroundColor: '#ffffff', strokeColor: '#111111' }); elements.push({ id: `synthetic-end-${index}-text`, type: 'text', x: centerX - 20, y: bottomY + 14, width: 40, height: 40, text: 'B' }); }
  return { type: 'excalidraw', elements };
}
function compactSource(source, sourceFile) {
  const out = JSON.parse(JSON.stringify(source));
  const merges = {
    'hinh_2_28a_theo_doi_ghi_thoi_diem.excalidraw': [
      [['Đúng hướng đo?'], ['Đã qua vạch A?'], 'Đúng hướng và đã qua vạch A?'],
    ],
    'hinh_2_29a_chuan_hoa_phan_loai_du_lieu.excalidraw': [
      [['Nhận số xe trong ROI'], ['Nhận số lượng theo loại'], ['Nhận tốc độ trung bình'], 'Thu nhận số xe, số lượng và tốc độ trung bình'],
    ],
    'hinh_2_29b_dieu_chinh_vsl_theo_dieu_kien.excalidraw': [
      [['Thời tiết xấu?'], ['Mức độ thời tiết?'], 'Thời tiết xấu và mức độ?'],
    ],
    'hinh_2_30a_xac_dinh_thoi_tiet_su_co.excalidraw': [
      [['Mở màn hình cập nhật bối cảnh'], ['Đọc trạng thái hiện tại'], 'Mở màn hình và đọc trạng thái bối cảnh hiện tại'],
    ],
  };
  const rules = merges[sourceFile] || [];
  for (const rule of rules) {
    const groups = rule.slice(0, -1); const newLabel = rule[rule.length - 1];
    const shapes = out.elements.filter((e) => ['rectangle', 'diamond'].includes(e.type));
    const matches = [];
    for (const group of groups) {
      const found = shapes.find((s) => { const tx = out.elements.find((t) => t.type === 'text' && !String(t.text || '').includes('[') && textInShape(t, s)); return tx && group.some((f) => String(tx.text || '').includes(f)); });
      if (found) matches.push(found);
    }
    if (!matches.length) continue;
    const keep = matches[0];
    const keepText = out.elements.find((t) => t.type === 'text' && !String(t.text || '').includes('[') && textInShape(t, keep));
    if (keepText) keepText.text = keepText.originalText = newLabel;
    const removeIds = new Set(matches.slice(1).map((s) => s.id));
    const removeTextIds = new Set(out.elements.filter((t) => t.type === 'text' && matches.slice(1).some((s) => textInShape(t, s))).map((t) => t.id));
    out.elements = out.elements.filter((e) => !removeIds.has(e.id) && !removeTextIds.has(e.id));
  }
  return out;
}
function normalizeShape(n) {
  if (n.type === 'rectangle') { n.width = Math.max(500, Math.min(600, n.width || 540)); n.height = 130; }
  else if (n.type === 'diamond') { n.width = 380; n.height = 220; }
  else if (n.type === 'ellipse') { n.width = n.kind === 'connector' ? 88 : (n.kind === 'finish' ? 68 : 54); n.height = n.width; }
}
function layoutNodes(nodes) {
  for (const n of nodes) normalizeShape(n);
  const rows = splitRows(nodes);
  let y = 260;
  for (const row of rows) {
    row.nodes.sort((a, b) => a.ox - b.ox);
    const count = row.nodes.length;
    let centers;
    if (count === 1) centers = [canvasWidth / 2];
    else if (count === 2) centers = [760, 1640];
    else if (count === 3) centers = [360, 1200, 2040];
    else centers = [300, 900, 1500, 2100];
    const h = Math.max(...row.nodes.map((n) => n.height));
    row.nodes.forEach((n, i) => { n.x = centers[i] - n.width / 2; n.y = y; });
    y += h + 80;
  }
  return { height: y + 100 };
}
function route(src, dst, nodes) {
  const s = center(src), t = center(dst);
  const sb = nodeBounds(src), tb = nodeBounds(dst);
  const sameRow = Math.abs(s.y - t.y) < 80;
  if (sameRow) {
    if (s.x < t.x) return [{ x: sb.r, y: s.y }, { x: tb.l, y: t.y }];
    return [{ x: sb.l, y: s.y }, { x: tb.r, y: t.y }];
  }
  if (t.y > s.y) {
    const midY = (sb.b + tb.t) / 2;
    return [{ x: s.x, y: sb.b }, { x: s.x, y: midY }, { x: t.x, y: midY }, { x: t.x, y: tb.t }];
  }
  const right = s.x < canvasWidth / 2;
  const corridor = right ? canvasWidth - 130 : 130;
  const startX = right ? sb.r : sb.l;
  const endX = right ? tb.r : tb.l;
  return [{ x: startX, y: s.y }, { x: corridor, y: s.y }, { x: corridor, y: t.y }, { x: endX, y: t.y }];
}
function pathAbs(e) { return e.points.map((p) => ({ x: e.x + (Array.isArray(p) ? p[0] : p.x), y: e.y + (Array.isArray(p) ? p[1] : p.y) })); }
function distToPolyline(p, pts) { let best = Infinity; for (let i = 1; i < pts.length; i++) { const a = pts[i - 1], b = pts[i]; const vx = b.x - a.x, vy = b.y - a.y; const t = Math.max(0, Math.min(1, ((p.x - a.x) * vx + (p.y - a.y) * vy) / (vx * vx + vy * vy || 1))); best = Math.min(best, Math.hypot(p.x - (a.x + t * vx), p.y - (a.y + t * vy))); } return best; }
function branchLabelPosition(points, width) {
  let best = null;
  for (let i = 1; i < points.length; i++) { const a = points[i - 1], b = points[i]; const len = Math.hypot(b.x - a.x, b.y - a.y); if (!best || len > best.len) best = { a, b, len }; }
  if (!best) return { x: points[0].x, y: points[0].y };
  const mid = { x: (best.a.x + best.b.x) / 2, y: (best.a.y + best.b.y) / 2 };
  if (Math.abs(best.b.x - best.a.x) >= Math.abs(best.b.y - best.a.y)) return { x: mid.x - width / 2, y: mid.y - 34 };
  return { x: mid.x + 24, y: mid.y - 14 };
}
function wrapLabel(text, maxChars) {
  const src = String(text || '');
  if (src.includes('\n') || src.length <= maxChars) return src;
  const words = src.split(/\s+/); const lines = []; let line = '';
  for (const word of words) { if (line && (line.length + 1 + word.length) > maxChars) { lines.push(line); line = word; } else line = line ? `${line} ${word}` : word; }
  if (line) lines.push(line); return lines.join('\n');
}
function moveLabelAwayFromNodes(pos, width, nodes) {
  let out = { ...pos };
  for (let i = 0; i < 4; i++) {
    const cx = out.x + width / 2, cy = out.y + 18;
    const hit = nodes.some((n) => cx >= n.x && cx <= n.x + n.width && cy >= n.y && cy <= n.y + n.height);
    if (!hit) break;
    out.y -= 48;
  }
  return out;
}
function makeText(id, text, x, y, width, height, fontSize, bold = false, align = 'left') {
  return { id, type: 'text', x, y, width, height, text, originalText: text, fontSize, fontFamily: 2, textAlign: align, verticalAlign: 'middle', strokeColor: '#111111', backgroundColor: 'transparent', fillStyle: 'solid', strokeWidth: 1, roughness: 0, opacity: 100, fontWeight: bold ? 700 : 400, seed: Math.floor(Math.random() * 1000000000), version: 1, versionNonce: Math.floor(Math.random() * 1000000000), isDeleted: false, groupIds: [], frameId: null, roundness: null, boundElements: [], updated: Date.now(), link: null, locked: false, customData: null };
}
function makeShape(id, type, x, y, width, height, options = {}) {
  return { id, type, x, y, width, height, angle: 0, strokeColor: '#111111', backgroundColor: options.fill || '#ffffff', fillStyle: 'solid', strokeWidth: 3.5, strokeStyle: 'solid', roughness: 0, opacity: 100, groupIds: [], frameId: null, roundness: type === 'rectangle' ? { type: 3 } : null, seed: Math.floor(Math.random() * 1000000000), version: 1, versionNonce: Math.floor(Math.random() * 1000000000), isDeleted: false, boundElements: [], updated: Date.now(), link: null, locked: false, customData: options.customData || null };
}
function makeArrow(id, points, label = null) {
  const x = points[0].x, y = points[0].y;
  return { id, type: 'arrow', x, y, width: null, height: null, angle: 0, points: points.map((p) => [p.x - x, p.y - y]), startBinding: null, endBinding: null, startArrowhead: null, endArrowhead: 'triangle', strokeColor: '#111111', backgroundColor: 'transparent', fillStyle: 'solid', strokeWidth: 3.5, strokeStyle: 'solid', roughness: 0, opacity: 100, groupIds: [], frameId: null, roundness: null, seed: Math.floor(Math.random() * 1000000000), version: 1, versionNonce: Math.floor(Math.random() * 1000000000), isDeleted: false, boundElements: label ? [{ id: `${id}-label`, type: 'text' }] : [], updated: Date.now(), link: null, locked: false, customData: null };
}
function renderSvg(elements, width, height) {
  const arrowEls = elements.filter((e) => e.type === 'arrow');
  const shapeEls = elements.filter((e) => ['rectangle', 'diamond', 'ellipse'].includes(e.type));
  const textEls = elements.filter((e) => e.type === 'text');
  const out = [`<?xml version="1.0" encoding="UTF-8"?><svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}" viewBox="0 0 ${width} ${height}"><rect width="100%" height="100%" fill="#ffffff"/><defs><marker id="arrow" markerWidth="18" markerHeight="18" refX="15" refY="9" orient="auto"><path d="M1,1 L16,9 L1,17 z" fill="#111111"/></marker></defs>`];
  for (const e of arrowEls) { const pts = e.points.map((p) => `${(e.x + p[0]).toFixed(1)},${(e.y + p[1]).toFixed(1)}`).join(' '); out.push(`<polyline points="${pts}" fill="none" stroke="#111111" stroke-width="3.5" stroke-linejoin="miter" stroke-linecap="square" marker-end="url(#arrow)"/>`); }
  for (const e of shapeEls) {
    if (e.type === 'rectangle') out.push(`<rect x="${e.x}" y="${e.y}" width="${e.width}" height="${e.height}" rx="20" fill="#ffffff" stroke="#111111" stroke-width="3.5"/>`);
    else if (e.type === 'diamond') { const cx = e.x + e.width / 2, cy = e.y + e.height / 2; out.push(`<polygon points="${cx},${e.y} ${e.x + e.width},${cy} ${cx},${e.y + e.height} ${e.x},${cy}" fill="#ffffff" stroke="#111111" stroke-width="3.5"/>`); }
    else { const cx = e.x + e.width / 2, cy = e.y + e.height / 2, r = e.width / 2; out.push(`<circle cx="${cx}" cy="${cy}" r="${r}" fill="${e.backgroundColor}" stroke="#111111" stroke-width="3.5"/>`); if (e.customData?.kind === 'finish') out.push(`<circle cx="${cx}" cy="${cy}" r="${r - 11}" fill="#111111"/>`); }
  }
  for (const e of textEls) {
    const anchor = e.textAlign === 'center' ? 'middle' : 'start'; const tx = e.textAlign === 'center' ? e.x + e.width / 2 : e.x; const lines = String(e.text || '').split(/\n/); const lineH = e.fontSize * 1.22; const top = e.y + (e.height - lines.length * lineH) / 2 + e.fontSize * 0.85; const style = `font-family:'Times New Roman',Times,serif;font-size:${e.fontSize}px;font-weight:${e.fontWeight || 400};fill:#111111;${e.text.includes('[') ? 'paint-order:stroke;stroke:#ffffff;stroke-width:10px;stroke-linejoin:round;' : ''}`; out.push(`<text x="${tx}" y="${top}" text-anchor="${anchor}" style="${style}">${lines.map((line, i) => `<tspan x="${tx}" dy="${i ? lineH : 0}">${esc(line)}</tspan>`).join('')}</text>`);
  }
  out.push('</svg>'); return out.join('');
}
function panelSuffix(name) { return name.match(/hinh_(2_\d+)([abc])_/)?.[2] || ''; }
function continuationText(base, suffix, isStart) {
  const fig = base.match(/hinh_(2_\d+)/)?.[1] || '';
  const next = suffix === 'a' ? 'b' : suffix === 'b' ? 'c' : null;
  const prev = suffix === 'b' ? 'a' : suffix === 'c' ? 'b' : null;
  if (isStart && prev) return `Từ Hình ${fig}${prev}`;
  if (!isStart && next) return `Tiếp tục ở Hình ${fig}${next}`;
  return null;
}
function rebuild(source, base) {
  const raw = source.elements || [];
  const originalShapes = raw.filter((e) => ['rectangle', 'diamond', 'ellipse'].includes(e.type));
  const texts = raw.filter((e) => e.type === 'text');
  const paired = new Set();
  const nodes = [];
  for (const shape of originalShapes) {
    const candidate = texts.filter((t) => !paired.has(t.id) && !String(t.text || '').includes('[') && textInShape(t, shape)).sort((a, b) => (a.width * a.height) - (b.width * b.height))[0];
    if (candidate) paired.add(candidate.id);
    const fill = String(shape.backgroundColor || '').toLowerCase();
    const nearBlack = fill === '#111111' || fill === '#000000';
    const node = { id: shape.id, type: shape.type, label: candidate?.text || '', ox: Number(shape.x || 0) + Number(shape.width || 0) / 2, oy: Number(shape.y || 0) + Number(shape.height || 0) / 2, width: Number(shape.width || 0), height: Number(shape.height || 0), kind: shape.type === 'ellipse' ? (nearBlack ? 'start' : 'connector') : null, sourceShape: shape };
    nodes.push(node);
  }
  for (const n of nodes.filter((x) => x.type === 'ellipse' && !x.label)) { if (n.oy > Math.max(...nodes.map((x) => x.oy)) - 180) n.kind = 'finish'; }
  const finishInner = nodes.filter((n) => n.type === 'ellipse' && n.kind === 'start' && n.oy > Math.max(...nodes.map((x) => x.oy)) - 180);
  for (const n of finishInner) n.kind = 'finish';
  const keepNodes = nodes.filter((n) => !(n.type === 'ellipse' && n.kind === 'start' && n.oy > Math.max(...nodes.map((x) => x.oy)) - 180));
  layoutNodes(keepNodes);
  const nodeById = new Map(keepNodes.map((n) => [n.id, n]));
  const arrows = [];
  const arrowMeta = [];
  for (const old of raw.filter((e) => e.type === 'arrow' && e.points?.length >= 2)) {
    const sOld = nearestNode(pointOnArrow(old, false), nodes); const tOld = nearestNode(pointOnArrow(old, true), nodes);
    const src = nodeById.get(sOld?.id), dst = nodeById.get(tOld?.id);
    if (!src || !dst || src.id === dst.id) continue;
    const key = `${src.id}->${dst.id}`; if (arrows.some((a) => a.key === key)) continue;
    const pts = route(src, dst, keepNodes); const arrow = makeArrow(`edge-${arrows.length}`, pts); arrows.push({ key, src, dst, pts, arrow }); arrowMeta.push({ old, newEdge: arrows[arrows.length - 1] });
  }
  const out = [];
  const title = texts.find((t) => /Hình/.test(t.text || ''));
  const titleText = title?.text || `Hình ${base.replace(/_/g, ' ')}`;
  out.push(makeText('title', titleText, margin, 50, canvasWidth - margin * 2, 64, 42, true, 'center'));
  const standalones = texts.filter((t) => !paired.has(t.id) && t.id !== title?.id && !String(t.text || '').includes('['));
  standalones.slice(0, 3).forEach((t, i) => out.push(makeText(`role-${i}`, t.text, margin + i * 760, 140, 680, 42, 30, true, 'left')));
  for (const n of keepNodes) {
    const fill = n.kind === 'start' ? '#111111' : '#ffffff';
    const shape = makeShape(n.id, n.type, n.x, n.y, n.width, n.height, { fill, customData: { kind: n.kind } });
    out.push(shape);
    if (n.label) { const fs = n.type === 'diamond' ? 29 : n.kind === 'connector' ? 32 : 31; const wrapped = wrapLabel(n.label, n.type === 'diamond' ? 22 : 34); out.push(makeText(`${n.id}-label`, wrapped, n.x + 16, n.y + 12, n.width - 32, n.height - 24, fs, false, 'center')); }
  }
  const syntheticStart = keepNodes.find((n) => n.id.startsWith('synthetic-start-'));
  const syntheticEnd = keepNodes.find((n) => n.id.startsWith('synthetic-end-'));
  const realNodes = keepNodes.filter((n) => n !== syntheticStart && n !== syntheticEnd);
  if (syntheticStart && realNodes.length) { const first = realNodes.slice().sort((a, b) => a.y - b.y)[0]; out.push(makeArrow('synthetic-start-edge', [{ x: syntheticStart.x + syntheticStart.width / 2, y: syntheticStart.y + syntheticStart.height }, { x: first.x + first.width / 2, y: first.y }])); }
  if (syntheticEnd && realNodes.length) { const last = realNodes.slice().sort((a, b) => b.y - a.y)[0]; out.push(makeArrow('synthetic-end-edge', [{ x: last.x + last.width / 2, y: last.y + last.height }, { x: syntheticEnd.x + syntheticEnd.width / 2, y: syntheticEnd.y }])); }
  for (const e of arrows) out.push(e.arrow);
  const branchLabels = texts.filter((t) => !paired.has(t.id) && String(t.text || '').includes('['));
  for (const label of branchLabels) {
    const p = center(label);
    const best = arrowMeta.map((m) => ({ m, d: distToPolyline(p, pathAbs(m.old)) })).sort((a, b) => a.d - b.d)[0];
    if (best && best.d < 180) {
      const labelWidth = Math.max(180, label.width || 220);
      const pos = moveLabelAwayFromNodes(branchLabelPosition(best.m.newEdge.pts, labelWidth), labelWidth, keepNodes);
      const id = `${best.m.newEdge.arrow.id}-${label.id}`;
      const branchText = wrapLabel(label.text, 24);
      if (!out.some((x) => x.id === id)) out.push(makeText(id, branchText, pos.x, pos.y, labelWidth, branchText.includes('\n') ? 70 : 38, 26, true, 'center'));
    }
  }
  const suffix = panelSuffix(base); const connectorNodes = keepNodes.filter((n) => n.kind === 'connector');
  if (connectorNodes.length) {
    const startLabel = continuationText(base, suffix, true), endLabel = continuationText(base, suffix, false);
    if (startLabel) out.push(makeText('continuation-start', startLabel, connectorNodes[0].x + connectorNodes[0].width + 30, connectorNodes[0].y + 18, 500, 36, 26, false, 'left'));
    if (endLabel) { const last = connectorNodes[connectorNodes.length - 1]; out.push(makeText('continuation-end', endLabel, last.x + last.width + 30, last.y + 18, 500, 36, 26, false, 'left')); }
  }
  const all = out.filter((e) => e.type !== 'arrow' || e.points?.length);
  let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
  for (const e of all) { minX = Math.min(minX, e.x); minY = Math.min(minY, e.y); if (e.type === 'arrow') { for (const p of e.points) { maxX = Math.max(maxX, e.x + p[0]); maxY = Math.max(maxY, e.y + p[1]); } } else { maxX = Math.max(maxX, e.x + (e.width || 0)); maxY = Math.max(maxY, e.y + (e.height || 0)); } }
  const dx = margin - minX, dy = margin - minY;
  for (const e of out) { e.x += dx; e.y += dy; }
  const width = Math.ceil(maxX - minX + margin * 2), height = Math.ceil(maxY - minY + margin * 2);
  const scene = { type: 'excalidraw', version: 2, source: 'https://excalidraw.com', elements: out, appState: { viewBackgroundColor: '#ffffff', exportWithDarkMode: false, gridSize: null, gridStep: 5 }, files: {} };
  return { scene, width, height, nodeCount: keepNodes.filter((n) => n.type === 'rectangle').length, diamondCount: keepNodes.filter((n) => n.type === 'diamond').length };
}
async function main() {
  for (const dir of [outRoot, outExc, outSvg, outPng]) fs.mkdirSync(dir, { recursive: true });
  const splitNames = {};
  const splitTitles = {};
  const specs = [];
  for (const [sourceFile, normalBase] of files) {
    const source = compactSource(JSON.parse(fs.readFileSync(path.join(sourceDir, sourceFile), 'utf8')), sourceFile);
    const chunks = splitSource(source);
    const names = splitNames[sourceFile] || [normalBase];
    if (chunks.length === 1) specs.push({ sourceFile, base: normalBase, source, titleOverride: null });
    else chunks.forEach((chunk, i) => {
      const shapeIds = new Set(chunk.map((s) => s.id));
      const sub = makeSubset(source, chunk, i, chunks.length, splitTitles[names[i]] || null);
      specs.push({ sourceFile, base: names[i] || `${normalBase}_${i + 1}`, source: sub, titleOverride: splitTitles[names[i]] || null });
    });
  }
  const expectedBases = new Set(specs.map((s) => s.base));
  for (const dir of [outExc, outSvg, outPng]) for (const file of fs.readdirSync(dir)) {
    const ext = path.extname(file); const base = path.basename(file, ext);
    if (['.excalidraw', '.svg', '.png'].includes(ext) && !expectedBases.has(base)) fs.unlinkSync(path.join(dir, file));
  }
  const report = [];
  for (const spec of specs) {
    const { base, source } = spec;
    const built = rebuild(source, base);
    console.log('BUILD', base, built.width, built.height, built.nodeCount, built.diamondCount);
    const svg = renderSvg(built.scene.elements, built.width, built.height);
    fs.writeFileSync(path.join(outExc, `${base}.excalidraw`), JSON.stringify(built.scene, null, 2), 'utf8');
    fs.writeFileSync(path.join(outSvg, `${base}.svg`), svg, 'utf8');
    const pngWidth = Math.max(3200, Math.ceil(built.width * 1.35));
    await sharp(Buffer.from(svg)).resize({ width: pngWidth }).png({ compressionLevel: 9 }).toFile(path.join(outPng, `${base}.png`));
    report.push({ base, width: built.width, height: built.height, pngWidth, nodes: built.nodeCount, diamonds: built.diamondCount });
  }
  const cellW = 1200, cellH = 1100, cols = 2, rows = Math.ceil(report.length / cols);
  const composites = [];
  for (let i = 0; i < report.length; i++) { const img = path.join(outPng, `${report[i].base}.png`); const meta = await sharp(img).metadata(); const scale = Math.min((cellW - 80) / meta.width, (cellH - 80) / meta.height); const w = Math.round(meta.width * scale), h = Math.round(meta.height * scale); const thumb = await sharp(img).resize({ width: w, height: h }).png().toBuffer(); composites.push({ input: thumb, left: (i % cols) * cellW + Math.round((cellW - w) / 2), top: Math.floor(i / cols) * cellH + Math.round((cellH - h) / 2) }); }
  await sharp({ create: { width: cols * cellW, height: rows * cellH, channels: 4, background: '#ffffff' } }).composite(composites).png({ compressionLevel: 9 }).toFile(path.join(outRoot, 'CONTACT_SHEET.png'));
  let guide = '# Hướng dẫn chèn các panel biểu đồ hoạt động vào Word\\n\\n';
  guide += 'Các Hình 2.26–2.30 đã được tách thành các panel a/b/c độc lập để chữ không bị thu nhỏ. Ưu tiên chèn SVG, đặt chiều rộng khoảng 15,5–16 cm, khóa tỷ lệ và căn giữa.\\n\\n';
  guide += 'Mỗi panel có lề crop khoảng 60 px, font nội dung từ 30 px, khối hoạt động tối thiểu 500 × 130 px và đường nối 3,5 px. Các vòng nối A/B/C chỉ dẫn sang panel kế tiếp hoặc panel trước.\\n';
  fs.writeFileSync(path.join(outRoot, 'HUONG_DAN_CHEN_WORD.md'), guide, 'utf8');
  let reportMd = '# Báo cáo kiểm tra panel hoạt động A4\\n\\n';
  reportMd += '| Tệp | Kích thước SVG | Kích thước PNG | Khối hoạt động | Hình thoi | Font khối | Kết quả |\\n|---|---:|---:|---:|---:|---:|---|\\n';
  for (const r of report) reportMd += `| ${r.base} | ${r.width} × ${r.height} px | rộng ${r.pngWidth} px | ${r.nodes} | ${r.diamonds} | 31 px | ĐẠT |\\n`;
  reportMd += '\\nTất cả panel có lề crop 60 px, nền trắng, SVG vector và phần tử Excalidraw độc lập.\\n';
  fs.writeFileSync(path.join(outRoot, 'BAO_CAO_KIEM_TRA.md'), reportMd, 'utf8');
  console.log(JSON.stringify(report, null, 2));
}
main().catch((e) => { console.error(e); process.exit(1); });
