# Hình 2.1 Use-Case Temporary Canvas Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Dựng Hình 2.1 use-case tổng quát hệ thống VSL trên canvas Excalidraw tạm thời, giữ nội dung và phong cách của SVG mẫu.

**Architecture:** Dùng CLI `mcp-excalidraw-server` để tạo các shape, text và arrow trên canvas cục bộ. Dùng browser để đồng bộ cảnh, chụp screenshot và kiểm tra trực quan; không sửa file SVG gốc và không lưu bản vẽ thành file đầu ra.

**Tech Stack:** Excalidraw skill, `mcp-excalidraw-server` 1.1.0, Codex bundled Node/pnpm, browser canvas tại `http://127.0.0.1:3000`.

## Global Constraints

- Canvas logic: 1800×1250.
- Nền trắng, nét đen/xám, bố cục UML tối giản.
- Chữ sans-serif tương đương DejaVu Sans; tiêu đề 25px đậm, tên hệ thống 22px đậm, nội dung 18px.
- Không thay đổi `C:\do an\bieu_do_vsl_giong_Hoan_dung_ten_svg (1)\hinh_2_1_usecase_tong_quat.svg`.

### Task 1: Create and verify the temporary use-case scene

**Files:**
- Read: `C:\do an\bieu_do_vsl_giong_Hoan_dung_ten_svg (1)\hinh_2_1_usecase_tong_quat.svg`
- No project files modified; scene exists only in the live canvas.

**Interfaces:**
- Consumes: 16 use-case labels, 6 actor/external labels, actor links, and 2 `<<include>>` links from the SVG reference.
- Produces: A live Excalidraw scene at `http://127.0.0.1:3000` that can be inspected and edited.

- [ ] **Step 1: Clear the temporary canvas.**

Run `mcp-excalidraw-server clear --yes` using the Codex bundled runtime.

- [ ] **Step 2: Add the system boundary, title, actors, external systems, use-cases, and links.**

Use custom IDs, `fontFamily: "DejaVu Sans"`, white fills, black strokes, ellipse use-cases, free-standing text for the title/system label, and bound arrows using `startElementId`/`endElementId`.

- [ ] **Step 3: Open and sync the canvas.**

Navigate the in-app browser to `http://127.0.0.1:3000`, select `Sync to Backend`, and verify the scene is visible.

- [ ] **Step 4: Run the quality check.**

Capture a screenshot and check text truncation, overlap, arrow crossings, label readability, and placement of both `<<include>>` labels. Adjust only the affected elements and recapture if needed.

- [ ] **Step 5: Leave the temporary scene available for viewing.**

Keep the canvas server and browser tab open so the user can inspect the result; do not export or overwrite the SVG.
