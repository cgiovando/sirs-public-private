"""Render the meeting note markdown to a styled standalone HTML file.

Single self-contained file (no external CSS/JS) so it can be opened locally or
emailed to the SIRS team without further setup. Uses system fonts so it works
offline.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

import markdown


CSS = r"""
:root {
    --bg: #f4f3ee;            /* warm off-white background outside the page */
    --page: #ffffff;
    --fg: #1a1a1a;
    --fg-muted: #5b6470;
    --fg-subtle: #8a929d;
    --rule: #e7e9ec;
    --rule-strong: #cdd2da;
    --accent: #d73f3f;
    --accent-soft: #fdecec;
    --public: #1f77b4;
    --warn: #d4a017;
    --code-bg: #f3f4f7;
    --shadow: 0 1px 2px rgba(0,0,0,0.04), 0 4px 14px rgba(0,0,0,0.05);
    --radius: 12px;
    --content-max: 760px;
}

* { box-sizing: border-box; }
html { scroll-behavior: smooth; }
body {
    margin: 0;
    background: var(--bg);
    color: var(--fg);
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Inter", "Helvetica Neue", Arial, sans-serif;
    line-height: 1.65;
    font-size: 16px;
    -webkit-font-smoothing: antialiased;
    -moz-osx-font-smoothing: grayscale;
}

/* === Outer page layout === */
.shell {
    max-width: 1200px;
    margin: 0 auto;
    padding: 32px 24px 80px;
    display: grid;
    grid-template-columns: 220px minmax(0, 1fr);
    gap: 40px;
    align-items: start;
}
@media (max-width: 960px) {
    .shell { grid-template-columns: minmax(0, 1fr); padding: 16px 12px 48px; gap: 20px; }
    .sidebar { position: static !important; }
}

/* === Sidebar TOC === */
.sidebar {
    position: sticky;
    top: 24px;
    align-self: start;
    font-size: 13px;
    line-height: 1.55;
    background: var(--page);
    border: 1px solid var(--rule);
    border-radius: var(--radius);
    padding: 18px 18px 18px 8px;
    box-shadow: var(--shadow);
    max-height: calc(100vh - 48px);
    overflow-y: auto;
}
.toc-title {
    text-transform: uppercase;
    letter-spacing: 0.08em;
    font-size: 11px;
    color: var(--fg-subtle);
    font-weight: 700;
    margin: 0 0 10px 12px;
}
.sidebar .toc { font-size: 13px; }
.sidebar .toc > ul { list-style: none; padding: 0; margin: 0; border-left: 1px solid var(--rule); }
.sidebar .toc ul ul { list-style: none; padding-left: 12px; margin: 4px 0; }
.sidebar .toc li { margin: 0; }
.sidebar .toc a {
    display: block;
    padding: 4px 0 4px 12px;
    color: var(--fg-muted);
    text-decoration: none;
    border-left: 2px solid transparent;
    margin-left: -1px;
    transition: color 0.15s, border-color 0.15s;
}
.sidebar .toc a:hover { color: var(--accent); border-left-color: var(--accent); }
.sidebar .toc ul ul a { font-size: 12.5px; padding-left: 24px; }

/* === Page (main content card) === */
.page {
    background: var(--page);
    border: 1px solid var(--rule);
    border-radius: var(--radius);
    box-shadow: var(--shadow);
    padding: 40px 56px 56px;
    min-width: 0;
}
@media (max-width: 720px) {
    .page { padding: 24px 18px 32px; }
}

.prose { max-width: var(--content-max); }
.prose > * { max-width: 100%; }

/* === Hero === */
.hero { margin-bottom: 32px; padding-bottom: 24px; border-bottom: 1px solid var(--rule); }
.eyebrow {
    text-transform: uppercase;
    letter-spacing: 0.1em;
    font-size: 11.5px;
    font-weight: 700;
    color: var(--accent);
    margin-bottom: 10px;
}
.hero h1 {
    font-size: 30px;
    line-height: 1.2;
    font-weight: 700;
    margin: 0 0 12px;
    letter-spacing: -0.01em;
}
.hero .lead { color: var(--fg-muted); font-size: 15px; margin: 0 0 14px; }
.hero .meta { color: var(--fg-subtle); font-size: 13px; }
.hero code { font-size: 12.5px; }

/* === Headings === */
.prose h2 {
    font-size: 22px;
    line-height: 1.25;
    font-weight: 700;
    margin: 48px 0 14px;
    padding-top: 0;
    letter-spacing: -0.005em;
    color: var(--fg);
}
.prose h2:first-child { margin-top: 8px; }
.prose h3 {
    font-size: 16.5px;
    font-weight: 700;
    margin: 28px 0 10px;
    color: var(--fg);
}
.prose h2 .anchor, .prose h3 .anchor {
    color: var(--fg-subtle);
    text-decoration: none;
    margin-left: 8px;
    opacity: 0;
    transition: opacity 0.15s;
    font-weight: 400;
}
.prose h2:hover .anchor, .prose h3:hover .anchor { opacity: 0.5; }

/* === Body text === */
.prose p { margin: 0 0 14px; }
.prose strong { font-weight: 700; color: #000; }
.prose em { color: var(--fg-muted); font-style: italic; }
.prose a { color: var(--accent); text-decoration: none; border-bottom: 1px solid #f0bcbc; transition: border-color 0.15s; }
.prose a:hover { border-bottom-color: var(--accent); }
.prose ul, .prose ol { margin: 0 0 18px; padding-left: 22px; }
.prose li { margin-bottom: 6px; }
.prose li > ul, .prose li > ol { margin: 6px 0; }
.prose hr { border: 0; border-top: 1px solid var(--rule); margin: 32px 0; }

/* === Code === */
.prose code {
    font-family: ui-monospace, "SF Mono", Menlo, Consolas, monospace;
    font-size: 13.5px;
    background: var(--code-bg);
    padding: 1.5px 6px;
    border-radius: 4px;
    color: #2a2a2a;
}
.prose pre {
    background: #1f2429;
    color: #e6e6e6;
    border-radius: 8px;
    padding: 16px 18px;
    overflow-x: auto;
    font-size: 13px;
    line-height: 1.55;
    margin: 18px 0 28px;
}
.prose pre code { background: transparent; padding: 0; font-size: 13px; color: inherit; border: none; }

/* === Tables === */
.prose .table-wrap {
    margin: 18px 0 28px;
    border: 1px solid var(--rule);
    border-radius: 8px;
    overflow: auto;
    box-shadow: var(--shadow);
    background: var(--page);
}
.prose table {
    border-collapse: collapse;
    width: 100%;
    font-size: 14px;
    margin: 0;
}
.prose thead { background: #f7f7f5; }
.prose th, .prose td {
    text-align: left;
    padding: 10px 14px;
    border-bottom: 1px solid var(--rule);
    vertical-align: top;
}
.prose th {
    font-weight: 700;
    color: var(--fg-muted);
    font-size: 12px;
    text-transform: uppercase;
    letter-spacing: 0.05em;
}
.prose tbody tr:last-child td { border-bottom: none; }
.prose tbody tr:nth-child(even) { background: #fbfbfa; }
.prose td code { font-size: 12.5px; }

/* === Figures === */
.prose img {
    max-width: 100%;
    height: auto;
    display: block;
    margin: 24px auto;
    border-radius: 8px;
    box-shadow: var(--shadow);
    border: 1px solid var(--rule);
    background: var(--page);
}

/* === KPI grid === */
.kpi-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
    gap: 12px;
    margin: 28px 0 36px;
}
.kpi {
    background: #fafaf8;
    border: 1px solid var(--rule);
    border-radius: 10px;
    padding: 14px 16px;
}
.kpi .num {
    font-size: 24px;
    font-weight: 700;
    line-height: 1.1;
    color: var(--fg);
    font-variant-numeric: tabular-nums;
    letter-spacing: -0.01em;
}
.kpi .num.accent { color: var(--accent); }
.kpi .num.public { color: var(--public); }
.kpi .num.warn { color: var(--warn); }
.kpi .label {
    font-size: 11.5px;
    color: var(--fg-muted);
    margin-top: 6px;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    font-weight: 600;
    line-height: 1.35;
}

/* === Footer === */
.page-footer {
    margin-top: 56px;
    padding-top: 20px;
    border-top: 1px solid var(--rule);
    color: var(--fg-subtle);
    font-size: 13px;
}

/* === Print === */
@media print {
    body { background: white; font-size: 12pt; }
    .shell { display: block; padding: 0; max-width: 100%; }
    .sidebar { display: none; }
    .page { box-shadow: none; border: none; padding: 0; border-radius: 0; }
    .prose img, .prose .table-wrap { box-shadow: none; }
    .prose h2 { break-before: page; }
    .prose h2:first-child { break-before: auto; }
}
"""


KPI_INTERNAL = """
<div class="kpi-grid">
  <div class="kpi"><div class="num public">9,269</div><div class="label">Schools assembled<br>(Giga + OSM)</div></div>
  <div class="kpi"><div class="num">70.6%</div><div class="label">Stage A coverage<br>(high + medium)</div></div>
  <div class="kpi"><div class="num">0.887</div><div class="label">Stage C ROC-AUC<br>(ADM1-grouped CV)</div></div>
  <div class="kpi"><div class="num accent">6% &rarr; 11%</div><div class="label">Detected private vs<br>prior-shifted estimate</div></div>
  <div class="kpi"><div class="num warn">36%</div><div class="label">INFRE 2021-22<br>national private rate</div></div>
  <div class="kpi"><div class="num">3-5x</div><div class="label">Under-detection<br>vs INFRE per-department</div></div>
</div>
"""

KPI_TEAM = """
<div class="kpi-grid">
  <div class="kpi"><div class="num public">9,269</div><div class="label">Schools assembled<br>Giga + OSM joined</div></div>
  <div class="kpi"><div class="num">~12,000</div><div class="label">INFRE 2021-22<br>primary universe</div></div>
  <div class="kpi"><div class="num">70.6%</div><div class="label">Stage A coverage<br>deterministic labels</div></div>
  <div class="kpi"><div class="num">0.887 / 0.916</div><div class="label">Stage C ROC-AUC<br>grouped / shuffled CV</div></div>
  <div class="kpi"><div class="num accent">6%</div><div class="label">Detected private<br>(of labelled)</div></div>
  <div class="kpi"><div class="num warn">36%</div><div class="label">INFRE national<br>private share, primary</div></div>
</div>
"""


def split_intro(md_text: str) -> tuple[str, str, str]:
    """Return (h1, intro_md, body_md). Intro is everything between the H1 and
    the first H2 (or top of body if no H2 exists). Body starts at the first H2."""
    lines = md_text.splitlines()
    h1 = ""
    intro_start = None
    body_start = len(lines)
    for i, line in enumerate(lines):
        if not h1 and line.startswith("# "):
            h1 = line[2:].strip()
            intro_start = i + 1
            continue
        if h1 and line.startswith("## "):
            body_start = i
            break
    intro_md = "\n".join(lines[intro_start:body_start]).strip() if intro_start is not None else ""
    body_md = "\n".join(lines[body_start:])
    return h1, intro_md, body_md


def render(md_path: Path, out_path: Path, variant: str = "internal") -> None:
    md_text = md_path.read_text()
    h1, intro_md, body_md = split_intro(md_text)

    md_engine = markdown.Markdown(
        extensions=["extra", "toc", "attr_list", "sane_lists"],
        extension_configs={
            "toc": {
                "permalink": "#",
                "permalink_class": "anchor",
                "permalink_title": "permalink",
                "toc_depth": "2-3",
            },
        },
    )

    intro_html = md_engine.convert(intro_md) if intro_md else ""
    md_engine.reset()
    body_html = md_engine.convert(body_md)
    toc_html = md_engine.toc

    body_html = re.sub(r"<table>", '<div class="table-wrap"><table>', body_html)
    body_html = re.sub(r"</table>", "</table></div>", body_html)

    # Insert the KPI grid right after the first H2's first <ul>, choosing the
    # KPI block matching the variant.
    kpi = KPI_TEAM if variant == "team" else KPI_INTERNAL
    h2_match = re.search(r"<h2[^>]*>", body_html)
    if h2_match:
        ul_close = body_html.find("</ul>", h2_match.end())
        if ul_close != -1:
            insert_at = ul_close + len("</ul>")
            body_html = body_html[:insert_at] + "\n" + kpi + body_html[insert_at:]

    title = h1 or "Meeting note"
    eyebrow = "SIRS Weekly &middot; 2026-05-01" if variant == "internal" else "SIRS Weekly &middot; Benin pilot"
    page = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>{CSS}</style>
</head>
<body>
<div class="shell">
  <aside class="sidebar">
    <div class="toc-title">On this page</div>
    {toc_html}
  </aside>
  <main class="page">
    <header class="hero">
      <div class="eyebrow">{eyebrow}</div>
      <h1>{title}</h1>
      {intro_html}
    </header>
    <article class="prose">
      {body_html}
    </article>
    <div class="page-footer">
      Generated from <code>{md_path.name}</code> on 2026-04-30.
    </div>
  </main>
</div>
</body>
</html>
"""
    out_path.write_text(page)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--input", default="docs/2026-05-01_sirs_weekly_stage_a_benin.md")
    p.add_argument("--output", default="docs/2026-05-01_sirs_weekly_stage_a_benin.html")
    p.add_argument("--variant", choices=["internal", "team"], default="internal")
    args = p.parse_args()

    in_path = Path(args.input)
    out_path = Path(args.output)
    render(in_path, out_path, args.variant)
    size = out_path.stat().st_size
    print(f"wrote {out_path}  ({size:,} bytes, variant={args.variant})")


if __name__ == "__main__":
    main()
