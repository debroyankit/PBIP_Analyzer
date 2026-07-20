"""Streamlit web UI for the PBIP Dependency Analyzer.

Run with:
    streamlit run streamlit_app.py
"""

from __future__ import annotations

import io
import tempfile
import zipfile
from pathlib import Path

import streamlit as st

# ---------------------------------------------------------------------------
# Ensure project root is importable (handles running from project dir)
# ---------------------------------------------------------------------------
import sys

_project_root = Path(__file__).resolve().parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from main import analyze_pbip, is_system_table
from services.dependency_engine import DependencyGraph, find_unused_entities
from services.excel_export import write_excel_report

# ═══════════════════════════════════════════════════════════════════════════
# Page config
# ═══════════════════════════════════════════════════════════════════════════
st.set_page_config(
    page_title="PBIP Analyzer",
    page_icon="🔍",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ═══════════════════════════════════════════════════════════════════════════
# Custom CSS — premium dark glassmorphism theme
# ═══════════════════════════════════════════════════════════════════════════
st.markdown(
    """
<style>
/* ── Google Font ── */
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&display=swap');

* { font-family: 'Inter', sans-serif !important; }

/* ── Animated gradient header bar ── */
.gradient-header {
    background: linear-gradient(135deg, #4f8ffc 0%, #6c63ff 25%, #10b981 50%, #f59e0b 75%, #ef4444 100%);
    background-size: 300% 300%;
    animation: gradientShift 8s ease infinite;
    padding: 2rem 2.5rem;
    border-radius: 16px;
    margin-bottom: 1.5rem;
    position: relative;
    overflow: hidden;
}
.gradient-header::before {
    content: '';
    position: absolute;
    inset: 0;
    background: rgba(10, 14, 39, 0.45);
    border-radius: 16px;
}
.gradient-header h1 {
    position: relative;
    color: #ffffff !important;
    font-weight: 800;
    font-size: 2rem;
    margin: 0;
    letter-spacing: -0.02em;
}
.gradient-header p {
    position: relative;
    color: rgba(255,255,255,0.85) !important;
    font-weight: 400;
    font-size: 0.95rem;
    margin: 0.4rem 0 0 0;
}
@keyframes gradientShift {
    0%   { background-position: 0% 50%; }
    50%  { background-position: 100% 50%; }
    100% { background-position: 0% 50%; }
}

/* ── Metric cards ── */
.metric-card {
    background: rgba(19, 24, 54, 0.65);
    backdrop-filter: blur(16px);
    -webkit-backdrop-filter: blur(16px);
    border: 1px solid rgba(79, 143, 252, 0.18);
    border-radius: 14px;
    padding: 1.4rem 1.6rem;
    text-align: center;
    transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
    position: relative;
    overflow: hidden;
}
.metric-card:hover {
    transform: translateY(-4px);
    border-color: rgba(79, 143, 252, 0.45);
    box-shadow: 0 12px 40px rgba(79, 143, 252, 0.15);
}
.metric-card .metric-value {
    font-size: 2.4rem;
    font-weight: 800;
    background: linear-gradient(135deg, #4f8ffc, #6c63ff);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    background-clip: text;
    line-height: 1.1;
}
.metric-card .metric-label {
    font-size: 0.82rem;
    font-weight: 500;
    color: #94a3b8;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    margin-top: 0.3rem;
}
.metric-card.emerald .metric-value {
    background: linear-gradient(135deg, #10b981, #34d399);
    -webkit-background-clip: text; background-clip: text;
}
.metric-card.amber .metric-value {
    background: linear-gradient(135deg, #f59e0b, #fbbf24);
    -webkit-background-clip: text; background-clip: text;
}
.metric-card.coral .metric-value {
    background: linear-gradient(135deg, #ef4444, #f87171);
    -webkit-background-clip: text; background-clip: text;
}
.metric-card.purple .metric-value {
    background: linear-gradient(135deg, #8b5cf6, #a78bfa);
    -webkit-background-clip: text; background-clip: text;
}
.metric-card.cyan .metric-value {
    background: linear-gradient(135deg, #06b6d4, #22d3ee);
    -webkit-background-clip: text; background-clip: text;
}

/* ── Section titles ── */
.section-title {
    font-size: 1.15rem;
    font-weight: 700;
    color: #e2e8f0;
    margin: 1.8rem 0 0.8rem 0;
    padding-bottom: 0.5rem;
    border-bottom: 2px solid rgba(79, 143, 252, 0.25);
    display: flex;
    align-items: center;
    gap: 0.5rem;
}

/* ── Badge chips ── */
.badge {
    display: inline-block;
    padding: 0.2rem 0.65rem;
    border-radius: 20px;
    font-size: 0.72rem;
    font-weight: 600;
    margin: 0.15rem 0.2rem;
    letter-spacing: 0.02em;
}
.badge-blue   { background: rgba(79,143,252,0.18); color: #4f8ffc; border: 1px solid rgba(79,143,252,0.3); }
.badge-green  { background: rgba(16,185,129,0.18); color: #10b981; border: 1px solid rgba(16,185,129,0.3); }
.badge-amber  { background: rgba(245,158,11,0.18); color: #f59e0b; border: 1px solid rgba(245,158,11,0.3); }
.badge-red    { background: rgba(239,68,68,0.18);  color: #ef4444; border: 1px solid rgba(239,68,68,0.3);  }
.badge-purple { background: rgba(139,92,246,0.18); color: #8b5cf6; border: 1px solid rgba(139,92,246,0.3); }
.badge-cyan   { background: rgba(6,182,212,0.18);  color: #06b6d4; border: 1px solid rgba(6,182,212,0.3);  }

/* ── DAX code blocks ── */
.dax-block {
    background: rgba(10, 14, 39, 0.8);
    border: 1px solid rgba(79, 143, 252, 0.15);
    border-radius: 10px;
    padding: 1rem 1.2rem;
    font-family: 'JetBrains Mono', 'Fira Code', monospace !important;
    font-size: 0.82rem;
    color: #a5f3fc;
    overflow-x: auto;
    white-space: pre-wrap;
    word-break: break-word;
    line-height: 1.6;
}

/* ── Glass panel ── */
.glass-panel {
    background: rgba(19, 24, 54, 0.5);
    backdrop-filter: blur(12px);
    border: 1px solid rgba(79, 143, 252, 0.12);
    border-radius: 12px;
    padding: 1.2rem 1.4rem;
    margin-bottom: 0.8rem;
    transition: border-color 0.3s ease;
}
.glass-panel:hover {
    border-color: rgba(79, 143, 252, 0.35);
}

/* ── Table row highlight ── */
.entity-row {
    padding: 0.6rem 0;
    border-bottom: 1px solid rgba(79, 143, 252, 0.08);
}
.entity-row:last-child { border-bottom: none; }

/* ── Streamlit overrides ── */
.stTabs [data-baseweb="tab-list"] {
    gap: 0;
    background: rgba(19, 24, 54, 0.6);
    border-radius: 12px;
    padding: 0.3rem;
}
.stTabs [data-baseweb="tab"] {
    border-radius: 8px;
    padding: 0.6rem 1.2rem;
    font-weight: 600;
    font-size: 0.85rem;
}
.stTabs [aria-selected="true"] {
    background: rgba(79, 143, 252, 0.2) !important;
}

div[data-testid="stExpander"] {
    background: rgba(19, 24, 54, 0.45);
    border: 1px solid rgba(79, 143, 252, 0.12);
    border-radius: 12px;
    margin-bottom: 0.5rem;
    transition: border-color 0.3s ease;
}
div[data-testid="stExpander"]:hover {
    border-color: rgba(79, 143, 252, 0.35);
}

/* ── Sidebar ── */
section[data-testid="stSidebar"] {
    background: rgba(10, 14, 39, 0.95) !important;
    border-right: 1px solid rgba(79, 143, 252, 0.12);
}
section[data-testid="stSidebar"] .stMarkdown h2 {
    font-size: 1rem;
    font-weight: 700;
    color: #4f8ffc;
}

/* ── Upload area ── */
section[data-testid="stSidebar"] [data-testid="stFileUploader"] {
    border: 2px dashed rgba(79, 143, 252, 0.3);
    border-radius: 12px;
    padding: 0.5rem;
    transition: border-color 0.3s ease;
}
section[data-testid="stSidebar"] [data-testid="stFileUploader"]:hover {
    border-color: rgba(79, 143, 252, 0.6);
}

/* ── Empty-state ── */
.empty-state {
    text-align: center;
    padding: 4rem 2rem;
    color: #64748b;
}
.empty-state .icon {
    font-size: 4rem;
    margin-bottom: 1rem;
    opacity: 0.5;
}
.empty-state h3 {
    color: #94a3b8;
    font-weight: 600;
    margin-bottom: 0.5rem;
}
.empty-state p {
    font-size: 0.9rem;
    max-width: 480px;
    margin: 0 auto;
}
</style>
""",
    unsafe_allow_html=True,
)


# ═══════════════════════════════════════════════════════════════════════════
# Helper renderers
# ═══════════════════════════════════════════════════════════════════════════

def _metric_card(value, label: str, variant: str = "") -> str:
    cls = f"metric-card {variant}" if variant else "metric-card"
    return f'<div class="{cls}"><div class="metric-value">{value}</div><div class="metric-label">{label}</div></div>'


def _badge(text: str, color: str = "blue") -> str:
    return f'<span class="badge badge-{color}">{text}</span>'


def _section_title(icon: str, text: str) -> str:
    return f'<div class="section-title">{icon} {text}</div>'


def _render_badge_list(items: list[str], color: str = "blue", max_show: int = 30) -> str:
    if not items:
        return '<span style="color:#64748b;font-size:0.85rem;">None</span>'
    shown = items[:max_show]
    html = "".join(_badge(item, color) for item in shown)
    if len(items) > max_show:
        html += f'<span style="color:#64748b;font-size:0.8rem;margin-left:0.4rem;">+{len(items) - max_show} more</span>'
    return html


# ═══════════════════════════════════════════════════════════════════════════
# Sidebar — Upload & controls
# ═══════════════════════════════════════════════════════════════════════════

with st.sidebar:
    st.markdown("## 🔍 PBIP Analyzer")
    st.markdown(
        '<p style="color:#64748b;font-size:0.82rem;margin-top:-0.5rem;">'
        "Analyze your Power BI PBIP project dependencies.</p>",
        unsafe_allow_html=True,
    )
    st.markdown("---")

    input_mode = st.radio(
        "Input method",
        ["📁 Local Folder Path", "📦 ZIP Upload"],
        help="Use 'Local Folder Path' for large projects to avoid upload size limits.",
        horizontal=True,
    )

    pbip_path_input = None
    uploaded = None

    if input_mode == "📁 Local Folder Path":
        folder_path = st.text_input(
            "Path to folder containing .pbip file",
            placeholder=r"C:\Users\...\MyProject",
            help="Paste the full path to the folder that contains your .pbip file (along with .Report/ and .SemanticModel/ siblings).",
        )
        if folder_path:
            folder = Path(folder_path.strip().strip('"').strip("'"))
            if folder.is_dir():
                pbip_files = list(folder.glob("*.pbip"))
                if pbip_files:
                    pbip_path_input = str(pbip_files[0])
                    st.success(f"✅ Found: `{pbip_files[0].name}`")
                else:
                    st.error("No `.pbip` file found in this folder.")
            elif folder.is_file() and folder.suffix.lower() == ".pbip":
                pbip_path_input = str(folder)
                st.success(f"✅ Found: `{folder.name}`")
            else:
                st.error("Folder not found. Please check the path.")

        analyze_btn = st.button("🔍 Analyze Project", use_container_width=True, disabled=pbip_path_input is None)
    else:
        uploaded = st.file_uploader(
            "Upload PBIP Project (.zip)",
            type=["zip"],
            help="Zip the folder containing your .pbip file along with its .Report/ and .SemanticModel/ siblings. Max 1GB.",
        )
        analyze_btn = False

    exclude_system = st.toggle("Exclude system tables", value=True, help="Hide auto-generated LocalDateTable / DateTableTemplate entries.")

    st.markdown("---")

    # Downloads (available after analysis)
    if "graph" in st.session_state:
        st.markdown("## 📥 Downloads")
        graph: DependencyGraph = st.session_state["graph"]

        excel_bytes = write_excel_report(graph, exclude_system=exclude_system)
        st.download_button(
            "⬇ dependency_report.xlsx",
            data=excel_bytes,
            file_name="dependency_report.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
            help="3-sheet workbook: Table Summary · Detailed Mapping · DAX Lineage",
        )


# ═══════════════════════════════════════════════════════════════════════════
# Analysis engine
# ═══════════════════════════════════════════════════════════════════════════

def _run_analysis_from_zip(zip_bytes: bytes) -> DependencyGraph:
    """Extract ZIP, locate .pbip file, run analysis, return graph."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            zf.extractall(tmp_path)

        pbip_files = list(tmp_path.rglob("*.pbip"))
        if not pbip_files:
            st.error("No `.pbip` file found inside the uploaded ZIP. Please make sure to include the `.pbip` file.")
            st.stop()

        pbip_path = pbip_files[0]
        graph = analyze_pbip(
            str(pbip_path),
            output_dir=str(tmp_path / "_output"),
            exclude_system=False,
            no_color=True,
        )
        return graph


def _run_analysis_from_path(pbip_path: str) -> DependencyGraph:
    """Run analysis directly from a local .pbip file path."""
    with tempfile.TemporaryDirectory() as tmp:
        graph = analyze_pbip(
            pbip_path,
            output_dir=str(Path(tmp) / "_output"),
            exclude_system=False,
            no_color=True,
        )
        return graph


# Trigger analysis — local folder path mode
if analyze_btn and pbip_path_input:
    with st.spinner("🔍 Analyzing PBIP project…"):
        graph = _run_analysis_from_path(pbip_path_input)
        st.session_state["graph"] = graph
        st.session_state["_last_upload_id"] = pbip_path_input
    st.rerun()

# Trigger analysis — ZIP upload mode
if uploaded is not None:
    file_id = f"{uploaded.name}_{uploaded.size}"
    if st.session_state.get("_last_upload_id") != file_id:
        with st.spinner("🔍 Analyzing PBIP project…"):
            graph = _run_analysis_from_zip(uploaded.getvalue())
            st.session_state["graph"] = graph
            st.session_state["_last_upload_id"] = file_id
        st.rerun()


# ═══════════════════════════════════════════════════════════════════════════
# Main content
# ═══════════════════════════════════════════════════════════════════════════

# Header
st.markdown(
    '<div class="gradient-header">'
    "<h1>PBIP Dependency Analyzer</h1>"
    "<p>Explore tables, measures, visuals, pages, and relationships across your Power BI project.</p>"
    "</div>",
    unsafe_allow_html=True,
)

if "graph" not in st.session_state:
    st.markdown(
        '<div class="empty-state">'
        '<div class="icon">📂</div>'
        "<h3>No project loaded</h3>"
        "<p>Paste a local folder path or upload a zipped PBIP project in the sidebar to start exploring.</p>"
        "</div>",
        unsafe_allow_html=True,
    )
    st.stop()


# ── Data prep ──
graph: DependencyGraph = st.session_state["graph"]
unused = find_unused_entities(graph)

total_tables = len(graph.tables)
system_tables_count = sum(1 for n in graph.tables if is_system_table(n))
active_tables = total_tables - system_tables_count

if exclude_system:
    tables_dict = {n: t for n, t in graph.tables.items() if not is_system_table(n)}
    measures_dict = {n: m for n, m in graph.measures.items() if not is_system_table(m.table)}
    unused_tables = [t for t in unused["unused_tables"] if not is_system_table(t)]
    unused_measures = [m for m in unused["unused_measures"] if not (m in graph.measures and is_system_table(graph.measures[m].table))]
    unused_columns = {t: cols for t, cols in unused["unused_columns"].items() if not is_system_table(t)}
    relationships = [r for r in graph.relationships if not is_system_table(r.from_table) and not is_system_table(r.to_table)]
else:
    tables_dict = graph.tables
    measures_dict = graph.measures
    unused_tables = unused["unused_tables"]
    unused_measures = unused["unused_measures"]
    unused_columns = unused["unused_columns"]
    relationships = graph.relationships

total_measures = len(measures_dict)
total_pages = len(graph.pages)
total_visuals = len(graph.visuals)
total_relationships = len(relationships)
total_unused = len(unused_tables) + len(unused_measures) + sum(len(c) for c in unused_columns.values())


# ═══════════════════════════════════════════════════════════════════════════
# Tabs
# ═══════════════════════════════════════════════════════════════════════════

tab_summary, tab_tables, tab_measures, tab_pages, tab_rels, tab_unused = st.tabs(
    ["📊 Summary", "📋 Tables", "📐 Measures", "📄 Pages & Visuals", "🔗 Relationships", "⚠️ Unused"]
)


# ─────────────────────────────────────────────────────────────────────────
# TAB 1: Summary
# ─────────────────────────────────────────────────────────────────────────
with tab_summary:
    cols = st.columns(6)
    cards = [
        (active_tables, "Active Tables", ""),
        (total_measures, "Measures", "emerald"),
        (total_pages, "Pages", "amber"),
        (total_visuals, "Visuals", "purple"),
        (total_relationships, "Relationships", "cyan"),
        (total_unused, "Unused Entities", "coral"),
    ]
    for col, (val, label, variant) in zip(cols, cards):
        col.markdown(_metric_card(val, label, variant), unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)

    col_chart, col_graph = st.columns([1, 2])

    with col_chart:
        st.markdown(_section_title("📈", "Table Usage Breakdown"), unsafe_allow_html=True)
        used_count = len([n for n in tables_dict if tables_dict[n].visuals])
        unused_count = len(tables_dict) - used_count

        import plotly.graph_objects as go  # noqa: E402

        fig = go.Figure(
            data=[
                go.Pie(
                    labels=["Used by visuals", "Unused"],
                    values=[used_count, unused_count],
                    hole=0.65,
                    marker=dict(colors=["#4f8ffc", "#1e293b"], line=dict(color="#0a0e27", width=2)),
                    textfont=dict(color="#e2e8f0", size=13),
                    hoverinfo="label+value+percent",
                )
            ]
        )
        fig.update_layout(
            showlegend=True,
            legend=dict(font=dict(color="#94a3b8", size=12)),
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            margin=dict(t=10, b=10, l=10, r=10),
            height=280,
        )
        st.plotly_chart(fig, use_container_width=True)

    with col_graph:
        st.markdown(_section_title("🕸️", "Dependency Graph"), unsafe_allow_html=True)
        dot_src = build_dot(graph, exclude_system=exclude_system)
        try:
            st.graphviz_chart(dot_src, use_container_width=True)
        except Exception:
            st.info("Install Graphviz on your system to render the dependency graph inline.")
            st.code(dot_src, language="dot")


# ─────────────────────────────────────────────────────────────────────────
# TAB 2: Tables
# ─────────────────────────────────────────────────────────────────────────
with tab_tables:
    st.markdown(_section_title("📋", f"Tables ({len(tables_dict)})"), unsafe_allow_html=True)

    search = st.text_input("🔎 Search tables…", key="table_search", placeholder="Type a table name…")
    filtered = {n: t for n, t in sorted(tables_dict.items()) if search.lower() in n.lower()} if search else dict(sorted(tables_dict.items()))

    if not filtered:
        st.info("No tables match your search.")
    else:
        for name, table in filtered.items():
            has_visuals = bool(table.visuals)
            status_badge = _badge("USED", "green") if has_visuals else _badge("UNUSED", "red")
            with st.expander(f"**{name}**  {('✅' if has_visuals else '⚠️')}  —  {len(table.columns)} cols · {len(table.measures)} measures · {len(table.visuals)} visuals"):
                c1, c2 = st.columns(2)
                with c1:
                    st.markdown(_section_title("📊", "Columns"), unsafe_allow_html=True)
                    st.markdown(_render_badge_list(sorted(table.columns), "blue"), unsafe_allow_html=True)

                    st.markdown(_section_title("📐", "Measures"), unsafe_allow_html=True)
                    st.markdown(_render_badge_list(sorted(table.measures), "green"), unsafe_allow_html=True)

                with c2:
                    st.markdown(_section_title("👁️", "Visuals"), unsafe_allow_html=True)
                    table_visual_titles = sorted(graph.visuals[vid].title for vid in table.visuals if vid in graph.visuals)
                    st.markdown(_render_badge_list(table_visual_titles, "purple"), unsafe_allow_html=True)

                    st.markdown(_section_title("📄", "Pages"), unsafe_allow_html=True)
                    st.markdown(_render_badge_list(sorted(table.pages), "amber"), unsafe_allow_html=True)

                # Related tables
                related = sorted(table.related_tables)
                if exclude_system:
                    related = [r for r in related if not is_system_table(r)]
                st.markdown(_section_title("🔗", "Related Tables"), unsafe_allow_html=True)
                st.markdown(_render_badge_list(related, "cyan"), unsafe_allow_html=True)


# ─────────────────────────────────────────────────────────────────────────
# TAB 3: Measures
# ─────────────────────────────────────────────────────────────────────────
with tab_measures:
    st.markdown(_section_title("📐", f"Measures ({len(measures_dict)})"), unsafe_allow_html=True)

    msearch = st.text_input("🔎 Search measures…", key="measure_search", placeholder="Type a measure name…")
    filtered_m = {n: m for n, m in sorted(measures_dict.items()) if msearch.lower() in n.lower()} if msearch else dict(sorted(measures_dict.items()))

    if not filtered_m:
        st.info("No measures match your search.")
    else:
        for name, measure in filtered_m.items():
            dep_count = len(measure.depends_on_measures)
            used_by_count = len(measure.used_by_measures)
            with st.expander(f"**{name}**  —  table: {measure.table} · refs {len(measure.referenced_tables)} tables · {dep_count} deps"):
                # DAX expression
                if measure.dax:
                    st.markdown(_section_title("🧮", "DAX Expression"), unsafe_allow_html=True)
                    st.markdown(f'<div class="dax-block">{measure.dax}</div>', unsafe_allow_html=True)

                c1, c2 = st.columns(2)
                with c1:
                    st.markdown(_section_title("🏠", "Home Table"), unsafe_allow_html=True)
                    st.markdown(_badge(measure.table, "blue"), unsafe_allow_html=True)

                    ref_tables = sorted(measure.referenced_tables)
                    if exclude_system:
                        ref_tables = [t for t in ref_tables if not is_system_table(t)]
                    st.markdown(_section_title("📊", "Referenced Tables"), unsafe_allow_html=True)
                    st.markdown(_render_badge_list(ref_tables, "cyan"), unsafe_allow_html=True)

                    ref_cols = sorted(measure.referenced_columns)
                    if exclude_system:
                        ref_cols = [c for c in ref_cols if not is_system_table(c.partition("[")[0])]
                    st.markdown(_section_title("📊", "Referenced Columns"), unsafe_allow_html=True)
                    st.markdown(_render_badge_list(ref_cols, "blue"), unsafe_allow_html=True)

                with c2:
                    st.markdown(_section_title("👁️", "Used in Visuals"), unsafe_allow_html=True)
                    measure_visual_titles = sorted(graph.visuals[vid].title for vid in measure.visuals if vid in graph.visuals)
                    st.markdown(_render_badge_list(measure_visual_titles, "purple"), unsafe_allow_html=True)

                    st.markdown(_section_title("📄", "Used on Pages"), unsafe_allow_html=True)
                    st.markdown(_render_badge_list(sorted(measure.pages), "amber"), unsafe_allow_html=True)

                    st.markdown(_section_title("⬇️", "Depends On"), unsafe_allow_html=True)
                    st.markdown(_render_badge_list(sorted(measure.depends_on_measures), "red"), unsafe_allow_html=True)

                    st.markdown(_section_title("⬆️", "Used By"), unsafe_allow_html=True)
                    st.markdown(_render_badge_list(sorted(measure.used_by_measures), "green"), unsafe_allow_html=True)


# ─────────────────────────────────────────────────────────────────────────
# TAB 4: Pages & Visuals
# ─────────────────────────────────────────────────────────────────────────
with tab_pages:
    st.markdown(_section_title("📄", f"Pages ({total_pages})"), unsafe_allow_html=True)

    for page_name, page in sorted(graph.pages.items()):
        page_tables = sorted(page.tables)
        if exclude_system:
            page_tables = [t for t in page_tables if not is_system_table(t)]
        visual_count = len(page.visuals)
        with st.expander(f"**{page_name}**  —  {visual_count} visuals · {len(page_tables)} tables"):
            st.markdown(_section_title("📊", "Tables Used"), unsafe_allow_html=True)
            st.markdown(_render_badge_list(page_tables, "cyan"), unsafe_allow_html=True)

            st.markdown(_section_title("👁️", f"Visuals ({visual_count})"), unsafe_allow_html=True)
            # Find visuals on this page
            page_visuals = {vid: v for vid, v in graph.visuals.items() if v.page == page_name}
            for vid, visual in sorted(page_visuals.items(), key=lambda x: x[1].title):
                vis_tables = sorted(visual.tables)
                vis_cols = sorted(visual.columns)
                vis_measures = sorted(visual.measures)
                if exclude_system:
                    vis_tables = [t for t in vis_tables if not is_system_table(t)]
                    vis_cols = [c for c in vis_cols if not is_system_table(c.partition("[")[0])]

                st.markdown(
                    f'<div class="glass-panel">'
                    f'<strong style="color:#e2e8f0;">{visual.title}</strong> '
                    f'{_badge(visual.type, "purple")}'
                    f'<br><span style="color:#64748b;font-size:0.78rem;">ID: {vid}</span>'
                    f"</div>",
                    unsafe_allow_html=True,
                )
                inner_c1, inner_c2, inner_c3 = st.columns(3)
                with inner_c1:
                    st.markdown("**Tables**", unsafe_allow_html=True)
                    st.markdown(_render_badge_list(vis_tables, "cyan"), unsafe_allow_html=True)
                with inner_c2:
                    st.markdown("**Columns**", unsafe_allow_html=True)
                    st.markdown(_render_badge_list(vis_cols, "blue"), unsafe_allow_html=True)
                with inner_c3:
                    st.markdown("**Measures**", unsafe_allow_html=True)
                    st.markdown(_render_badge_list(vis_measures, "green"), unsafe_allow_html=True)


# ─────────────────────────────────────────────────────────────────────────
# TAB 5: Relationships
# ─────────────────────────────────────────────────────────────────────────
with tab_rels:
    st.markdown(_section_title("🔗", f"Relationships ({total_relationships})"), unsafe_allow_html=True)

    if not relationships:
        st.info("No relationships found in the model.")
    else:
        rel_data = []
        for r in relationships:
            rel_data.append({
                "From Table": r.from_table,
                "From Column": r.from_column,
                "→": "→",
                "To Table": r.to_table,
                "To Column": r.to_column,
            })

        st.dataframe(
            rel_data,
            use_container_width=True,
            hide_index=True,
            column_config={
                "From Table": st.column_config.TextColumn(width="medium"),
                "From Column": st.column_config.TextColumn(width="medium"),
                "→": st.column_config.TextColumn(width="small"),
                "To Table": st.column_config.TextColumn(width="medium"),
                "To Column": st.column_config.TextColumn(width="medium"),
            },
        )


# ─────────────────────────────────────────────────────────────────────────
# TAB 6: Unused Entities
# ─────────────────────────────────────────────────────────────────────────
with tab_unused:
    st.markdown(_section_title("⚠️", "Unused Entities"), unsafe_allow_html=True)
    st.markdown(
        '<p style="color:#64748b;font-size:0.85rem;">Tables, measures, and columns that are <strong>never referenced by any visual</strong> in the report.</p>',
        unsafe_allow_html=True,
    )

    # Summary cards
    uc1, uc2, uc3 = st.columns(3)
    uc1.markdown(_metric_card(len(unused_tables), "Unused Tables", "coral"), unsafe_allow_html=True)
    uc2.markdown(_metric_card(len(unused_measures), "Unused Measures", "amber"), unsafe_allow_html=True)
    total_unused_cols = sum(len(c) for c in unused_columns.values())
    uc3.markdown(_metric_card(total_unused_cols, "Unused Columns", "purple"), unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)

    # Unused tables
    if unused_tables:
        st.markdown(_section_title("📊", f"Unused Tables ({len(unused_tables)})"), unsafe_allow_html=True)
        st.markdown(_render_badge_list(unused_tables, "red"), unsafe_allow_html=True)

    # Unused measures
    if unused_measures:
        st.markdown(_section_title("📐", f"Unused Measures ({len(unused_measures)})"), unsafe_allow_html=True)
        st.markdown(_render_badge_list(unused_measures, "amber"), unsafe_allow_html=True)

    # Unused columns
    if unused_columns:
        st.markdown(_section_title("📊", f"Unused Columns ({total_unused_cols} across {len(unused_columns)} tables)"), unsafe_allow_html=True)
        for tname, cols in sorted(unused_columns.items()):
            with st.expander(f"**{tname}** — {len(cols)} unused columns"):
                st.markdown(_render_badge_list(sorted(cols), "purple"), unsafe_allow_html=True)

    if not unused_tables and not unused_measures and not unused_columns:
        st.success("🎉 No unused entities found — your model is clean!")
