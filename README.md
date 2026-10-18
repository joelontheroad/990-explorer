# IRS 990 Nonprofit Ultimate Funding & Relationship Social Graph Explorer

A high-performance Python CLI tool and standalone interactive visualizer designed to ingest IRS Form 990 filings, trace **ultimate funding lineages** (inbound and outbound grant flows), and map **corporate governance relationships** (parents, subsidiaries, siblings, and disregarded entities) of 501(c) non-profit organizations.

## Key Features

1. **Interactive Live Explorer Server (`--serve` / `-s`)**:
   - Start with `python main.py --name "Tides Foundation" --serve` (or `python main.py --serve`).
   - Automatically opens your browser at `http://127.0.0.1:8990` with real-time dynamic querying.
   - **1-Click Entity Recentering**: Click `🎯 Recenter` on any parent, sibling, or grantee (or double-click any node) to fetch 990 filings and rebuild the graph around that organization live.
   - **Animated Progress Modal**: Visual multi-step progress bar during IRS filing ingestion and lineage traversal.
   - **Breadcrumb History Trail**: Clickable navigation history to jump between explored entities.
   - **Instant Snapshot Export**: Save any dynamically explored view to an offline standalone HTML file with a single click.

2. **Standalone Portable HTML Visualizer**:
   - Zero web server required for offline viewing of generated snapshot files.
   - Generates a 100% self-contained `.html` file embedding the Vis.js Network bundle, CSS, and graph datasets.
   - Interactive slide-out drawer with organization financials, grant tables, and Schedule R corporate tree.
   - Live filters: Minimum grant dollar slider, direction filter, force-directed vs. hierarchical layouts, physics freeze.
   - Direct export to CSV, JSON, and PNG screenshot.

3. **Bidirectional & Recursive Funding Traversal**:
   - Trace upstream funders (who funds target organization backwards across multi-hop pass-throughs).
   - Trace downstream grantees (where target organization awards funds).
   - Expand Schedule R corporate hierarchy (parents, subsidiaries, siblings, disregarded entities).
   - Configurable depth (`--depth 1` to `8`), dollar threshold (`--min-grant-amt`), and tax year range.

4. **Hybrid Ingestion & High-Performance Storage**:
   - Integrated with **ProPublica Nonprofit Explorer API v2** for automated EIN resolution and filing metadata.
   - Built on **DuckDB** for lightning-fast sub-millisecond local graph querying and indexing.
   - Bulk ingestion support for IRS TEOS XML zip files and local folder scanning (e.g. `/media/ai-drive`).
   - Out-of-the-box institutional seed data covering major US foundations and grantmaker hubs.

5. **Functional Spending & Contractor Transparency (`--spending`)**:
   - Analyzes Form 990 Part IX Statement of Functional Expenses.
   - Calculates charitable efficiency: Program Services % vs. Management/Overhead % vs. Fundraising %.
   - Identifies major expenditure categories: Grants Paid, Personnel & Salaries, Professional Fees (Legal, Lobbying, PR), Office/IT, and Travel.
   - Unveils Form 990 Part VII Section B top 5 independent contractors paid over $100,000.

6. **Leadership, Officers & Cross-Board Interlocks (`--person`, `--interlocks`)**:
   - Extracts Officers, Directors, Trustees, and Key Employees from Form 990 Part VII Section A & Form 990-PF Part VIII.
   - Cross-filing entity resolution: detects when an individual serves on multiple nonprofit boards simultaneously.
   - Discovers interlocking directorates across charities and foundations.
   - Tracks titles, hours devoted per week, reportable W-2/1099 compensation, and benefits.

7. **Multi-Entity Omni-Search & Commercial Vendor Dossiers (`--search`, `--vendor`)**:
   - Unified omni-search input indexing **Nonprofit Charities**, **Board Members/Officers**, **Commercial Vendors/Contractors**, **Schedule R Corporate Affiliates**, **IRS 527 Political Organizations**, and **FEC Federal PACs / Committees**.
   - **Contractor Dossier**: Aggregates all charity clients, multi-year billings, and service descriptions for commercial firms (e.g., Arabella Advisors, law firms, IT vendors) with clickable drawer access.

8. **IRS Section 527 Political Organizations & Soft-Money PACs (`--sync-527`, `--527`)**:
   - Streams and indexes IRS Political Organization Filing and Disclosure (POFD) bulk data directly into DuckDB.
   - Captures Form 8871 notices of Section 527 political status, officers/directors, and related organizations.
   - Ingests Form 8872 periodic reports with itemized political contributions (Schedule A) and expenditures (Schedule B).

9. **Federal Election Commission (FEC) Political Committees & Super PACs (`--sync-fec`, `--fec`, `--sync-all-pacs`)**:
   - Downloads and indexes FEC bulk data across **three election cycles by default** (`2022`, `2024`, `2026` = 6 years of federal political fundraising).
   - Ingests Committee Master (`cm.txt`), Candidate Master (`cn.txt`), Candidate Linkages (`ccl.txt`), Independent Expenditures / Contributions (`itpas2.txt`), and Operating Disbursements (`oppexp.txt`).
   - Maps Super PACs (Independent Expenditure-Only), Hybrid PACs, Traditional PACs, and Connected Organizations (sponsoring corporations, labor unions, 501(c)(4)s).
   - Generates comprehensive committee dossiers detailing independent expenditures (support/oppose), direct contributions, candidate recipients, and commercial political vendor spending.

10. **Cross-Entity Political Bridges & PAC Linkages (`--pacs`, `--cross-linkages`, `--no-pacs`)**:
   - Automatically establishes, scores, and visualizes the bridges connecting 501(c)(3) charities and sister 501(c)(4) social welfare entities to political committees across three distinct legal and financial mechanisms:
     - **Bridge 1 (`connected_org` / `schedule_r_conduit`)**: Cross-references FEC `connected_org_name` and Form 8871 Part IV `irs_527_related` against non-profit entities and Schedule R corporate affiliates (detecting classic 501(c)(3) $\rightarrow$ 501(c)(4) $\rightarrow$ PAC multi-hop conduit pipelines).
     - **Bridge 2 (`shared_leadership`)**: Matches Form 990 Part VII officers, directors, and trustees against FEC committee treasurers and IRS Section 527 directors/officers.
     - **Bridge 3 (`shared_contractor`)**: Identifies commercial political vendors, strategy firms, and media consultants serving both charities ($>\$100\text{k}$ on Form 990 Part VII Section B) and political committees ($>\$10\text{k}$ in disbursements).
   - **Interactive Visualizer Integration**: Connected PACs appear as crimson hexagon nodes (`#ef4444`) attached via dashed coral/crimson linkage edges, with a dedicated `[🗳️ PACs]` tab in the slide-out drawer providing 1-click access to complete FEC and 527 dossiers.


---

## Quick Start

### Runtime & Virtual Environment

The repository includes a pre-configured local virtual environment (`.venv`) with all dependencies (`duckdb`, `requests`, `jinja2`, `pytest`) pre-installed. `main.py` features **automatic virtual environment self-reactivation**—when invoked with `python3 main.py`, it automatically detects `.venv` and seamlessly pivots execution into the virtual environment without requiring manual activation.

You can launch the program using any of the following methods:

```bash
# Method 1: Using python3 (Recommended — automatically uses .venv)
python3 main.py --name "Tides Foundation" --serve

# Method 2: Direct executable script
./main.py --name "Tides Foundation" --serve

# Method 3: Shell runner script
./run.sh --name "Tides Foundation" --serve

# Method 4: Activate the virtual environment in your shell
source .venv/bin/activate
python main.py --name "Tides Foundation" --serve
```

---

### Usage Examples

#### 1. Explore The Tides Foundation (Default Bidirectional Traversal)
```bash
python3 main.py --name "Tides Foundation" --depth 4 --min-grant-amt 50000
```
*Generates `output/tides_foundation_funding.html`.*

#### 2. Trace Upstream Funders Only (Backward Traversal)
```bash
python3 main.py --name "Tides Foundation" --direction upstream --depth 3
```

#### 3. Trace Downstream Grantees Only (Forward Traversal)
```bash
python3 main.py --name "Ford Foundation" --direction downstream --depth 2 --min-grant-amt 100000
```

#### 4. Launch Live Interactive Explorer Server (Dynamic Recentering & Live Queries)
```bash
python3 main.py --name "Tides Foundation" --serve
# Or via the 'serve' subcommand with optional --no-browser flag:
python3 main.py serve --name "Tides Foundation" --no-browser
```
*Starts local server at `http://127.0.0.1:8990`, automatically opens your browser (unless `--no-browser` or headless), and enables:*
- **1-Click Dynamic Recentering**: Click `🎯 Recenter` on any parent, sibling, or grant partner (or double-click any node) to fetch 990 filings and rebuild the graph around that entity in real time.
- **Active Graph Layers**: Instantaneous HUD layer toggles (`💸 Grants & Funding`, `🏢 Schedule R Affiliates`, `🗳️ Political PACs & 527s`) with sub-millisecond client-side filtering.
- **PACs & Candidate Visualization**: Crimson hexagons (⬡) for PACs, violet diamonds (◆) for federal candidates, and directed dashed arrows for independent expenditures (🟢 Support, 🔴 Oppose).
- **Dynamic Graph Injection**: 1-click action buttons (`➕ Inject PAC into Graph`, `🎯 Center in Map`, `➕ Graph` on candidates) to inject political conduits and campaign spending into the network on demand.
- **Self-Contained Offline Export**: Standalone `.html` snapshots pre-bundle all PAC linkages, Form 8871 profiles, and FEC dossiers directly in `GRAPH_DATA` for 100% offline inspection.
- **Animated Progress Modal**: Visual multi-step progress bar during IRS filing ingestion and lineage traversal.
- **Breadcrumb History**: Quick jump back through past explored organizations.
- **Snapshot Export**: Save any dynamically explored view to a standalone `.html` file directly from the browser.

#### 5. Ingest Local IRS XML or ZIP Archives
```bash
python main.py --ingest-dir /media/ai-drive/990_xmls/
# or ingest a single TEOS zip file:
python main.py --ingest-zip /media/ai-drive/2023_TEOS_XML_01A.zip
```

#### 6. Check Database Ingestion Status & Statistics
```bash
python main.py --status
```
*Displays the last load timestamp and comprehensive metrics for every data source (BMF, Seeds, Grants, Schedule R, and Dynamic Filings).*

#### 7. Analyze Nonprofit Spending Breakdown & Top Contractors
```bash
python main.py --name "Tides Foundation" --spending
```
*Outputs Part IX functional expense allocation (Program % vs Overhead % vs Fundraising %), salary totals, professional fees, and top contractors > $100,000.*

#### 8. Investigate an Individual Across Filings & Board Interlocks
```bash
python main.py --person "Amanda Keton"
```
*Discovers all organizations where this individual appears as an officer, director, trustee, or key employee, their titles, hours, compensation, and detected interlocks.*

#### 9. Discover Interlocking Directorates Across All Nonprofits
```bash
python main.py --interlocks
```
*Finds pairs of tax-exempt entities in the database that share common board leadership or key officers.*

#### 10. Multi-Entity Omni-Search
```bash
python main.py --search "Arabella"
```
*Unified search across Nonprofits, Board Members/Officers, Commercial Vendors, Corporate Affiliates, and 527 Political Organizations.*

#### 11. Commercial Contractor & Vendor Dossier
```bash
python main.py --vendor "Arabella Advisors"
```
*Aggregates all charity clients, billing totals, active years, and services for commercial vendors and advisory firms.*

#### 12. Search & Profile IRS Section 527 Political Organizations
```bash
python main.py --527 "Majority Forward"
```
*Displays Form 8871 registration, officers, directors, related entities, and Form 8872 contributions and expenditures.*

#### 13. Synchronize FEC Political Committees & PACs
```bash
# Ingest 3 election cycles (2022, 2024, 2026) covering 6 years of federal PAC filings:
python main.py --sync-fec

# Or specify custom election cycles:
python main.py --sync-fec --fec-cycles 2020,2022,2024,2026

# Or synchronize BOTH IRS 527 POFD and FEC PACs in a single run:
python main.py --sync-all-pacs
```

#### 14. Search & Profile FEC Committee / Super PAC
```bash
python main.py --fec "Senate Majority PAC"
# or inspect by FEC Committee ID:
python main.py --fec C00495028
```
*Displays committee metadata, connected sponsoring organizations (501(c)(4)s / labor unions), top independent expenditures (support/oppose), direct contributions, and commercial political disbursements.*

#### 15. Discover Connected PACs, 527s, Shared Leaders & Vendors
```bash
python main.py --pacs "Tides Foundation"
# or alias:
python main.py --links "Majority Forward"
```
*Scans and reports all direct and Schedule R conduit bridges connecting the organization to federal PACs and soft-money 527s, complete with confidence scores and evidence breakdowns.*

#### 16. Database-Wide Cross-Entity Linkage Resolution
```bash
python main.py --cross-linkages
```
*Performs high-speed indexed joins across the entire DuckDB database to identify every charity-to-PAC connection across connected organizations, leadership interlocks, and shared political vendors.*

#### 17. Exclude PACs from Funding Graph
```bash
python main.py --name "Majority Forward" --no-pacs
```
*Traverses the non-profit funding network while suppressing PAC nodes and political linkage edges.*

#### 18. Open Portable HTML
Simply double-click the generated `.html` file or open it in any web browser:
```bash
xdg-open output/tides_foundation_funding.html
```

---

## Bulk Data Population & Maintenance Guide

To achieve instant sub-millisecond graph queries without relying on remote API calls or hitting rate limits, you can populate the local DuckDB database with bulk IRS datasets.

### 1. Initial Data Population

Run the following command to download and ingest the official IRS Exempt Organizations Business Master File:

```bash
# Ingest all 1.85M+ US tax-exempt organizations from the IRS Master File
python main.py --sync-bmf

# Or synchronize both BMF data and institutional seed grantmakers:
python main.py --sync-all
```

*What happens during initial population:*
- Downloads the 4 official IRS EO BMF regional extract files (`eo1.csv` through `eo4.csv`).
- Streams and indexes all **1,850,000+ organizations** directly into DuckDB table `irs_bmf`.
- Compressed storage footprint is only **~75 MB in DuckDB**.
- Automatically indexes EINs, organization names, tax-exempt subsections (`501(c)(3)`), and private foundation classifications.
- Records the sync timestamp, record count, and source details in the database metadata log.

*Smart Pre-Flight Freshness & Conditional Skip:*
- `--sync-all` and `--sync-bmf` automatically perform a zero-bandwidth HTTP `HEAD` probe to official IRS servers before downloading.
- If your local database is already synchronized with the latest IRS monthly release, it displays `✅ [UP TO DATE]` and **skips both downloading and database re-indexing**, completing in `< 1 second`.
- If the IRS has released a newer monthly extract, it invalidates any stale files, downloads the latest release, and synchronizes DuckDB.
- To bypass the freshness check and force a complete re-download and re-index, append `--force-download`:
```bash
python main.py --sync-all --force-download
```

### 2. Recommended Update Frequency

| Data Source | Agency Publication Schedule | Recommended Update Frequency | Command to Update |
| :--- | :--- | :--- | :--- |
| **IRS Business Master File (EO BMF)** | **Monthly** (typically published on the 2nd Monday of each month) | **Monthly or Quarterly** | `python main.py --sync-bmf` |
| **IRS Section 527 Political Orgs (POFD)** | **Weekly** (published every Saturday morning) | **Monthly or Quarterly** | `python main.py --sync-527` |
| **FEC Political Committees & PACs** | **Regularly / Nightly** by the Federal Election Commission | **Monthly or Quarterly** | `python main.py --sync-fec` |
| **IRS Electronic 990 Filings (TEOS XML)** | **Monthly** batches of e-filed returns | **Quarterly or Semi-Annually** | `python main.py --sync-all`<br>or `python main.py --ingest-zip <FILE.zip>` |
| **On-Demand Filings Cache** | Live via IRS S3 / ProPublica API | **Automatic** (cached permanently upon node expansion) | Automatically updated when exploring nodes |

### 3. Monitoring Database Health & Status

You can inspect the database at any time to verify when data was last loaded and view statistics organized by data source:

```bash
python main.py --status
# or alias:
python main.py --db-stats
```

The report provides:
- **Last Ingestion Date & Time** for each data source (BMF, Institutional Seeds, 527 POFD, FEC PACs, TEOS XML archives, and On-Demand lookups).
- **Data Source Statistics**: Total registered charities, 501(c)(3) counts, private foundations, reported assets & revenue from the BMF.
- **Grants & Relationship Metrics**: Total grant count, dollar volume, unique grantors, unique recipients, and breakdown by schedule (`Schedule I` vs `990-PF Part XV`).
- **Section 527 Political Org Metrics**: Total registered 527 committees, Form 8872 reports, contributions count and volume, and expenditures count and volume.
- **FEC Political Committee Metrics**: Total federal committees, Super PACs, hybrid PACs, candidates, candidate linkages, independent expenditure transactions, and operating disbursements.
- **Database Footprint**: Exact file path and size on disk.

### 4. Checking If Downloaded Data Is Out Of Date

To verify whether newer data has been released on official IRS servers without needlessly downloading gigabytes of files, run:

```bash
python main.py --check-updates
# or aliases:
python main.py --check-freshness
python main.py --updates
```

*How it works:*
- Sends lightweight, zero-bandwidth HTTP `HEAD` probes (~500 bytes) to official IRS servers (`https://www.irs.gov`).
- Extracts the IRS's exact `Last-Modified` publication timestamp.
- Compares the IRS release date with your local DuckDB ingestion timestamps.
- Flags datasets as:
  - `✅ UP TO DATE`: Local data matches or is newer than the IRS release.
  - `⚠️ OUT OF DATE`: Local data is behind upstream IRS releases (details exact days behind and command to update).
  - `❌ NOT INGESTED`: Identifies datasets that have not been populated yet.
  - `⚠️ POSSIBLY STALE`: Used when offline if data exceeds recommended freshness thresholds (35 days for BMF, 14 days for 527 POFD).

---

## CLI Options

| Argument | Flag | Default | Description |
| :--- | :--- | :--- | :--- |
| `--name` | `-n` | `None` | Target organization name (auto-resolves EIN via ProPublica) |
| `--ein` | `-e` | `None` | Target organization EIN (e.g. `51-0198509`) |
| `--search` | | `None` | Multi-entity omni-search across nonprofits, people, vendors, affiliates, 527s |
| `--vendor`, `--contractor` | | `None` | Aggregate commercial contractor profile & client charities across filings |
| `--527`, `--pac` | | `None` | Search & inspect IRS Section 527 political organization profile |
| `--fec`, `--committee` | | `None` | Search & inspect FEC political committee / Super PAC dossier |
| `--status`, `--db-stats` | | `False` | Display last data load timestamps & statistics by data source, then exit |
| `--check-updates`, `--check-freshness` | | `False` | Probe upstream IRS & FEC servers to check if local data is out of date |
| `--spending` | | `False` | Display Part IX functional expense allocation and top contractors |
| `--person` | | `None` | Search for an officer/trustee to display roles, comp, and board interlocks |
| `--interlocks` | | `False` | Discover interlocking directorates (nonprofits sharing board members) |
| `--sync-bmf` | | `False` | Download & ingest official IRS Business Master File (1.85M charities) |
| `--sync-527` | | `False` | Download & ingest IRS Section 527 Political Organizations (POFD bulk zip) |
| `--sync-527-split` | | `False` | Synchronize 527 POFD using 4 smaller alphabetical archives (A-G, H-M, N-R, S-Z) |
| `--sync-fec` | | `False` | Download & ingest FEC bulk data (default: 3 cycles: 2022, 2024, 2026) |
| `--fec-cycles` | | `2022,2024,2026` | Comma-separated list of election cycles to synchronize |
| `--fec-skip-exp` | | `False` | Skip heavy transaction files for lightweight committee-only sync |
| `--sync-all-pacs` | | `False` | Synchronize both IRS 527 POFD and FEC PACs in a single run |
| `--sync-all` | | `False` | Synchronize all bulk datasets (BMF, seeds, 527 POFD, and FEC PACs) |
| `--force-download` | | `False` | Force re-download of bulk files even if cached locally |
| `--serve` | `-s` | `False` | Launch interactive web server with dynamic recentering & live search |
| `--daemon` | | `False` | Run server as a detached background daemon process |
| `--port` | `-p` | `8990` | Port for interactive web server |
| `--host` | | `127.0.0.1` | Host address for interactive web server |
| `--no-browser` | | `False` | Do not automatically open browser when starting server |
| `--depth` | `-d` | `4` | Maximum recursive funding hop depth (up to 8) |
| `--direction` | | `both` | `both`, `upstream` (funders), or `downstream` (grantees) |
| `--min-grant-amt`| `-m` | `10000.0` | Minimum grant dollar threshold |
| `--start-year` | | `None` | Filter grants from starting tax year |
| `--end-year` | | `None` | Filter grants up to ending tax year |
| `--top-n` | | `25` | Maximum branches per node hop (avoids node explosion) |
| `--output` | `-o` | Auto | Output HTML filepath |
| `--ingest-dir` | | `None` | Scan and ingest directory of XML or ZIP files |
| `--ingest-zip` | | `None` | Ingest specific TEOS ZIP archive directly |
| `--db-path` | | Local | Path to DuckDB database file |
| `--no-seeds` | | `False` | Skip loading default institutional seed dataset |
| `--no-schedule-r`| | `False` | Exclude Schedule R corporate relationships |
| `--no-pacs` | | `False` | Exclude connected PACs and 527 committees from graph |
| `--pacs`, `--links` | | `None` | Discover and display all connected PACs, 527s, leaders & vendors |
| `--cross-linkages` | | `False` | Run database-wide cross-entity resolution scan |

---

## 🛡️ Defensive Patent Publication & Prior Art Disclosure

This project adheres to a **Defensive Open Source Intellectual Property Strategy** under 35 U.S.C. § 102(a)(1) and international patent treaties. All methods, data structures, algorithms, and architectures implemented in this repository—including the **3-Bridge Political Linkage Engine**, **Anchor-Centric Bidirectional Traversal**, **Zero-Bandwidth Pre-Flight Freshness Probing**, and **Self-Contained Offline Standalone Graph Packaging**—are irrevocably published as public prior art.

For detailed technical claims, mathematical heuristics, and prior art citations, see:
📄 **[DEFENSIVE_PUBLICATION.md](DEFENSIVE_PUBLICATION.md)**

---

## 📄 License & Source Code Notice

This project is licensed under the **GNU Affero General Public License v3.0 or later** ([GNU AGPLv3+](LICENSE)).

In accordance with Section 13 of GNU AGPLv3, the corresponding source code for this software is publicly available at:
<https://github.com/joelontheroad/990-explorer>

---

## Running Automated Tests

```bash
source .venv/bin/activate
pytest -v
```

