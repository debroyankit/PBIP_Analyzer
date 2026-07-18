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
python main.py "C:/Projects/Procurement.pbip"
```

This will:

1. Locate the project's Report and Semantic Model folders automatically.
2. Parse the semantic model (tables, columns, measures, relationships).
3. Parse the report (pages, visuals, fields/measures used).
4. Build the full dependency graph.
5. Print a per-table report to the console.
6. Write `./output/dependency_report.json` (and a richer
   `dependency_report_full.json`, see [Output](#output) below).

You can also point at a custom output directory:

```bash
python main.py "C:/Projects/Procurement.pbip" --output ./reports --verbose
```

### As a library

```python
from main import analyze_pbip

graph = analyze_pbip("C:/Projects/Procurement.pbip")
print(graph.tables["Fact Procurement"].measures)
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
│   ├── tmdl_parser.py          # Parses TMDL (+ legacy .bim) -> tables/measures/relationships
│   ├── report_parser.py        # Parses PBIR (+ legacy report.json) -> pages/visuals
│   ├── visual_parser.py        # Parses one visual.json -> type/title/field refs
│   └── dax_parser.py           # Regex-based DAX reference extractor
├── services/
│   └── dependency_engine.py    # Cross-links tables/measures/visuals/pages
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
   (tables → columns/measures, plus relationships).
3. **`report_parser.parse_report`** — returns a `RawReport` (pages →
   visuals), delegating each visual to **`visual_parser.parse_visual`**.
4. **`dax_parser.extract_references`** — used by the engine to figure out
   which tables/columns each measure's DAX expression touches.
5. **`services.dependency_engine.DependencyEngine.build()`** — combines all
   of the above into a fully cross-linked `DependencyGraph`
   (`tables`, `measures`, `visuals`, `pages` dictionaries).

### How "where is a table used" is computed

- A table's **measures** = every measure whose DAX expression references
  that table (via `dax_parser`), plus any measure whose *home* table is that
  table (so measures with a trivial `= 1` body are still attributed).
- A table's **visuals** = every visual that either (a) directly queries a
  column/measure from that table, or (b) uses a *measure* whose DAX
  expression transitively touches that table (e.g. a visual showing "Purchase
  Price Variance", whose DAX references both `Fact Procurement` and
  `Dim_Material`, is correctly linked to **both** tables).
- A table's **pages** = the pages containing any of the visuals above.

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
TABLE: Fact Procurement

Columns:
* Currency
* POID
* Spend
* Vendor

Measures:
* Avg Spend
* Purchase Price Variance
* Total Spend

Visuals:
* KPI Card
* Spend Trend
* Supplier Matrix

Pages:
* Executive Dashboard
* Supplier Analysis

==================================================
```

### `dependency_report.json` (primary, table-keyed)

Matches the required shape exactly — one entry per table:

```json
{
  "Fact Procurement": {
    "columns": ["Currency", "POID", "Spend", "Vendor"],
    "measures": ["Avg Spend", "Purchase Price Variance", "Total Spend"],
    "visuals": ["KPI Card", "Spend Trend", "Supplier Matrix"],
    "pages": ["Executive Dashboard", "Supplier Analysis"]
  }
}
```

### `dependency_report_full.json` (extended, for deeper analysis / an API)

Adds full detail for every entity type — including each measure's DAX text
and referenced tables/columns, and every visual's type/page:

```json
{
  "tables": { "...": "same shape as above" },
  "measures": {
    "Purchase Price Variance": {
      "table": "Fact Procurement",
      "dax": "VAR CurrentPrice = SUM('Fact Procurement'[Spend])\n...",
      "referenced_tables": ["Dim_Material", "Fact Procurement"],
      "referenced_columns": ["Dim_Material[StandardCost]", "Fact Procurement[Spend]"],
      "visuals": ["Supplier Matrix"],
      "pages": ["Supplier Analysis"]
    }
  },
  "visuals": {
    "visSupplierMatrix": {
      "title": "Supplier Matrix",
      "type": "pivotTable",
      "page": "Supplier Analysis",
      "tables": ["Dim_Material", "Fact Procurement"],
      "columns": ["Fact Procurement[Spend]", "Fact Procurement[Vendor]"],
      "measures": ["Purchase Price Variance"]
    }
  },
  "pages": {
    "Supplier Analysis": {
      "visuals": ["Supplier Matrix"],
      "tables": ["Dim_Material", "Fact Procurement"]
    }
  }
}
```

A sample project and its generated output are included under
[`sample_project/`](./sample_project) and [`sample_output/`](./sample_output).

---

## Error handling

All expected failure modes raise a subclass of `PBIPAnalyzerError`
(`utils/exceptions.py`) with a clear, actionable message, and `main.py`
converts these into exit code `1` with a friendly CLI message (unexpected
errors exit `2` with a full traceback logged):

| Situation                              | Exception raised               |
|-----------------------------------------|--------------------------------|
| Path isn't a `.pbip` file / doesn't exist / is a `.pbix` | `InvalidPBIPFileError` |
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
- **Richer DAX analysis** (e.g. detecting `RELATED`/`RELATEDTABLE` traversal
  direction) → extend `dax_parser.extract_references`.
- **New output format** (e.g. CSV, Markdown, a graph/DOT file) → add a
  `build_*` + writer function in `main.py` alongside
  `build_table_summary` / `write_json_reports`; the `DependencyGraph` already
  has everything needed.
- **A FastAPI backend** → import `analyze_pbip` (file-based) or
  `DependencyEngine` (in-memory, if you already have parsed data) directly;
  neither has any CLI or filesystem-output coupling baked in beyond writing
  the two JSON files, which is trivially optional.

## Known limitations

- DAX parsing is regex-based, not a full grammar; it will not resolve
  references inside string literals that happen to look like `Table[Column]`,
  and does not model `RELATED`/`RELATEDTABLE` traversal direction separately
  from a plain column reference.
- Calculated columns and calculation groups are not yet modeled as separate
  entities (only measures and columns are).
- Visual-level/page-level *filters* are not currently walked for field
  references — only the visual's own query fields are (this can be added by
  extending `visual_parser._extract_field_refs` to also scan a visual's
  `filterConfig`, since the walker is already generic).
