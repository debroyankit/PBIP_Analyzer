# PBIP Dependency Analyzer

Analyzes a Power BI **PBIP** project and answers, for every table in the
semantic model:

> "Where is this table used?" — which measures, visuals, and report pages
> depend on it.

PBIX is intentionally **not** supported — PBIP (Power BI Project) is the
git-friendly, folder-based format Power BI Desktop can save to via
*File → Save as → Power BI project (.pbip)*.

---

## Quick start

```bash
pip install -r requirements.txt   # only needed for running the test suite
python main.py "C:/Projects/Sales"
```

This will:

1. Locate the project's Report and Semantic Model folders automatically (accepts either a direct path to a `.pbip` file, or the parent folder containing one).
2. Parse the semantic model (tables, columns, calculated columns, measures,
   relationships, and Row-Level Security RLS roles).
3. Parse the report (pages, visuals, fields/measures used, and Page/Report-level filters).
4. Build the full dependency graph, including RLS dependencies, relationship- and
   calculated-column-derived table links, and measure-to-measure lineage.
5. Automatically save a formatted Excel workbook with a unique timestamp (e.g. `dependency_report_20260719_164728.xlsx`) to your `Downloads` folder. (It also writes a copy to `./output/dependency_report.xlsx`).

Useful flags:

```bash
# Custom output directory (in addition to the Downloads copy)
python main.py "C:/Projects/Sales" --output ./reports

# Only print one table's dependency report to the console
python main.py "C:/Projects/Sales" --table "Fact_Sales"

# Also emit a Graphviz DOT file (dependency_graph.dot) for a visual diagram
python main.py "C:/Projects/Sales" --graph

# Do not write the Excel workbook
python main.py "C:/Projects/Sales" --no-excel

# Debug logging
python main.py "C:/Projects/Sales" --verbose
```

Render the graph with Graphviz once installed:

```bash
dot -Tpng output/dependency_graph.dot -o dependency_graph.png
```

### As a library

```python
from main import analyze_pbip

graph = analyze_pbip("C:/Projects/Sales.pbip")
print(graph.tables["Fact_Sales"].measures)
```

`analyze_pbip` never uses hardcoded absolute paths — folder discovery is
always relative to the `.pbip` file you pass in.

---

## Supported project formats

Power BI Desktop has changed the on-disk format of both artifacts over time.
This tool auto-detects and supports **both** generations of each, so it
works whether the project was last saved by an old or current version of
Desktop:

| Artifact        | Modern format (auto-detected)                       | Legacy format (auto-detected)         |
|-----------------|------------------------------------------------------|----------------------------------------|
| Semantic Model  | TMDL, folder-based (`definition/tables/*.tmdl`)       | `model.bim` (TMSL/JSON)                 |
| Report          | PBIR, folder-based (`definition/pages/**/visual.json`) | single `report.json` (sections/visualContainers) |

No folder or file names are hardcoded beyond Power BI Desktop's own
well-known suffixes (`.pbip`, `.Report`, `.SemanticModel`) and standard
internal filenames (`definition.pbir`, `model.tmdl`, `page.json`, etc.).

---

## Architecture

```
pbip_analyzer/
├── main.py                     # CLI entry point + analyze_pbip() public API
├── parser/
│   ├── pbip_loader.py          # Finds the .Report / .SemanticModel folders
│   ├── tmdl_parser.py          # Parses TMDL (+ legacy .bim) -> tables/measures/relationships/roles
│   ├── report_parser.py        # Parses PBIR (+ legacy report.json) -> pages/visuals/filters
│   ├── visual_parser.py        # Parses one visual.json -> type/title/field refs
│   └── dax_parser.py           # Regex-based DAX reference extractor
├── services/
│   ├── dependency_engine.py    # Cross-links tables/measures/visuals/pages/roles
│   └── graph_export.py         # Optional Graphviz DOT export
├── models/
│   ├── table.py                # Table dataclass
│   ├── measure.py               # Measure dataclass
│   ├── visual.py                # Visual dataclass
│   └── page.py                  # Page dataclass
├── utils/
│   ├── file_utils.py            # Safe JSON/text reading, folder discovery
│   ├── logging_config.py        # Central logging setup
│   └── exceptions.py            # PBIPAnalyzerError hierarchy
├── tests/                       # pytest unit + integration tests
└── output/                      # Default location for generated reports
```

Each layer only depends on the layer(s) below it:

`main.py` → `services` → `parser` → `utils`/`models`

This makes it straightforward to, for example, swap in a different report
format parser, or wrap `analyze_pbip()` (or `DependencyEngine` directly) in a
FastAPI endpoint without touching parsing logic.

### Pipeline

1. **`pbip_loader.load_pbip_project`** — validates the `.pbip` file and
   resolves the sibling Report/SemanticModel folders (via the pointer files
   Power BI writes, with a suffix-scan fallback).
2. **`tmdl_parser.parse_semantic_model`** — returns a `RawSemanticModel`
   (tables → columns/measures, relationships, and `roles` for RLS security filters).
3. **`report_parser.parse_report`** — returns a `RawReport` (pages →
   visuals and page/report filters), delegating each visual to **`visual_parser.parse_visual`**.
4. **`dax_parser.extract_references`** — used by the engine to figure out
   which tables/columns each measure and RLS role filter DAX expression touches.
5. **`services.dependency_engine.DependencyEngine.build()`** — combines all
   of the above into a fully cross-linked `DependencyGraph`
   (`tables`, `measures`, `visuals`, `pages`, `roles` dictionaries).

### How "where is a table used" is computed

- A table's **measures** = every measure whose DAX expression references
  that table (via `dax_parser`), plus any measure whose *home* table is that
  table (so measures with a trivial `= 1` body are still attributed).
- A table's **visuals** = every visual that either (a) directly queries a
  column/measure from that table, or (b) uses a *measure* whose DAX
  expression transitively touches that table (e.g. a visual showing "Sales
  Variance", whose DAX references both `Fact_Sales` and
  `Products`, is correctly linked to **both** tables).
- A table's **pages** = the pages containing any of the visuals above.
- A table's **related_tables** = every other table it's structurally
  connected to, from two sources:
  - **Model relationships** (`relationships.tmdl` / TMSL `relationships`) --
    linked in both directions regardless of cardinality/cross-filter
    direction.
  - **Calculated columns** whose DAX formula reaches into another table,
    most commonly via `RELATED(...)` or `RELATEDTABLE(...)` (e.g. a
    `Savings` column on `Invoice Line Item` computed as
    `RELATED(Invoice[Discount Percent]) * [Invoice Amount]` correctly links
    `Invoice Line Item` <-> `Invoice`, even though no measure or
    relationship expresses that link explicitly).
- Each **measure** also tracks `depends_on_measures` / `used_by_measures` --
  the lineage chain created when one measure references another via a bare
  `[Measure Name]` expression.

### Unused-entity detection & Safety Checks

Since the graph already knows every table/measure/column's full usage, the
engine flags anything **never referenced by a visual, filter, or RLS role** -- a quick
model-hygiene signal for identifying imported-but-unused tables, abandoned
measures, or columns nobody ever put on a report.

Columns and measures are safely protected from being marked as "unused" if they are:
- Used on any visual canvas (axes, legends, tooltips, values).
- Used in **Page-Level** or **Report-Level** filters (`filterConfig.filters`).
- Used in **Row-Level Security (RLS)** table permission DAX expressions (`tablePermission`).
- Used inside calculated column DAX expressions or measure-to-measure dependency chains.
- Used as relationship join keys between tables.

### Dependency graph diagram (optional)

Passing `--graph` writes `dependency_graph.dot` alongside the JSON reports:
table nodes, page nodes, solid edges for table -> page usage (labeled with
the connecting visual titles), dashed edges for model relationships, and
dotted edges for calculated-column cross-table references. See
`services/graph_export.py`.

### DAX parsing approach

Full DAX parsing needs a real grammar. Since dependency analysis only needs
to know *what a measure touches*, `dax_parser.py` uses two tolerant regexes:

- `Table[Column]` / `'Table Name'[Column]` → explicit, qualified references.
- `[Name]` (not preceded by an identifier/quote) → an implicit reference,
  typically to another measure. These are resolved against the full set of
  known measure names once every measure in the model has been parsed.

This covers the vast majority of real-world DAX (`SUM(...)`, `CALCULATE(...)`,
`VAR`/`RETURN`, measure-to-measure references, etc.) without the complexity
of a full parser.

### Visual field extraction approach

Rather than hardcoding the (version-specific, visual-type-specific) JSON
paths Power BI uses for query fields, `visual_parser.py` walks each
`visual.json` tree generically: any dict with sibling `"Property"` and
`"Expression"` keys is a field reference, and the owning table is found by
searching inside `"Expression"` for a nested `SourceRef.Entity`. This is
resilient to the `Column` / `Measure` / `Aggregation` / `HierarchyLevel`
wrapper variations Power BI uses across visual types, and works for both the
modern PBIR `query.queryState` shape and the legacy `prototypeQuery.Select`
shape.

---

## Output

### Console report

```
==================================================
TABLE: Fact_Sales

Columns:
* Currency
* OrderID
* SalesAmount
* Customer

Measures:
* Avg Sales
* Sales Variance
* Total Sales

Visuals:
* KPI Card
* Sales Trend
* Customer Matrix

Pages:
* Executive Dashboard
* Customer Analysis

Related Tables:
* Products
* Customers

==================================================
```

A final section flags anything never used by a visual:

```
==================================================
UNUSED ENTITIES (not referenced by any visual)

Tables:
* Customers

Measures:
* Customer Count

Columns:
* Products[ProductID]
* Products[Price]
* Customers[Region]
* Customers[CustomerName]
* Fact_Sales[OrderID]

==================================================
```

### Excel workbook (`dependency_report_[timestamp].xlsx`)

The workbook is formatted with clear headers and contains three sheets:

1. **Visual Inventory**: One row per visual showing Page Name, Visual Name, Visual Type, Direct Measures used, Dependency Tables, and Dependency Columns (including transitive lineage through measures and calculated columns).
2. **Impact Analysis**: One row per Table, Measure, Calculated Column, and Column in the model. Displays usage counts (# Visuals, # Measures, # Calc Columns), relationship flags, and an actionable classification Status (*Active Table/Measure/Column*, *No References Found*, *Bridge Table*, *Used via Relationship Only*, *System Table*).
3. **Measure Lineage**: One row per measure showing direct measure dependencies, base columns used, dependency tables, visuals utilizing the measure, other measures depending on it, and the full DAX expression.

Every run automatically downloads a new copy of the Excel workbook with a unique timestamp in the filename directly to your user `Downloads` folder, avoiding locking issues if you have a report open in Excel.

---

## Error handling

All expected failure modes raise a subclass of `PBIPAnalyzerError`
(`utils/exceptions.py`) with a clear, actionable message, and `main.py`
converts these into exit code `1` with a friendly CLI message (unexpected
errors exit `2` with a full traceback logged):

| Situation                              | Exception raised               |
|-----------------------------------------|--------------------------------|
| Path isn't a `.pbip` file or folder containing one / doesn't exist | `InvalidPBIPFileError` |
| `.pbip` JSON is corrupt                 | `InvalidPBIPFileError` (via `CorruptFileError`) |
| No `*.Report` folder found              | `ReportNotFoundError`          |
| No `*.SemanticModel` folder found       | `SemanticModelNotFoundError`   |
| A JSON/TMDL file exists but can't be parsed | `CorruptFileError`         |

---

## Running the tests

```bash
pip install -r requirements.txt
pytest tests/ -v
```

---

## Extending the tool

The architecture is intentionally split so each extension point is isolated:

- **New report/model format version** → add a new branch inside
  `tmdl_parser.parse_semantic_model` / `report_parser.parse_report`; nothing
  else needs to change since both return the same `Raw*` structures.
- **Richer DAX analysis** (e.g. distinguishing `RELATED` from a plain column
  reference) → extend `dax_parser.extract_references`.
- **New output format** (e.g. Markdown, CSV) → add a builder + writer
  function in `main.py` or `excel_export.py`; the `DependencyGraph` already has everything needed.
- **A FastAPI backend** → import `analyze_pbip` (file-based) or
  `DependencyEngine` (in-memory, if you already have parsed data) directly;
  neither has any CLI coupling baked in.

## Known limitations

- DAX parsing is regex-based, not a full grammar; it will not resolve
  references inside string literals that happen to look like `Table[Column]`,
  and does not distinguish `RELATED`/`RELATEDTABLE` traversal direction from
  a plain column reference (both simply register as "this entity touches
  that table").
- Calculation groups and hierarchies are not yet modeled as their own
  entities (only tables, columns, calculated columns, measures, and RLS roles are).
- Visuals, Page-Level filters, Report-Level filters (`filterConfig`), and Row-Level Security (RLS) filters are all fully parsed and incorporated into dependency resolution.
