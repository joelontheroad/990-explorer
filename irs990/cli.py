# SPDX-FileCopyrightText: 2026 990-Explorer Authors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Command-Line Interface (CLI) for IRS 990 Nonprofit Funding & Relationship Explorer.

Architectural Purpose:
    Provides the primary user interface and argument parsing for graph traversal,
    bulk dataset synchronization (EO BMF, 527 POFD, FEC bulk), omni-search,
    specialized dossier reports, and interactive web server orchestration.

Security Invariants:
    - Binds local servers strictly to 127.0.0.1 by default.
    - Sanitizes process invocations with discrete argument arrays (preventing CWE-78).
    - Preserves terminal hygiene across interrupts and standard stream redirection.
    - Routes user diagnostics and clickable URLs to stderr per Directive 3.
"""

import argparse
import sys
import os
import logging
from typing import Optional

from . import __version__
from .models import OrganizationNode
from .storage import IRS990Storage, DEFAULT_DB_PATH
from .client import ProPublicaClient
from .seeds import load_seed_data
from .traversal import FundingTraversalEngine
from .visualizer import VisualizerGenerator
from .bulk import BulkIngester
from .parser import clean_ein
from .bmf import BMFIngester
from .pofd import POFDIngester
from .fec import FECIngester, DEFAULT_FEC_CYCLES

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger("irs990-explorer")


def restore_terminal() -> None:
    """Restore terminal attributes to canonical, echoing state with visible cursor.

    Inspects standard input, output, and error streams for active TTY file descriptors,
    resets termios flags, and issues stty sane and ANSI cursor unhide sequences.
    Safe to invoke multiple times during signal handling or clean shutdown.
    """
    try:
        import termios
        for stream in (sys.stdin, sys.stdout, sys.stderr):
            try:
                # SECURITY: Verify TTY capability before issuing termios control sequences
                if stream and hasattr(stream, "fileno") and stream.isatty():
                    fd = stream.fileno()
                    attrs = termios.tcgetattr(fd)
                    # Input modes: map CR to NL, enable start/stop output control
                    attrs[0] |= (termios.ICRNL | termios.IXON)
                    # Output modes: post-process output, map NL to CR-NL
                    attrs[1] |= (termios.OPOST | termios.ONLCR)
                    # Control modes: enable receiver, 8-bit chars
                    attrs[2] |= (termios.CREAD | termios.CS8)
                    # Local modes: echo, canonical input, signals, echo erase, echo kill, extended input processing
                    attrs[3] |= (termios.ECHO | termios.ICANON | termios.ISIG | termios.IEXTEN | termios.ECHOE | termios.ECHOK)
                    termios.tcsetattr(fd, termios.TCSANOW, attrs)
            except Exception:
                pass
    except Exception:
        pass

    try:
        import subprocess
        # SECURITY: Discrete array with timeout to prevent hung processes on shutdown
        subprocess.run(["stty", "sane"], stdin=sys.stdin, stdout=sys.stdout, stderr=sys.stderr, timeout=0.5, check=False)
    except Exception:
        try:
            os.system("stty sane 2>/dev/null")
        except Exception:
            pass

    try:
        sys.stdout.write("\033[?25h\033[0m")
        sys.stdout.flush()
    except Exception:
        pass


def setup_terminal_hygiene() -> None:
    """Configure terminal stream encoding and register cleanup signal handlers.

    Reconfigures standard output and standard error streams to UTF-8 encoding,
    registers atexit cleanup, and binds signal handlers for SIGINT, SIGTERM, and SIGHUP.
    """
    for stream in (sys.stdout, sys.stderr):
        if stream and hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8")
            except Exception:
                pass

    if not sys.stdin.isatty():
        return

    import atexit
    import signal

    atexit.register(restore_terminal)

    def _sig_handler(signum, frame):
        restore_terminal()
        signal.signal(signum, signal.SIG_DFL)
        os.kill(os.getpid(), signum)

    for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        try:
            signal.signal(sig, _sig_handler)
        except Exception:
            pass


def parse_args(args: Optional[list] = None) -> argparse.Namespace:
    """Parse and validate command-line arguments for graph traversal and server operations.

    Configures top-level flags and subcommands (such as 'serve' with '--no-browser'),
    normalizing dual invocation styles for interactive server launching.

    Args:
        args: Command-line arguments to parse. If None, defaults to sys.argv[1:].

    Returns:
        Populated namespace containing parsed arguments.
    """
    parser = argparse.ArgumentParser(
        description="IRS 990 Ultimate Funding & Relationship Social Graph Explorer",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )

    parser.add_argument(
        "--version", "-v",
        action="version",
        version=f"irs990-explorer {__version__} (GNU AGPLv3)\nSource Code (GNU AGPLv3): https://github.com/joelontheroad/990-explorer",
        help="Show program version, license information (GNU AGPLv3), and repository URL"
    )

    target_group = parser.add_mutually_exclusive_group(required=False)
    target_group.add_argument(
        "--name", "-n",
        type=str,
        help="Target organization name (e.g. 'Tides Foundation')"
    )
    target_group.add_argument(
        "--ein", "-e",
        type=str,
        help="Target organization EIN (e.g. '51-0198509')"
    )

    parser.add_argument(
        "--depth", "-d",
        type=int,
        default=4,
        help="Recursive traversal depth limit (number of funding hops, e.g. 1 to 8)"
    )

    parser.add_argument(
        "--direction",
        type=str,
        choices=["both", "upstream", "downstream"],
        default="both",
        help="Funding flow direction: 'upstream' (funders), 'downstream' (grantees), or 'both'"
    )

    parser.add_argument(
        "--min-grant-amt", "-m",
        type=float,
        default=10000.0,
        help="Ignore grants below this threshold (in USD)"
    )

    parser.add_argument(
        "--years", "-y",
        type=int,
        default=10,
        help="Look back N tax years"
    )

    parser.add_argument(
        "--start-year",
        type=int,
        default=None,
        help="Filter grants starting from tax year (e.g. 2018)"
    )

    parser.add_argument(
        "--end-year",
        type=int,
        default=None,
        help="Filter grants up to tax year (e.g. 2024)"
    )

    parser.add_argument(
        "--top-n",
        type=int,
        default=25,
        help="Max branches per node hop (keeps graph readable and responsive)"
    )

    parser.add_argument(
        "--output", "-o",
        type=str,
        default=None,
        help="Output HTML filepath (e.g. 'output/tides_foundation_funding.html')"
    )

    parser.add_argument(
        "--db-path",
        type=str,
        default=DEFAULT_DB_PATH,
        help="Path to local DuckDB database"
    )

    parser.add_argument(
        "--ingest-dir",
        type=str,
        default=None,
        help="Directory of IRS 990 XMLs or ZIP files to ingest into database"
    )

    parser.add_argument(
        "--ingest-zip",
        type=str,
        default=None,
        help="Specific IRS TEOS ZIP archive to stream into database"
    )

    parser.add_argument(
        "--status", "--db-stats",
        action="store_true",
        dest="status",
        help="Display last data load timestamps and comprehensive database statistics organized by data source, then exit"
    )

    parser.add_argument(
        "--check-updates", "--check-freshness", "--updates",
        action="store_true",
        dest="check_updates",
        help="Probe upstream IRS servers (via zero-bandwidth HTTP HEAD) to check if local data is out of date, then exit"
    )

    parser.add_argument(
        "--sync-bmf",
        action="store_true",
        help="Download and ingest the official IRS Exempt Organizations Business Master File (EO BMF) with ~1.85M charities"
    )

    parser.add_argument(
        "--sync-527",
        action="store_true",
        help="Download and ingest the official IRS Section 527 Political Organizations (POFD) dataset with Forms 8871 & 8872"
    )

    parser.add_argument(
        "--sync-fec",
        action="store_true",
        help="Download and ingest Federal Election Commission (FEC) bulk data (default: 3 election cycles: 2022, 2024, 2026)"
    )

    parser.add_argument(
        "--fec-cycles",
        type=str,
        default=None,
        help="Comma-separated list of election cycles to synchronize (e.g. '2022,2024,2026')"
    )

    parser.add_argument(
        "--fec-skip-exp",
        action="store_true",
        help="Skip downloading large transaction and operating expenditure files for lightweight committee-only sync"
    )

    parser.add_argument(
        "--sync-all-pacs",
        action="store_true",
        help="Synchronize both IRS Section 527 Political Organizations and FEC federal PACs"
    )

    parser.add_argument(
        "--sync-all",
        action="store_true",
        help="Synchronize all bulk datasets (IRS BMF, seeds, IRS 527 POFD, and FEC political committees)"
    )

    parser.add_argument(
        "--person",
        type=str,
        default=None,
        help="Search for an individual (officer, director, trustee) across all filings to find roles, compensation, and cross-board interlocks"
    )

    parser.add_argument(
        "--vendor", "--contractor",
        type=str,
        default=None,
        dest="vendor",
        help="Search for a commercial contractor/vendor across all filings to find hiring charities, services, and total billings"
    )

    parser.add_argument(
        "--527", "--pac",
        type=str,
        default=None,
        dest="pac_527",
        help="Inspect an IRS Section 527 political organization (by EIN, Form ID, or name) to view filings, officers, and connections"
    )

    parser.add_argument(
        "--fec", "--committee",
        type=str,
        default=None,
        dest="fec_cmte",
        help="Inspect a Federal Election Commission (FEC) committee (Super PAC, PAC, Campaign) by ID or name"
    )

    parser.add_argument(
        "--search",
        type=str,
        default=None,
        help="Unified multi-entity search across nonprofits, board leaders, contractors, affiliates, and 527 political committees"
    )

    parser.add_argument(
        "--spending",
        action="store_true",
        help="Display Part IX functional spending breakdown and top independent contractors for the target organization"
    )

    parser.add_argument(
        "--interlocks",
        action="store_true",
        help="List detected interlocking directorates (nonprofits that share common board members or officers)"
    )

    parser.add_argument(
        "--force-download",
        action="store_true",
        help="Force re-download of bulk files even if already cached locally"
    )

    parser.add_argument(
        "--no-seeds",
        action="store_true",
        help="Do not load default institutional seed foundations and grants"
    )

    parser.add_argument(
        "--no-schedule-r",
        action="store_true",
        help="Exclude Schedule R corporate relationships from graph"
    )

    parser.add_argument(
        "--no-pacs",
        action="store_true",
        help="Exclude connected PACs and 527 political committees from the graph"
    )

    parser.add_argument(
        "--pacs", "--pac-bridges", "--links",
        type=str,
        default=None,
        dest="pac_links",
        help="Discover and display all connected PACs, 527s, shared leaders, and vendors for an organization"
    )

    parser.add_argument(
        "--cross-linkages",
        action="store_true",
        help="Run database-wide cross-entity resolution to identify all charity-to-PAC linkages"
    )

    parser.add_argument(
        "--serve", "-s",
        action="store_true",
        help="Start local interactive explorer server enabling live recentering and real-time ProPublica queries"
    )

    parser.add_argument(
        "--port", "-p",
        type=int,
        default=8990,
        help="Port for local interactive explorer server (default: 8990)"
    )

    parser.add_argument(
        "--host",
        type=str,
        default="127.0.0.1",
        help="Host address for local interactive explorer server (default: 127.0.0.1)"
    )

    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="Do not automatically launch web browser when running server"
    )

    parser.add_argument(
        "--daemon",
        action="store_true",
        help="Run interactive explorer server as a detached background daemon process"
    )

    subparsers = parser.add_subparsers(dest="subcommand", help="Available subcommands")
    serve_parser = subparsers.add_parser(
        "serve",
        help="Start local interactive explorer server",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    serve_parser.add_argument(
        "--port", "-p",
        type=int,
        default=8990,
        help="Port for local interactive explorer server"
    )
    serve_parser.add_argument(
        "--host",
        type=str,
        default="127.0.0.1",
        help="Host address for local interactive explorer server"
    )
    serve_parser.add_argument(
        "--ein", "-e",
        type=str,
        default=None,
        help="Target organization EIN"
    )
    serve_parser.add_argument(
        "--name", "-n",
        type=str,
        default=None,
        help="Target organization name"
    )
    serve_parser.add_argument(
        "--db-path",
        type=str,
        default=DEFAULT_DB_PATH,
        help="Path to local DuckDB database"
    )
    serve_parser.add_argument(
        "--no-browser",
        action="store_true",
        help="Do not automatically launch web browser when running server"
    )
    serve_parser.add_argument(
        "--daemon",
        action="store_true",
        help="Run interactive explorer server as a detached background daemon process"
    )

    parsed = parser.parse_args(args)
    if parsed.subcommand == "serve":
        parsed.serve = True
    return parsed


def format_currency(val: float) -> str:
    """Format numerical monetary amounts into abbreviated human-readable currency strings.

    Args:
        val: Numerical dollar value.

    Returns:
        Formatted currency string with appropriate magnitude suffix (e.g., Million, Billion).
    """
    if val >= 1_000_000_000_000:
        return f"${val / 1_000_000_000_000:.2f} Trillion"
    if val >= 1_000_000_000:
        return f"${val / 1_000_000_000:.2f} Billion"
    if val >= 1_000_000:
        return f"${val / 1_000_000:.2f} Million"
    return f"${val:,.2f}"


def display_database_status(storage: IRS990Storage) -> None:
    """Display comprehensive database report including sync history and table statistics.

    Args:
        storage: Active DuckDB storage interface instance.
    """
    stats = storage.get_database_stats()

    print("\n" + "=" * 76)
    print("      📊 IRS 990 EXPLORER — DATABASE STATUS & INGESTION REPORT")
    print("=" * 76)
    print(f" 💾 Database File:     {stats['db_path']}")
    print(f" 📦 Storage Footprint: {stats['db_size_mb']:.2f} MB ({stats['db_size_bytes']:,} bytes)")
    print(f" 🕒 Report Timestamp:  {stats['timestamp'].strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 76)

    # 1. Ingested Data Sources & Sync History
    print("\n[1] 📥 DATA SOURCES & INGESTION TIMESTAMPS")
    print("-" * 76)
    sources = stats.get("sources", [])
    if not sources:
        print("  ℹ️  No sync history recorded yet.")
        print("  💡 Run 'python main.py --sync-all' or 'python main.py --sync-bmf' to populate bulk data.")
    else:
        source_icons = {
            "IRS_BMF": "🏛️ ",
            "SEEDS": "🌱",
            "ON_DEMAND_XML": "⚡",
            "BULK_DIR_INGEST": "📁"
        }
        for s in sources:
            icon = source_icons.get(s["source_id"], "📦" if not s["source_id"].startswith("ZIP_") else "🗜️")
            sync_dt = s['last_synced_at'].strftime('%Y-%m-%d %H:%M:%S') if hasattr(s['last_synced_at'], 'strftime') else str(s['last_synced_at'])
            print(f"  {icon} Source: {s['source_name']} [{s['source_id']}]")
            print(f"     📅 Last Ingested:  {sync_dt}")
            print(f"     📊 Records Count:  {s['records_count']:,}")
            if s.get("details"):
                print(f"     📝 Details:        {s['details']}")
            print()

    # 2. Statistics Organized by Data Source
    print("[2] 📈 DATA SOURCE STATISTICS")
    print("-" * 76)

    # A. IRS BMF
    bmf = stats.get("bmf", {})
    if bmf.get("table_present"):
        print("  A. 🏛️  IRS Business Master File (table: irs_bmf):")
        print(f"     • Status:                         ✅ Ingested")
        print(f"     • Total Registered Charities:    {bmf['total_organizations']:,}")
        print(f"     • 501(c)(3) Organizations:       {bmf['501c3_count']:,}")
        print(f"     • Private Foundations:           {bmf['private_foundations_count']:,}")
        print(f"     • Total Reported Assets:         {format_currency(bmf['total_assets'])}")
        print(f"     • Total Reported Revenue:        {format_currency(bmf['total_revenue'])}")
    else:
        print("  A. 🏛️  IRS Business Master File (table: irs_bmf):")
        print("     • Status:                         ❌ Not yet ingested into DuckDB.")
        print("     • Ingest command:                 💡 python main.py --sync-bmf")

    # B. Funding Grants
    grants = stats.get("grants", {})
    if grants and not grants.get("error") and grants.get("total_grants", 0) > 0:
        print("\n  B. 💸 Funding Grants (table: grants):")
        print(f"     • Total Grant Transactions:      {grants['total_grants']:,}")
        print(f"     • Total Grant Dollar Volume:     {format_currency(grants['total_dollar_volume'])}")
        print(f"     • Unique Grantors (Funders):     🎯 {grants['unique_grantors']:,}")
        print(f"     • Unique Grantees (Recipients):  🤝 {grants['unique_recipients']:,}")
        if grants.get("min_year") and grants.get("max_year"):
            print(f"     • Tax Years Covered:             📅 {grants['min_year']} to {grants['max_year']}")
        if grants.get("by_schedule"):
            print("     • Breakdown by Schedule / Source:")
            for bs in grants["by_schedule"]:
                sched_icon = "📜" if "pf" in bs["schedule"].lower() else "📄"
                print(f"         {sched_icon} {bs['schedule']}: {bs['count']:,} grants ({format_currency(bs['dollar_volume'])})")
    else:
        print("\n  B. 💸 Funding Grants: ℹ️  No grant records found.")

    # C. Corporate Relationships
    rels = stats.get("relationships", {})
    if rels and not rels.get("error") and rels.get("total_relationships", 0) > 0:
        print(f"\n  C. 🏢 Corporate Relationships (table: relationships):")
        print(f"     • Total Corporate Ties:          🔗 {rels['total_relationships']:,}")
        if rels.get("by_type"):
            print("     • Breakdown by Relationship Type:")
            for bt in rels["by_type"]:
                print(f"         👥 {bt['type']}: {bt['count']:,}")
    else:
        print("\n  C. 🏢 Corporate Relationships: ℹ️  No corporate relationship records found.")

    # D. Graph Entities & Filings Cache
    orgs = stats.get("organizations", {})
    filings = stats.get("filings", {})
    print(f"\n  D. 🌐 Graph Entities & Dynamic Ingest Cache:")
    if orgs and not orgs.get("error"):
        print(f"     • Graph Entities (organizations): 🧩 {orgs.get('total_entities', 0):,} nodes ({orgs.get('entities_with_financials', 0):,} with financials)")
    if filings and not filings.get("error"):
        print(f"     • Filings Ingested On-Demand:    ⚡ {filings.get('filings_ingested', 0):,} full returns")
        print(f"     • Cached Raw Payloads:           📦 {filings.get('cached_payloads', 0):,}")

    # E. People & Spending Breakdown
    sp = stats.get("spending_and_people", {})
    if sp and not sp.get("error") and (sp.get("expenses_records", 0) > 0 or sp.get("leadership_records", 0) > 0):
        print(f"\n  E. 👥 Leadership, Interlocks & Spending (tables: people, expenses, contractors):")
        print(f"     • Leadership & Officer Roles:    👔 {sp['leadership_records']:,} affiliations ({sp['unique_people']:,} unique individuals)")
        print(f"     • Multi-Board Interlocks:        🔗 {sp['multi_board_leaders']:,} leaders serving on multiple nonprofit boards")
        print(f"     • Functional Expense Records:    📊 {sp['expenses_records']:,} filings analyzed")
        print(f"     • Independent Contractors:       🏢 {sp['contractors_records']:,} vendors paid >$100k")

    # F. Section 527 Political Organizations
    pacs = stats.get("pacs_527", {})
    if pacs and pacs.get("table_present") and pacs.get("total_527_orgs", 0) > 0:
        print(f"\n  F. ⚡ IRS Section 527 Political Organizations (POFD):")
        print(f"     • Registered 527 Committees:     🏛️  {pacs['total_527_orgs']:,} political organizations")
        print(f"     • Form 8872 Periodic Reports:    📑 {pacs['total_reports']:,}")
        print(f"     • Itemized Contributions:        💰 {pacs['total_contributions']:,} ({format_currency(pacs['contributions_volume'])})")
        print(f"     • Itemized Expenditures:         💸 {pacs['total_expenditures']:,} ({format_currency(pacs['expenditures_volume'])})")
    elif pacs and pacs.get("table_present"):
        print(f"\n  F. ⚡ IRS Section 527 Political Organizations: ℹ️  Table empty (run 'python main.py --sync-527').")

    # G. FEC Federal Political Committees & PACs
    fec = stats.get("fec_pacs", {})
    if fec and fec.get("table_present") and fec.get("total_committees", 0) > 0:
        cycles_str = ", ".join(str(c) for c in fec.get("cycles", []))
        print(f"\n  G. 🗳️  Federal Election Commission (FEC PACs, Super PACs & Campaigns):")
        print(f"     • Political Committees:          🏛️  {fec['total_committees']:,} registered committees (incl. {fec['total_super_pacs']:,} Super PACs)")
        print(f"     • Federal Candidates:            🎯 {fec['total_candidates']:,}")
        print(f"     • Independent Exp & Tx:          💰 {fec['total_transactions']:,} ({format_currency(fec['transactions_volume'])})")
        print(f"     • Operating / Vendor Expenses:   💸 {fec['total_operating_expenditures']:,} ({format_currency(fec['operating_expenditures_volume'])})")
        print(f"     • Election Cycles Covered:       📅 {cycles_str}")
    elif fec and fec.get("table_present"):
        print(f"\n  G. 🗳️  FEC Political Committees & PACs: ℹ️  Table empty (run 'python main.py --sync-fec').")

    # H. Cross-Entity Linkages & PAC Bridges
    link_stats = stats.get("linkages", {})
    if link_stats and link_stats.get("table_present") and link_stats.get("total_linkages", 0) > 0:
        print(f"\n  H. 🔗 Cross-Entity Linkages & Political Bridges (table: entity_linkages):")
        print(f"     • Discovered Linkages:           🌉 {link_stats['total_linkages']:,} charity-to-PAC connections")
        if link_stats.get("by_type"):
            for ltype, count in link_stats["by_type"].items():
                print(f"       - {ltype.replace('_', ' ').title()}: {count:,}")
    elif link_stats and link_stats.get("table_present"):
        print(f"\n  H. 🔗 Cross-Entity Linkages: ℹ️  No linkages cached yet (run 'python main.py --cross-linkages').")

    # 3. Data Freshness & Update Recommendations
    print("\n[3] 💡 DATA FRESHNESS & UPDATE RECOMMENDATIONS")
    print("-" * 76)
    print("  • 🏛️  IRS Business Master File (EO BMF):")
    print("    - Release Cycle: Published MONTHLY by the IRS (typically the 2nd Monday).")
    print("    - Recommended Update: Monthly or quarterly.")
    print("    - Update Command: python main.py --sync-bmf")
    print()
    print("  • ⚡ IRS Section 527 Political Organizations (POFD):")
    print("    - Release Cycle: Published WEEKLY by the IRS (every Saturday morning).")
    print("    - Recommended Update: Monthly or quarterly.")
    print("    - Update Command: python main.py --sync-527")
    print()
    print("  • 🗳️  FEC Federal PACs & Super PACs:")
    print("    - Release Cycle: Published NIGHTLY / REGULARLY by the FEC.")
    print("    - Recommended Update: Monthly or quarterly (default: 3 cycles: 2022, 2024, 2026).")
    print("    - Update Command: python main.py --sync-fec")
    print()
    print("  • 📄 Electronic 990 Schedules (Schedule I Grants & Schedule R Relationships):")
    print("    - Release Cycle: IRS TEOS e-file batches are released monthly.")
    print("    - Recommended Update: Quarterly, semi-annually, or on-demand.")
    print("    - Update Command: python main.py --sync-all")
    print()
    print("  • 🔍 Freshness Audit:")
    print("    - Probe live IRS & FEC servers to check for newer releases:")
    print("    - Check Command: python main.py --check-updates")
    print("=" * 76 + "\n")


def display_contractor_report(storage: IRS990Storage, query: str) -> None:
    """Display comprehensive report on a commercial contractor/vendor hired by nonprofits.

    Args:
        storage: Active DuckDB storage interface instance.
        query: Search string identifying target contractor or vendor.
    """
    dossier = storage.get_contractor_dossier(query)
    print("\n" + "=" * 76)
    print(f"     💼 COMMERCIAL CONTRACTOR & VENDOR DOSSIER: '{query}'")
    print("=" * 76)

    if not dossier:
        print(f"  No contractor matching '{query}' found in database.")
        print("  Tip: Contractor records are extracted from Form 990 Part VII Section B (> $100k).")
        print("=" * 76 + "\n")
        return

    print(f"  Primary Name:          🏢 {dossier['contractor_name']}")
    print(f"  Total Billings:        💰 {format_currency(dossier['total_amount'])}")
    print(f"  Client Charities:      🤝 {dossier['client_count']} nonprofit organization(s)")
    if dossier['min_year'] and dossier['max_year']:
        print(f"  Active Period:         📅 {dossier['min_year']} to {dossier['max_year']}")
    if dossier['locations']:
        print(f"  Known Locations:       📍 {', '.join(dossier['locations'][:4])}")
    if dossier['services']:
        print(f"  Services Rendered:     🛠️  {', '.join(dossier['services'][:5])}")

    print("\n" + "-" * 76)
    print(f"  NONPROFIT CLIENT BREAKDOWN ({len(dossier['clients'])} organizations):")
    print("-" * 76)

    for i, cl in enumerate(dossier["clients"], 1):
        serv_str = f"({', '.join(cl['services'][:2])})" if cl['services'] else ""
        print(f"  [{i}] {cl['filer_name']} (EIN: {cl['filer_ein']})")
        print(f"      • Total Billings:  {format_currency(cl['total_paid'])} across tax year(s) {', '.join(str(y) for y in cl['years'])}")
        if serv_str:
            print(f"      • Stated Services: {serv_str}")
        print()

    print("=" * 76 + "\n")


def display_527_report(storage: IRS990Storage, query: str) -> None:
    """Display report on an IRS Section 527 political organization.

    Args:
        storage: Active DuckDB storage interface instance.
        query: Target EIN, Form 8871 ID, or entity name.
    """
    org = storage.get_527_org(query)
    print("\n" + "=" * 76)
    print(f"      ⚡ IRS SECTION 527 POLITICAL ORGANIZATION REPORT: '{query}'")
    print("=" * 76)

    if not org:
        matches = storage.search_527_orgs(query, limit=5)
        if matches:
            org = storage.get_527_org(matches[0]["form_id"])
        else:
            print(f"  No Section 527 political committee matching '{query}' found.")
            print("  Tip: Make sure you have ingested the 527 dataset via 'python main.py --sync-527'.")
            print("=" * 76 + "\n")
            return

    print(f"  Committee Name:        🏛️  {org['name']}")
    print(f"  Form Type / Status:    📑 Form {org['form_type']} (Section 527 Political Organization)")
    if org['ein']:
        print(f"  EIN:                   🆔 {org['ein']}")
    if org['city'] or org['state']:
        print(f"  Location:              📍 {org['city']}, {org['state']} {org['zip']}")
    if org['custodian_name']:
        print(f"  Custodian of Records:  👤 {org['custodian_name']}")
    if org['email']:
        print(f"  Contact Email:         ✉️  {org['email']}")
    if org['purpose']:
        print(f"  Stated Purpose:        📝 {org['purpose'][:250]}")

    if org.get("directors"):
        print("\n" + "-" * 76)
        print(f"  COMMITTEE DIRECTORS & OFFICERS ({len(org['directors'])}):")
        print("-" * 76)
        for d in org["directors"][:8]:
            print(f"  • {d['name']} — {d['title']} ({d['city']}, {d['state']})")

    if org.get("related_entities"):
        print("\n" + "-" * 76)
        print(f"  CONNECTED & RELATED ORGANIZATIONS ({len(org['related_entities'])}):")
        print("-" * 76)
        for r in org["related_entities"][:6]:
            print(f"  • {r['related_name']} (Relationship: {r['relationship']})")

    if org.get("reports"):
        print("\n" + "-" * 76)
        print("  RECENT FORM 8872 FILINGS (Contributions & Expenditures):")
        print("-" * 76)
        for rep in org["reports"][:6]:
            period = f"{rep['begin']} to {rep['end']}" if rep['begin'] else f"Form ID {rep['form_id']}"
            print(f"  • Period: {period}")
            print(f"    - Contributions: {format_currency(rep['contributions'])} | Expenditures: {format_currency(rep['expenditures'])}")

    print("=" * 76 + "\n")


def display_omni_search_report(storage: IRS990Storage, query: str) -> None:
    """Execute unified multi-entity search across nonprofits, leaders, vendors, and PACs.

    Args:
        storage: Active DuckDB storage interface instance.
        query: Full-text search term.
    """
    results = storage.search_omni(query, limit=8)
    print("\n" + "=" * 76)
    print(f"         🔍 MULTI-ENTITY OMNI-SEARCH RESULTS FOR: '{query}'")
    print("=" * 76)

    total_found = sum(len(v) for v in results.values())
    if total_found == 0:
        print(f"  No records found matching '{query}'.")
        print("=" * 76 + "\n")
        return

    # 1. Nonprofits
    orgs = results.get("organizations", [])
    if orgs:
        print(f"\n  🏛️  NONPROFIT ORGANIZATIONS ({len(orgs)}):")
        for o in orgs:
            rev_str = f" | Rev: {format_currency(o['revenue'])}" if o.get('revenue') else ""
            loc_str = f"({o['city']}, {o['state']})" if o.get('city') else ""
            print(f"     • {o['name']} {loc_str} — EIN: {o['ein']} [{o['tax_status']}]{rev_str}")

    # 2. People & Board Members
    ppl = results.get("people", [])
    if ppl:
        print(f"\n  👤 LEADERSHIP & BOARD MEMBERS ({len(ppl)}):")
        for p in ppl:
            print(f"     • {p['name']} — {p['org_count']} board seat(s) [Titles: {p['titles'][:40]}]")

    # 3. Commercial Vendors & Contractors
    contr = results.get("contractors", [])
    if contr:
        print(f"\n  💼 COMMERCIAL CONTRACTORS & VENDORS ({len(contr)}):")
        for c in contr:
            print(f"     • {c['contractor_name']} — {format_currency(c['total_amount'])} across {c['client_count']} charity client(s)")

    # 4. Schedule R Affiliates
    aff = results.get("affiliates", [])
    if aff:
        print(f"\n  🏢 CORPORATE AFFILIATES & SCHEDULE R ({len(aff)}):")
        for a in aff:
            print(f"     • {a['related_name']} [{a['relationship_type']}] ⟷ {a['entity_name']}")

    # 5. Section 527 Political Organizations
    pacs = results.get("pacs_527", [])
    if pacs:
        print(f"\n  ⚡ SECTION 527 POLITICAL COMMITTEES ({len(pacs)}):")
        for pc in pacs:
            print(f"     • {pc['name']} ({pc['city']}, {pc['state']}) — EIN: {pc['ein']}")

    # 6. FEC Federal Political Committees & Super PACs
    fec = results.get("fec_pacs", [])
    if fec:
        print(f"\n  🗳️  FEDERAL POLITICAL COMMITTEES & SUPER PACS ({len(fec)}):")
        for f in fec:
            sponsor = f" [Connected Org: {f['connected_org']}]" if f.get('connected_org') else ""
            print(f"     • {f['name']} — ID: {f['cmte_id']} [{f['type_label']}]{sponsor} (Cycle {f.get('cycle', '')})")

    print("=" * 76 + "\n")


def display_fec_committee_report(storage: IRS990Storage, query: str) -> None:
    """Display comprehensive report on a Federal Election Commission (FEC) committee.

    Args:
        storage: Active DuckDB storage interface instance.
        query: FEC committee ID or entity name.
    """
    cmte = storage.get_fec_committee(query)
    print("\n" + "=" * 76)
    print(f"     🗳️  FEDERAL ELECTION COMMISSION (FEC) COMMITTEE DOSSIER: '{query}'")
    print("=" * 76)

    if not cmte:
        print(f"  No FEC committee matching '{query}' found in database.")
        print("  Tip: Verify committee ID (e.g. 'C00580100') or committee name (e.g. 'Majority Forward', 'Senate Majority PAC').")
        print("       Run 'python main.py --sync-fec' to download and populate FEC committees.")
        print("=" * 76 + "\n")
        return

    print(f"  Committee Name:        🏛️  {cmte['name']}")
    print(f"  Committee ID:          🆔 {cmte['cmte_id']}")
    print(f"  Classification:        🏷️  {cmte['type_label']}")
    if cmte['party']:
        print(f"  Party Affiliation:     🗳️  {cmte['party']}")
    if cmte['connected_org']:
        print(f"  Connected / Sponsor:   🏢 {cmte['connected_org']} (Links to 501(c) Network!)")
    if cmte['treasurer_name']:
        print(f"  Treasurer:             👤 {cmte['treasurer_name']}")
    if cmte['city'] or cmte['state']:
        print(f"  Location:              📍 {cmte['city']}, {cmte['state']} {cmte['zip']}")
    if cmte['cycle']:
        print(f"  Election Cycle:        📅 {cmte['cycle']}")

    # Candidates linked
    if cmte.get("candidates"):
        print("\n" + "-" * 76)
        print(f"  LINKED FEDERAL CANDIDATES ({len(cmte['candidates'])}):")
        print("-" * 76)
        for c in cmte["candidates"][:6]:
            dist = f"-{c['district']}" if c['district'] and c['district'] != "00" else ""
            print(f"  • {c['candidate_name']} ({c['party']}) — Office: {c['office']} {c['office_state']}{dist} [ID: {c['candidate_id']}]")

    # Independent Expenditures
    tx = cmte.get("expenditures_summary", {})
    if tx.get("supporting"):
        print("\n" + "-" * 76)
        print(f"  TOP INDEPENDENT EXPENDITURES — SUPPORTING CANDIDATES:")
        print("-" * 76)
        for s in tx["supporting"][:5]:
            print(f"  • 🟢 {s['recipient_name']}: {format_currency(s['total_amount'])} across {s['count']} filings")

    if tx.get("opposing"):
        print("\n" + "-" * 76)
        print(f"  TOP INDEPENDENT EXPENDITURES — OPPOSING CANDIDATES:")
        print("-" * 76)
        for o in tx["opposing"][:5]:
            print(f"  • 🔴 {o['recipient_name']}: {format_currency(o['total_amount'])} across {o['count']} filings")

    # Top Vendors / Operating Expenditures
    if cmte.get("top_vendors"):
        print("\n" + "-" * 76)
        print(f"  TOP COMMERCIAL VENDORS & MEDIA CONSULTANTS:")
        print("-" * 76)
        for v in cmte["top_vendors"][:6]:
            purp = f" ({v['purposes'][:45]})" if v['purposes'] else ""
            print(f"  • 💼 {v['payee_name']} ({v['city']}, {v['state']}): {format_currency(v['total_amount'])}{purp}")

    print("=" * 76 + "\n")


def display_organization_pacs_report(storage: IRS990Storage, client: ProPublicaClient, query: str) -> None:
    """Discover and display all connected PACs, 527s, shared leaders, and vendors for an organization.

    Args:
        storage: Active DuckDB storage interface instance.
        client: ProPublica API client for upstream lookups.
        query: Target organization name or EIN.
    """
    target_ein = client.resolve_ein(query)
    if not target_ein:
        print(f"\n⚠️  Could not resolve organization for '{query}'.")
        return

    org = storage.get_organization(target_ein)
    org_name = org.name if org else f"Organization {target_ein}"

    from .linkage import LinkageResolver
    resolver = LinkageResolver(storage)
    linkages = resolver.resolve_organization_linkages(target_ein)

    print("\n" + "=" * 76)
    print(f" 🗳️  POLITICAL ACTION COMMITTEES & CONDUITS LINKED TO: {org_name}")
    print(f" 🆔 Target EIN: {target_ein}")
    print("=" * 76)

    if not linkages:
        print(f"\n  No direct PAC or 527 political connections identified for {org_name}.")
        print("  Tips:")
        print("  • Run 'python main.py --sync-all-pacs' to populate local PAC and 527 records.")
        print("  • Ensure Form 990 filings for this entity are ingested into the database.")
        print("=" * 76 + "\n")
        return

    print(f"\n  Found {len(linkages)} political committee link(s) across governance & funding pipelines:\n")
    for i, link in enumerate(linkages, 1):
        type_icon = "🗳️ " if link.target_type == "fec_pac" else "⚡"
        conf_pct = int(link.confidence_score * 100)
        print(f"  [{i}] {type_icon} {link.target_name} (ID: {link.target_id})")
        print(f"      • Bridge Category:  {link.link_type.replace('_', ' ').title()} [Confidence: {conf_pct}%]")
        print(f"      • Evidence:         {link.description}")
        if link.evidence:
            for k, v in link.evidence.items():
                if k in ("shared_person", "nonprofit_title", "pac_role", "connected_org_filed", "relation_role"):
                    print(f"        - {k.replace('_', ' ').title()}: {v}")
        print()

    print("=" * 76 + "\n")


def display_cross_linkages_report(storage: IRS990Storage, limit: int = 50) -> None:
    """Display database-wide cross-entity resolution report linking charities to political entities.

    Args:
        storage: Active DuckDB storage interface instance.
        limit: Maximum number of resolved linkages to display.
    """
    from .linkage import LinkageResolver
    resolver = LinkageResolver(storage)
    print("\n" + "=" * 76)
    print("      🌉 DATABASE-WIDE CROSS-ENTITY RESOLUTION: CHARITY-TO-PAC BRIDGES")
    print("=" * 76)
    print("  Scanning non-profit organizations, officers, contractors, and PACs...")

    linkages = resolver.resolve_all_database_linkages(limit=limit)

    if not linkages:
        print("\n  No cross-entity linkages discovered yet in current database.")
        print("  Tip: Make sure you have populated the database with:")
        print("       - Non-profit filings: 'python main.py --sync-all' or '--ingest-dir'")
        print("       - IRS 527 Political Orgs: 'python main.py --sync-527'")
        print("       - FEC Federal PACs: 'python main.py --sync-fec'")
        print("=" * 76 + "\n")
        return

    print(f"\n  Discovered {len(linkages)} charity-to-PAC bridge(s):\n")
    for i, link in enumerate(linkages, 1):
        target_icon = "🗳️ " if link.target_type == "fec_pac" else "⚡"
        conf_pct = int(link.confidence_score * 100)
        print(f"  [{i}] 🏛️  {link.source_name}  ──({link.link_type.replace('_', ' ').title()} [{conf_pct}%])──▶  {target_icon} {link.target_name}")
        print(f"      • Evidence: {link.description}")
        print()

    print("=" * 76 + "\n")


def display_person_report(storage: IRS990Storage, query: str) -> None:
    """Display comprehensive report on an individual's nonprofit affiliations and interlocks.

    Args:
        storage: Active DuckDB storage interface instance.
        query: Target individual name.
    """
    results = storage.search_people(query)
    print("\n" + "=" * 76)
    print(f"      👥 IRS 990 LEADERSHIP & INTERLOCKS REPORT: '{query}'")
    print("=" * 76)

    if not results:
        print(f"  No individual matching '{query}' found in database.")
        print("  Tip: Verify spelling or try last name (e.g. 'Walker', 'Gates', 'Keton', 'Ramachandran').")
        print("=" * 76 + "\n")
        return

    # Group by clean name
    by_name: Dict[str, List[Any]] = {}
    for p in results:
        by_name.setdefault(p.clean_name, []).append(p)

    for clean_name, affiliations in by_name.items():
        distinct_orgs = len(set(a.filer_ein for a in affiliations))

        print(f"👤 Individual: {clean_name}")
        if distinct_orgs > 1:
            print(f"   🔗 CROSS-BOARD INTERLOCK: Sits on leadership of {distinct_orgs} distinct organizations!")
        print("-" * 76)

        for aff in affiliations:
            print(f"  🏛️  Organization:  {aff.filer_name} (EIN: {aff.filer_ein})")
            print(f"     • Position:     {aff.title} [{aff.role_type}]")
            print(f"     • Time Devoted: ⏱️  {aff.hours_per_week:.1f} hrs/week")
            comp_str = format_currency(aff.total_comp)
            if aff.total_comp > 0:
                print(f"     • Compensation: 💰 {comp_str} (Reportable: {format_currency(aff.reportable_comp)}, Other: {format_currency(aff.other_comp)})")
            else:
                print(f"     • Compensation: $0 (Uncompensated / Volunteer Trustee)")
            print(f"     • Tax Year:     📅 {aff.tax_year}")
            print()

    print("=" * 76 + "\n")


def display_spending_report(storage: IRS990Storage, ein: str, org_name: str) -> None:
    """Display Part IX functional spending breakdown and top independent contractors.

    Args:
        storage: Active DuckDB storage interface instance.
        ein: Target organization Employer Identification Number.
        org_name: Display name of target organization.
    """
    expenses_list = storage.get_expenses(ein)
    contractors = storage.get_contractors(ein)
    people = storage.get_people_by_organization(ein)

    print("\n" + "=" * 76)
    print(f"      💸 HOW THEY SPEND THEIR MONEY: {org_name}")
    print(f"         EIN: {ein}")
    print("=" * 76)

    if not expenses_list:
        print(f"  No Part IX functional expense data found for {org_name}.")
        print("  Tip: Ingest the latest 990 return with 'python main.py --ein <EIN> --serve'.")
    else:
        exp = expenses_list[0]
        print(f" 📅 Tax Year: {exp.tax_year}")
        print(f" 💰 Total Expenses: {format_currency(exp.total_expenses)}")
        print("-" * 76)
        print(" [1] FUNCTIONAL EXPENSE ALLOCATION (Charitable Efficiency)")
        print(f"     🎯 Program Services:       {format_currency(exp.program_services):<16} ({exp.program_percentage:5.1f}% of budget)")
        print(f"     🏢 Management & Overhead:  {format_currency(exp.management_general):<16} ({exp.admin_percentage:5.1f}% of budget)")
        print(f"     📣 Fundraising Expenses:   {format_currency(exp.fundraising):<16} ({exp.fundraising_percentage:5.1f}% of budget)")
        print()
        print(" [2] KEY EXPENDITURE CATEGORIES")
        if exp.grants_paid > 0:
            print(f"     🤝 Grants & Assistance:    {format_currency(exp.grants_paid)}")
        if exp.salaries_total > 0:
            print(f"     👔 Personnel & Salaries:   {format_currency(exp.salaries_total)}")
        if exp.professional_fees > 0:
            print(f"     ⚖️  Professional Fees:      {format_currency(exp.professional_fees)} (Legal, Lobbying, Consulting)")
        if exp.office_and_it > 0:
            print(f"     💻 Office, IT & Occupancy: {format_currency(exp.office_and_it)}")
        if exp.travel_and_conferences > 0:
            print(f"     ✈️  Travel & Conferences:   {format_currency(exp.travel_and_conferences)}")

    if contractors:
        print("\n" + "-" * 76)
        print(f" [3] TOP INDEPENDENT CONTRACTORS (> $100,000)")
        print("     (Disclosed in Form 990 Part VII Section B)")
        print("-" * 76)
        for i, c in enumerate(contractors, 1):
            loc = f"({c.city}, {c.state})" if c.city or c.state else ""
            print(f"  {i}. {c.contractor_name} {loc}")
            print(f"     • Services:      {c.description_of_services}")
            print(f"     • Compensation:  💰 {format_currency(c.amount)}")
            print()

    if people:
        print("-" * 76)
        print(f" [4] KEY OFFICERS, DIRECTORS & TRUSTEES ({len(people)} Individuals)")
        print("-" * 76)
        for p in people[:10]:
            comp = format_currency(p.total_comp) if p.total_comp > 0 else "$0"
            interlocks = storage.get_person_interlocks(p.clean_name)
            interlock_badge = f" [🔗 Sits on {len(interlocks)} boards!]" if len(interlocks) > 1 else ""
            print(f"  • {p.person_name}: {p.title} ({comp}, {p.hours_per_week:.1f} hrs/wk){interlock_badge}")

    print("=" * 76 + "\n")


def display_interlocks_report(storage: IRS990Storage) -> None:
    """Display discovered interlocking directorates across all nonprofits in database.

    Args:
        storage: Active DuckDB storage interface instance.
    """
    pairs = storage.get_interlocking_directorates(limit=50)
    print("\n" + "=" * 76)
    print("      🔗 INTERLOCKING DIRECTORATES: NONPROFITS SHARING BOARD LEADERSHIP")
    print("=" * 76)

    if not pairs:
        print("  No shared board members detected between organizations yet.")
        print("  Ingest additional 990 returns or load seeds to discover interlocks.")
        print("=" * 76 + "\n")
        return

    print(f" Discovered {len(pairs)} cross-organizational leadership link(s):\n")
    for i, pair in enumerate(pairs, 1):
        print(f"[{i}] Shared Leader: 👤 {pair['shared_person']}")
        print(f"    • Entity A: 🏛️  {pair['org_a']} (EIN: {pair['ein_a']})")
        print(f"      Role:     {pair['role_a']} (Tax Year {pair['year_a']})")
        print(f"    • Entity B: 🏛️  {pair['org_b']} (EIN: {pair['ein_b']})")
        print(f"      Role:     {pair['role_b']} (Tax Year {pair['year_b']})")
        print()

    print("=" * 76 + "\n")


def main() -> None:
    """Execute main CLI application workflow coordinating arguments, synchronization, and traversal."""
    setup_terminal_hygiene()
    args = parse_args()

    # 1. Initialize Storage
    storage = IRS990Storage(args.db_path)
    client = ProPublicaClient(storage)

    try:
        # Check if user asked to check for upstream updates
        if getattr(args, "check_updates", False):
            from .freshness import DataFreshnessChecker
            checker = DataFreshnessChecker(storage)
            checker.run_full_check()
            return

        # Check if user asked for status
        if args.status:
            display_database_status(storage)
            return

        print("=" * 70)
        print(" IRS 990 Ultimate Funding & Relationship Social Graph Explorer")
        print("=" * 70)

        # 2. Ingest seeds if needed
        if not args.no_seeds:
            if args.sync_all:
                print("\n[1/2] Checking Curated Institutional Funders & Seeds...")
                was_loaded = load_seed_data(storage, force=args.force_download)
                if was_loaded:
                    print("  ✅ Institutional foundation seeds and grants synchronized.")
                else:
                    print("  ✅ [UP TO DATE] Curated institutional seeds already present in database. Skipping.")
            else:
                load_seed_data(storage, force=args.force_download)

        # Handle BMF sync
        if args.sync_bmf or args.sync_all:
            if args.sync_all:
                print("\n[2/2] Checking IRS Business Master File (EO BMF)...")
            from .bmf import BMFIngester
            bmf_ingester = BMFIngester(storage)
            bmf_ingester.sync(force_download=args.force_download)

        # 3. Handle optional bulk ingestion arguments
        if args.ingest_dir:
            logger.info(f"Ingesting XML/ZIP files from directory: {args.ingest_dir}")
            ingester = BulkIngester(storage)
            stats = ingester.ingest_directory(args.ingest_dir)
            logger.info(f"Ingestion complete: {stats}")

        if args.ingest_zip:
            logger.info(f"Ingesting IRS TEOS ZIP file: {args.ingest_zip}")
            ingester = BulkIngester(storage)
            stats = ingester.ingest_zip(args.ingest_zip)
            logger.info(f"ZIP Ingestion complete: {stats}")

        # 3. Handle Bulk Data Synchronization
        if args.sync_bmf:
            ingester = BMFIngester(storage)
            ingester.sync(force_download=args.force_download)

        if args.sync_527:
            ingester_527 = POFDIngester(storage)
            ingester_527.sync(force_download=args.force_download)

        if args.sync_fec or args.sync_all_pacs:
            fec_ingester = FECIngester(storage)
            cycles = [int(c.strip()) for c in args.fec_cycles.split(",") if c.strip().isdigit()] if args.fec_cycles else None
            fec_ingester.sync_all_cycles(cycles=cycles, include_expenditures=not args.fec_skip_exp, force=args.force_download)

        if args.sync_all:
            print("Synchronizing all datasets (BMF + Seeds + 527 POFD + FEC Bulk)...")
            bmf_ingester = BMFIngester(storage)
            bmf_ingester.sync(force_download=args.force_download)
            load_seed_data(storage)
            pofd_ingester = POFDIngester(storage)
            pofd_ingester.sync(force_download=args.force_download)
            fec_ingester = FECIngester(storage)
            fec_ingester.sync_all_cycles(include_expenditures=not args.fec_skip_exp, force=args.force_download)

        if (args.sync_bmf or args.sync_527 or args.sync_fec or args.sync_all_pacs or args.sync_all) and not (args.ein or args.name or args.serve or args.spending or args.person or args.interlocks or args.vendor or args.pac_527 or args.fec_cmte or args.search):
            display_database_status(storage)
            return

        # 4. Handle Specialized People, Vendor, 527, FEC, and Search Reports
        if args.interlocks:
            display_interlocks_report(storage)
            return

        if args.person:
            display_person_report(storage, args.person)
            return

        if args.vendor:
            display_contractor_report(storage, args.vendor)
            return

        if args.pac_527:
            display_527_report(storage, args.pac_527)
            return

        if args.fec_cmte:
            display_fec_committee_report(storage, args.fec_cmte)
            return

        if args.search:
            display_omni_search_report(storage, args.search)
            return

        if args.cross_linkages:
            display_cross_linkages_report(storage)
            return

        if args.pac_links:
            display_organization_pacs_report(storage, client, args.pac_links)
            return

        if args.spending:
            target_query = args.ein or args.name
            if not target_query:
                print("⚠️  Error: Please specify an organization via --name or --ein to view spending.")
                print("   Example: python main.py --name 'Tides Foundation' --spending\n")
                return
            target_ein = client.resolve_ein(target_query)
            if not target_ein:
                logger.error(f"Could not resolve EIN for '{target_query}'.")
                return
            target_node = client.get_organization(target_ein)
            target_name = target_node.name if target_node else f"Organization {target_ein}"
            display_spending_report(storage, target_ein, target_name)
            return

        # 4. Handle Server Mode early or resolve Target EIN
        target_query = args.ein or args.name
        if not target_query and not args.serve:
            if args.ingest_dir or args.ingest_zip:
                print("Data ingestion finished. To explore an organization, specify --name or --ein.")
                return
            else:
                display_database_status(storage)
                print("Tip: Run with --name 'Organization' or --ein 'XX-XXXXXXX' to explore a graph.")
                print("     Run with --serve to launch the interactive browser interface.")
                print("     Run with --help to view all available commands.\n")
                return

        target_ein = None
        if target_query:
            logger.info(f"Resolving target organization: '{target_query}'...")
            target_ein = client.resolve_ein(target_query)
            if not target_ein:
                logger.error(f"Could not resolve EIN for '{target_query}'. Please verify spelling or provide exact EIN.")
                sys.exit(1)

        if args.serve:
            target_ein = target_ein or "51-0198509"
            storage.close()

            if args.daemon:
                import subprocess
                from .server import format_clickable_url
                cmd = [
                    sys.executable, "-m", "irs990.cli",
                    "serve",
                    "--host", args.host,
                    "--port", str(args.port),
                    "--db-path", args.db_path,
                ]
                if target_ein:
                    cmd.extend(["--ein", target_ein])
                if args.no_browser:
                    cmd.append("--no-browser")
                # SECURITY: Use discrete argument array (never shell=True) to prevent command injection (CWE-78)
                proc = subprocess.Popen(
                    cmd,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    start_new_session=True
                )
                daemon_url = f"http://{args.host}:{args.port}/?ein={target_ein}"
                clickable_url = format_clickable_url(daemon_url, stream=sys.stderr)
                # SECURITY: Diagnostic messages and URLs go to stderr to preserve stdout stream separation
                print(f"🚀 Server started in background (PID: {proc.pid})", file=sys.stderr)
                print(f"   URL: {clickable_url}", file=sys.stderr)
                print(f"   To stop: kill {proc.pid}\n", file=sys.stderr)
                return

            from .server import start_server
            start_server(
                host=args.host,
                port=args.port,
                target_ein=target_ein,
                db_path=args.db_path,
                auto_open=not args.no_browser
            )
            return

        target_node = client.get_organization(target_ein)
        target_name = target_node.name if target_node else f"Organization {target_ein}"
        logger.info(f"Resolved Target: '{target_name}' (EIN: {target_ein})")

        # 5. Graph Traversal
        logger.info(
            f"Starting {args.direction.upper()} traversal (Depth: {args.depth}, "
            f"Min Grant: ${args.min_grant_amt:,.0f}, Top-N: {args.top_n})..."
        )
        engine = FundingTraversalEngine(storage, client)
        graph = engine.traverse(
            target_ein=target_ein,
            direction=args.direction,
            max_depth=args.depth,
            min_grant_amt=args.min_grant_amt,
            start_year=args.start_year,
            end_year=args.end_year,
            top_n_per_hop=args.top_n,
            include_schedule_r=not args.no_schedule_r,
            include_pacs=not args.no_pacs
        )

        total_grants = sum(e.total_amount for e in graph.grant_edges.values())
        print("\n" + "-" * 70)
        print(f" Graph Traversal Summary for: {target_name}")
        print(f" • Target EIN:              {target_ein}")
        print(f" • Total Connected Nodes:   {len(graph.nodes)}")
        print(f" • Grant Funding Edges:     {len(graph.grant_edges)}")
        print(f" • Total Funding Volume:    ${total_grants:,.2f}")
        print(f" • Corporate Relationships: {len(graph.relationship_edges)}")
        print("-" * 70 + "\n")

        # 6. Generate Standalone Portable HTML
        sanitized_name = "".join(c if c.isalnum() else "_" for c in target_name.lower()).strip("_")
        default_out = os.path.join("output", f"{sanitized_name}_funding.html")
        output_path = args.output or default_out

        generator = VisualizerGenerator()
        final_path = generator.generate_html(graph, output_path, storage=storage)

        print(f"🎉 Portable HTML visualization generated successfully:")
        print(f"   file://{os.path.abspath(final_path)}")
        print(f"   (You can open this standalone file directly in any web browser without a webserver)\n")
    finally:
        storage.close()


if __name__ == "__main__":
    main()
