# SPDX-FileCopyrightText: 2026 990-Explorer Authors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Lightweight Interactive Local Server for IRS 990 Explorer.

Architectural Purpose:
    Provides a low-latency, localhost-only HTTP server (using standard library
    http.server and socketserver) exposing dynamic REST APIs for interactive
    Form 990 graph exploration, cross-entity PAC/527 linkages, full-text omni-search,
    and self-contained HTML snapshot generation.

Security Invariants:
    - Binds by default to 127.0.0.1 (never 0.0.0.0 without explicit host configuration).
    - Checks interactive TTY and NO_COLOR before emitting terminal styling or OSC 8 links.
    - Suppresses automatic browser launch in headless or CI execution environments.
    - Emits security response headers (CSP, X-Content-Type-Options, X-Frame-Options).
"""

import http.server
import socketserver
import urllib.parse
import json
import os
import sys
import logging
import threading
import secrets
import mimetypes
from typing import Optional, Any, Dict, List

from .storage import IRS990Storage, DEFAULT_DB_PATH
from .client import ProPublicaClient
from .fec import FECClient, FECIngester
from .seeds import load_seed_data
from .traversal import FundingTraversalEngine
from .visualizer import VisualizerGenerator, format_currency
from .security import is_headless_environment, sanitize_log_path

logger = logging.getLogger("irs990-server")

# SECURITY: Initialize standard shared MIME database per Directive 5
mimetypes.init()


def get_verified_content_type(filename_or_ext: str, default: str = "text/plain; charset=utf-8") -> str:
    """Determine MIME type using standard system MIME database (shared-mime-info-spec).

    Args:
        filename_or_ext: File name or extension (e.g. 'index.html', 'data.json').
        default: Fallback MIME type if extension is unrecognized.

    Returns:
        Verified Content-Type string with UTF-8 charset if text-based.
    """
    guessed, _ = mimetypes.guess_type(filename_or_ext)
    if not guessed:
        return default
    if guessed.startswith("text/") or guessed in ("application/json", "application/javascript"):
        return f"{guessed}; charset=utf-8"
    return guessed


def format_clickable_url(url: str, label: Optional[str] = None, stream=None) -> str:
    """Format a web address as an OSC 8 clickable hyperlink when supported.

    Inspects the target output stream for interactive TTY capabilities and verifies
    that the NO_COLOR environment variable is absent before emitting ANSI escape codes.
    Falls back to a clean plain-text URL if redirected or when NO_COLOR is active.

    Args:
        url: The destination web address.
        label: Optional display text. If omitted, the URL itself is displayed.
        stream: The output stream to test for TTY support. Defaults to sys.stderr.

    Returns:
        Formatted OSC 8 escape sequence string or plain URL string.
    """
    if stream is None:
        stream = sys.stderr
    text = label or url
    # SECURITY: Respect NO_COLOR standard and non-interactive pipes to avoid polluting machine logs
    if hasattr(stream, "isatty") and stream.isatty() and not os.environ.get("NO_COLOR"):
        return f"\033]8;;{url}\033\\{text}\033]8;;\033\\"
    return text




class IRS990RequestHandler(http.server.SimpleHTTPRequestHandler):
    storage: IRS990Storage = None
    client: ProPublicaClient = None
    fec_client: Optional[FECClient] = None
    engine: FundingTraversalEngine = None
    generator: VisualizerGenerator = None
    default_ein: str = "51-0198509"
    launch_token: Optional[str] = None
    lock: threading.Lock = threading.Lock()

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        query = urllib.parse.parse_qs(parsed.query)

        if path == "/" or path == "/index.html":
            self.handle_index(query)
        elif path == "/api/explore":
            self.handle_api_explore(query)
        elif path == "/api/search":
            self.handle_api_search(query)
        elif path == "/api/search/omni":
            self.handle_api_search_omni(query)
        elif path == "/api/contractor/dossier":
            self.handle_api_contractor_dossier(query)
        elif path.startswith("/api/527/org"):
            self.handle_api_527_org(query, path)
        elif path.startswith("/api/fec/committee"):
            self.handle_api_fec_committee(query, path)
        elif path == "/api/fec/sync-committees":
            self.handle_api_fec_sync_committees()
        elif path.startswith("/api/organization/") and path.endswith("/spending"):
            parts = path.strip("/").split("/")
            if len(parts) == 4:
                self.handle_api_spending(parts[2])
            else:
                self.send_error(400, "Bad Request")
        elif path.startswith("/api/organization/") and path.endswith("/people"):
            parts = path.strip("/").split("/")
            if len(parts) == 4:
                self.handle_api_people(parts[2])
            else:
                self.send_error(400, "Bad Request")
        elif path.startswith("/api/organization/") and (path.endswith("/pacs") or path.endswith("/linkages")):
            parts = path.strip("/").split("/")
            if len(parts) == 4:
                self.handle_api_organization_linkages(parts[2])
            else:
                self.send_error(400, "Bad Request")
        elif path == "/api/linkages/all":
            self.handle_api_all_linkages(query)
        elif path == "/api/people/search":
            self.handle_api_people_search(query)
        elif path == "/api/person/profile":
            self.handle_api_person_profile(query)
        elif path == "/api/interlocks":
            self.handle_api_interlocks()
        else:
            self.send_error(404, "Endpoint Not Found")

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/api/export":
            self.handle_api_export()
        else:
            self.send_error(404, "Endpoint Not Found")

    def handle_index(self, query):
        """Serve the interactive HTML page with active server hooks."""
        target_param = query.get("ein", [self.default_ein])[0]
        direction = query.get("direction", ["both"])[0].lower().strip()
        if direction in ("all", "both"):
            direction = "both"
        depth = int(query.get("depth", [1])[0])
        min_grant = float(query.get("min_grant", [10000.0])[0])


        with self.lock:
            target_ein = self.client.resolve_ein(target_param) or self.default_ein
            out_grants = self.storage.get_outbound_grants(target_ein)
            if len(out_grants) <= 1 and target_ein in ("23-7093598", "36-2993077"):
                load_seed_data(self.storage)
            graph = self.engine.traverse(

                target_ein=target_ein,
                direction=direction,
                max_depth=depth,
                min_grant_amt=min_grant,
                include_pacs=True
            )

        # Generate HTML with server mode enabled
        expenses_dict = {}
        contractors_dict = {}
        people_dict = {}
        for ein in graph.nodes:
            exp = self.storage.get_expenses(ein)
            if exp:
                expenses_dict[ein] = [e.to_dict() for e in exp]
            con = self.storage.get_contractors(ein)
            if con:
                contractors_dict[ein] = [c.to_dict() for c in con]
            ppl = self.storage.get_people_by_organization(ein)
            if ppl:
                people_dict[ein] = [p.to_dict() for p in ppl]

        pacs_loaded = {}
        try:
            from .linkage import LinkageResolver
            resolver = LinkageResolver(self.storage)
            for ein in graph.nodes:
                links = resolver.resolve_organization_linkages(ein)
                if links:
                    pacs_loaded[ein] = [l.to_dict() for l in links]
        except Exception as e:
            logger.warning(f"Could not pre-populate PAC linkages in handle_index: {e}")

        graph_dict = {
            "target": graph.target_node.to_dict(),
            "nodes": {ein: node.to_dict() for ein, node in graph.nodes.items()},
            "grant_edges": {k: edge.to_dict() for k, edge in graph.grant_edges.items()},
            "relationship_edges": {k: rel.to_dict() for k, rel in graph.relationship_edges.items()},
            "expenses": expenses_dict,
            "contractors": contractors_dict,
            "people": people_dict,
            "pacsLoaded": pacs_loaded
        }
        total_funding_amt = sum(e.total_amount for e in graph.grant_edges.values())

        from jinja2 import Template
        from .visualizer import HTML_TEMPLATE

        template = Template(HTML_TEMPLATE)
        html = template.render(
            graph=graph,
            graph_json=json.dumps(graph_dict),
            total_funding_amt=total_funding_amt,
            format_currency=format_currency,
            vis_js=self.generator.vis_js_content,
            vis_css=self.generator.vis_css_content,
            is_server_mode=True
        )

        content = html.encode("utf-8")
        content_type = get_verified_content_type("index.html", default="text/html; charset=utf-8")
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        # SECURITY: Set HTTP security headers per Directive 5
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'self' 'unsafe-inline' data:; frame-ancestors 'none';")
        if self.launch_token:
            self.send_header("Set-Cookie", f"irs990_token={self.launch_token}; Path=/; SameSite=Strict; HttpOnly")
        self.end_headers()
        self.wfile.write(content)

    def handle_api_explore(self, query):
        """API: Traverses and returns graph JSON for the given target."""
        target_param = query.get("ein", query.get("name", [""]))[0]
        if not target_param:
            self.send_json_response({"error": "Missing 'ein' or 'name' parameter"}, status=400)
            return

        direction = query.get("direction", ["both"])[0].lower().strip()
        if direction in ("all", "both"):
            direction = "both"
        depth = int(query.get("depth", [1])[0])
        min_grant = float(query.get("min_grant", [10000.0])[0])
        top_n = int(query.get("top_n", [30])[0])


        retrieve = query.get("retrieve", ["0"])[0] in ("1", "true", "True")

        with self.lock:
            target_ein = self.client.resolve_ein(target_param)
            if not target_ein:
                self.send_json_response({"error": f"Could not resolve organization for '{target_param}'"}, status=404)
                return

            # Fetch / update organization details from ProPublica if not cached
            target_node = self.storage.get_organization(target_ein)
            if not target_node or not target_node.name or target_node.name.startswith("Unknown"):
                target_node = self.client.get_organization(target_ein)

            # Ensure latest enriched seeds are loaded if target is MacArthur or has sparse data
            out_grants = self.storage.get_outbound_grants(target_ein)
            if len(out_grants) <= 1 and target_ein in ("23-7093598", "36-2993077"):
                load_seed_data(self.storage)
                target_node = self.storage.get_organization(target_ein)


            retrieval_info = None
            if retrieve:
                logger.info(f"Dynamic retrieve requested for {target_ein}. Fetching latest IRS XML...")
                retrieval_info = self.client.fetch_and_ingest_latest_filing(target_ein, force=False)

            include_pacs = query.get("pacs", query.get("include_pacs", ["1"]))[0] in ("1", "true", "True")

            graph = self.engine.traverse(
                target_ein=target_ein,
                direction=direction,
                max_depth=depth,
                min_grant_amt=min_grant,
                top_n_per_hop=top_n,
                include_pacs=include_pacs
            )

            total_funding_amt = sum(e.total_amount for e in graph.grant_edges.values())
            expenses_dict = {}
            contractors_dict = {}
            people_dict = {}
            for ein in graph.nodes:
                exp = self.storage.get_expenses(ein)
                if exp:
                    expenses_dict[ein] = [e.to_dict() for e in exp]
                con = self.storage.get_contractors(ein)
                if con:
                    contractors_dict[ein] = [c.to_dict() for c in con]
                ppl = self.storage.get_people_by_organization(ein)
                if ppl:
                    people_dict[ein] = [p.to_dict() for p in ppl]

            pacs_loaded = {}
            try:
                from .linkage import LinkageResolver
                resolver = LinkageResolver(self.storage)
                for ein in graph.nodes:
                    links = resolver.resolve_organization_linkages(ein)
                    if links:
                        pacs_loaded[ein] = [l.to_dict() for l in links]
            except Exception as e:
                logger.warning(f"Could not resolve PAC linkages in handle_api_explore: {e}")

            payload = {
                "target": graph.target_node.to_dict(),
                "nodes": {ein: node.to_dict() for ein, node in graph.nodes.items()},
                "grant_edges": {k: edge.to_dict() for k, edge in graph.grant_edges.items()},
                "relationship_edges": {k: rel.to_dict() for k, rel in graph.relationship_edges.items()},
                "expenses": expenses_dict,
                "contractors": contractors_dict,
                "people": people_dict,
                "pacsLoaded": pacs_loaded,
                "stats": {
                    "total_nodes": len(graph.nodes),
                    "total_grants": len(graph.grant_edges),
                    "total_funding_amt": total_funding_amt,
                    "total_relationships": len(graph.relationship_edges)
                },
                "retrieval": retrieval_info
            }
        self.send_json_response(payload)

    def handle_api_search(self, query):
        """API: Live autocomplete search across ProPublica and local database."""
        q = query.get("q", [""])[0].strip()
        if not q:
            self.send_json_response([])
            return

        with self.lock:
            # 1. Search local DB first
            local_results = self.storage.search_organizations(q, limit=10)
            results = [
                {"ein": o.ein, "name": o.name, "city": o.city, "state": o.state, "revenue": o.total_revenue}
                for o in local_results
            ]

            # 2. Search ProPublica if local is sparse
            if len(results) < 5:
                pp_results = self.client.search_organizations(q)
                for r in pp_results[:8]:
                    r_ein = r.get("strein") or str(r.get("ein"))
                    if not any(item["ein"] == r_ein for item in results):
                        results.append({
                            "ein": r_ein,
                            "name": r.get("name"),
                            "city": r.get("city"),
                            "state": r.get("state"),
                            "revenue": 0.0
                        })

        self.send_json_response(results[:15])

    def handle_api_search_omni(self, query):
        """API: Unified multi-entity omni-search across nonprofits, people, contractors, and 527s."""
        q = query.get("q", [""])[0].strip()
        if not q:
            self.send_json_response({
                "organizations": [], "people": [], "contractors": [], "affiliates": [], "pacs_527": []
            })
            return

        with self.lock:
            results = self.storage.search_omni(q, limit=12)

            # Fallback to ProPublica for organizations if local is sparse
            if len(results.get("organizations", [])) < 3:
                pp_results = self.client.search_organizations(q)
                existing_eins = set(o["ein"] for o in results["organizations"])
                for r in pp_results[:6]:
                    r_ein = r.get("strein") or str(r.get("ein"))
                    if r_ein not in existing_eins:
                        results["organizations"].append({
                            "ein": r_ein,
                            "name": r.get("name"),
                            "city": r.get("city") or "",
                            "state": r.get("state") or "",
                            "revenue": 0.0,
                            "assets": 0.0,
                            "tax_status": "501(c)(3)",
                            "type": "organization"
                        })

            # Fallback to OpenFEC API for federal PACs if local is sparse
            if len(results.get("fec_pacs", [])) < 3 and len(q) >= 2:
                try:
                    client_fec = self.fec_client or FECClient(self.storage)
                    live_pacs = client_fec.search_committees(q, limit=6)
                    existing_cmtes = set(p["cmte_id"] for p in results.get("fec_pacs", []))
                    if "fec_pacs" not in results:
                        results["fec_pacs"] = []
                    for p in live_pacs:
                        if p["cmte_id"] not in existing_cmtes:
                            results["fec_pacs"].append(p)
                except Exception as e:
                    logger.debug(f"OpenFEC live search fallback error: {e}")

        self.send_json_response(results)

    def handle_api_contractor_dossier(self, query):
        """API: Commercial contractor dossier showing all hiring charities, billings, and services."""
        name = query.get("name", [""])[0].strip()
        if not name:
            self.send_json_response({"error": "Missing 'name' parameter"}, status=400)
            return

        with self.lock:
            dossier = self.storage.get_contractor_dossier(name)

        if not dossier:
            self.send_json_response({"error": f"No records found for contractor '{name}'"}, status=404)
        else:
            self.send_json_response(dossier)

    def handle_api_527_org(self, query, path):
        """API: Profile and filings for an IRS Section 527 political organization."""
        parts = path.strip("/").split("/")
        ein_or_id = parts[3] if len(parts) >= 4 else query.get("ein", query.get("id", [""]))[0].strip()
        if not ein_or_id:
            self.send_json_response({"error": "Missing EIN or Form ID"}, status=400)
            return

        with self.lock:
            profile = self.storage.get_527_org(ein_or_id)

        if not profile:
            self.send_json_response({"error": f"527 Organization '{ein_or_id}' not found"}, status=404)
        else:
            self.send_json_response(profile)

    def handle_api_fec_committee(self, query, path):
        """API: Fetch federal political committee details, candidates, and independent expenditures."""
        parts = path.strip("/").split("/")
        cmte_id = parts[3] if len(parts) >= 4 else query.get("id", query.get("cmte_id", [""]))[0].strip()
        if not cmte_id:
            self.send_json_response({"error": "Missing Committee ID"}, status=400)
            return

        with self.lock:
            profile = self.storage.get_fec_committee(cmte_id)
            if not profile:
                try:
                    client_fec = self.fec_client or FECClient(self.storage)
                    profile = client_fec.get_committee_profile(cmte_id)
                except Exception as e:
                    logger.debug(f"Live FEC committee fetch error: {e}")

        if not profile:
            self.send_json_response({"error": f"FEC Committee '{cmte_id}' not found"}, status=404)
        else:
            self.send_json_response(profile)

    def handle_api_fec_sync_committees(self):
        """API: Rapidly sync FEC Committee Master records only."""
        with self.lock:
            try:
                ingester = FECIngester(self.storage)
                counts = ingester.sync_committees_only(cycles=[2022, 2024, 2026])
                total = sum(counts.values())
                self.send_json_response({
                    "status": "success",
                    "total_ingested": total,
                    "cycles": counts
                })
            except Exception as e:
                logger.error(f"Failed rapid committee sync: {e}")
                self.send_json_response({"status": "error", "message": str(e)}, status=500)

    def handle_api_organization_linkages(self, ein: str):
        """API: Fetch all resolved PAC and 527 linkages for a non-profit organization."""
        with self.lock:
            target_ein = self.client.resolve_ein(ein) or ein
            from .linkage import LinkageResolver
            resolver = LinkageResolver(self.storage)
            linkages = resolver.resolve_organization_linkages(target_ein)
            org = self.storage.get_organization(target_ein)
            name = org.name if org else f"Organization {target_ein}"

        self.send_json_response({
            "ein": target_ein,
            "name": name,
            "total_linkages": len(linkages),
            "linkages": [l.to_dict() for l in linkages]
        })

    def handle_api_all_linkages(self, query):
        """API: Fetch cross-entity linkages detected across the entire database."""
        limit = int(query.get("limit", [100])[0])
        with self.lock:
            from .linkage import LinkageResolver
            resolver = LinkageResolver(self.storage)
            linkages = resolver.resolve_all_database_linkages(limit=limit)

        self.send_json_response({
            "total_linkages": len(linkages),
            "linkages": [l.to_dict() for l in linkages]
        })

    def handle_api_export(self):
        """API: Export active graph to standalone portable HTML."""
        # SECURITY: Validate launch token on mutation endpoints per Directive 5
        if self.launch_token:
            token_valid = False
            cookie_hdr = self.headers.get("Cookie", "")
            if f"irs990_token={self.launch_token}" in cookie_hdr:
                token_valid = True
            elif self.headers.get("X-Launch-Token") == self.launch_token:
                token_valid = True
            else:
                query_dict = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
                if query_dict.get("token", [""])[0] == self.launch_token:
                    token_valid = True

            if not token_valid:
                self.send_json_response({"error": "Forbidden: Invalid or missing launch token"}, status=403)
                return

        try:
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length).decode("utf-8")
            data = json.loads(body)

            target_name = data.get("target", {}).get("name", "organization")
            sanitized = "".join(c if c.isalnum() else "_" for c in target_name.lower()).strip("_")
            out_file = os.path.join("output", f"{sanitized}_snapshot.html")

            # Reconstruct NetworkGraph
            from .models import NetworkGraph, OrganizationNode, AggregatedGrantEdge, Relationship
            target_node = OrganizationNode.from_dict(data.get("target", {}))
            graph = NetworkGraph(target_node=target_node)
            for ein, n in data.get("nodes", {}).items():
                graph.nodes[ein] = OrganizationNode.from_dict(n)
            for k, e in data.get("grant_edges", {}).items():

                graph.grant_edges[k] = AggregatedGrantEdge(**e)
            for k, r in data.get("relationship_edges", {}).items():
                graph.relationship_edges[k] = Relationship(**r)

            self.generator.generate_html(graph, out_file, storage=self.storage)
            self.send_json_response({"success": True, "filepath": os.path.abspath(out_file), "filename": os.path.basename(out_file)})
        except Exception as e:
            logger.error(f"Error during export: {e}")
            self.send_json_response({"error": str(e)}, status=500)

    def handle_api_spending(self, ein: str):
        """API: Return functional expense breakdown and contractors for an organization."""
        with self.lock:
            target_ein = self.client.resolve_ein(ein) or ein
            expenses = [e.to_dict() for e in self.storage.get_expenses(target_ein)]
            contractors = [c.to_dict() for c in self.storage.get_contractors(target_ein)]
            org = self.storage.get_organization(target_ein)
            name = org.name if org else f"Organization {target_ein}"

        self.send_json_response({
            "ein": target_ein,
            "name": name,
            "expenses": expenses,
            "contractors": contractors
        })

    def handle_api_people(self, ein: str):
        """API: Return key officers/trustees for an organization with cross-board interlock details."""
        with self.lock:
            target_ein = self.client.resolve_ein(ein) or ein
            raw_people = self.storage.get_people_by_organization(target_ein)
            org = self.storage.get_organization(target_ein)
            name = org.name if org else f"Organization {target_ein}"

            people_data = []
            for p in raw_people:
                interlocks = self.storage.get_person_interlocks(p.clean_name)
                other_boards = [
                    {
                        "ein": itk["filer_ein"],
                        "name": itk["filer_name"],
                        "title": itk["title"],
                        "role_type": itk["role_type"]
                    }
                    for itk in interlocks if itk["filer_ein"] != target_ein
                ]
                d = p.to_dict()
                d["interlocks_count"] = len(other_boards)
                d["other_boards"] = other_boards
                people_data.append(d)

        self.send_json_response({
            "ein": target_ein,
            "name": name,
            "people": people_data
        })

    def handle_api_people_search(self, query):
        """API: Search people across all filings with cross-board interlock detection."""
        q = query.get("q", [""])[0].strip()
        if not q:
            self.send_json_response([])
            return

        with self.lock:
            people = self.storage.search_people(q, limit=20)
            res = []
            for p in people:
                interlocks = self.storage.get_person_interlocks(p.clean_name)
                d = p.to_dict()
                d["distinct_orgs"] = len(set(i["filer_ein"] for i in interlocks))
                d["interlocks"] = interlocks
                res.append(d)

        self.send_json_response(res)

    def handle_api_person_profile(self, query):
        """API: Detailed cross-filing profile for a specific person with role capacities and financials."""
        name = query.get("name", [""])[0].strip()
        if not name:
            self.send_json_response({"error": "Missing person name parameter"}, status=400)
            return

        with self.lock:
            from .parser import normalize_person_name
            norm_name = normalize_person_name(name)
            interlocks = self.storage.get_person_interlocks(name)
            if not interlocks and norm_name != name:
                interlocks = self.storage.get_person_interlocks(norm_name)

            if not interlocks:
                # Fallback to search if exact clean_name match wasn't found
                search_results = self.storage.search_people(name, limit=5)
                if search_results:
                    matched_person = search_results[0]
                    interlocks = self.storage.get_person_interlocks(matched_person.clean_name)
                    name = matched_person.person_name

            # Group all filings by organization EIN
            orgs_dict = {}
            total_comp_all = 0.0
            for itk in interlocks:
                ein = itk["filer_ein"]
                if ein not in orgs_dict:
                    orgs_dict[ein] = {
                        "ein": ein,
                        "name": itk["filer_name"],
                        "roles": [],
                        "total_comp": 0.0,
                        "min_year": itk["start_year"],
                        "max_year": itk["end_year"]
                    }
                org = orgs_dict[ein]
                comp = float(itk.get("total_comp") or 0.0)
                org["total_comp"] += comp
                total_comp_all += comp
                if itk["start_year"] and (not org["min_year"] or itk["start_year"] < org["min_year"]):
                    org["min_year"] = itk["start_year"]
                if itk["end_year"] and (not org["max_year"] or itk["end_year"] > org["max_year"]):
                    org["max_year"] = itk["end_year"]

                org["roles"].append({
                    "title": itk["title"],
                    "role_type": itk["role_type"],
                    "hours_per_week": itk["hours_per_week"],
                    "total_comp": comp,
                    "start_year": itk["start_year"],
                    "end_year": itk["end_year"]
                })

            res = {
                "person_name": name,
                "clean_name": norm_name,
                "total_organizations": len(orgs_dict),
                "total_compensation": total_comp_all,
                "affiliations": list(orgs_dict.values()),
                "raw_records": interlocks
            }

        self.send_json_response(res)

    def handle_api_interlocks(self):
        """API: Discover pairs of organizations sharing common board members or officers."""
        with self.lock:
            pairs = self.storage.get_interlocking_directorates(limit=100)
        self.send_json_response(pairs)

    def send_json_response(self, data, status: int = 200) -> None:
        """Send a JSON HTTP response with mandatory security headers.

        Args:
            data: Python dictionary or list serializable to JSON.
            status: HTTP status code. Defaults to 200.
        """
        content = json.dumps(data).encode("utf-8")
        content_type = get_verified_content_type("data.json", default="application/json; charset=utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Access-Control-Allow-Origin", "*")
        # SECURITY: Set HTTP security headers per Directive 5
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'self' 'unsafe-inline' data:; frame-ancestors 'none';")
        self.end_headers()
        self.wfile.write(content)

    def log_message(self, format: str, *args: Any) -> None:
        """Route internal server request logging cleanly to logger.

        Args:
            format: Log message format string.
            *args: Variable positional arguments for string interpolation.
        """
        # SECURITY: Sanitize client address and request logs per Directive 1
        client_addr = sanitize_log_path(self.address_string())
        logger.info(f"{client_addr} - {format % args}")


class ThreadedHTTPServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    """Multi-threaded HTTP server handling concurrent graph requests cleanly."""

    daemon_threads = True
    block_on_close = False
    allow_reuse_address = True


def start_server(
    host: str = "127.0.0.1",
    port: int = 8990,
    target_ein: str = "51-0198509",
    db_path: str = DEFAULT_DB_PATH,
    auto_open: bool = True
) -> None:
    """Start local interactive explorer server and attach terminal control loop.

    Args:
        host: Host IP interface to bind. Defaults to 127.0.0.1 (localhost only).
        port: TCP port to listen on. Defaults to 8990.
        target_ein: Initial organization EIN to anchor graph visualizer.
        db_path: Filesystem path to DuckDB database file.
        auto_open: If True, automatically launch user's default browser window unless headless.
    """
    storage = IRS990Storage(db_path)
    client = ProPublicaClient(storage)
    engine = FundingTraversalEngine(storage, client)
    generator = VisualizerGenerator()

    # Load seed foundations
    load_seed_data(storage)

    # Bind handler class variables
    fec_client = FECClient(storage)
    IRS990RequestHandler.storage = storage
    IRS990RequestHandler.client = client
    IRS990RequestHandler.fec_client = fec_client
    IRS990RequestHandler.engine = engine
    IRS990RequestHandler.generator = generator
    IRS990RequestHandler.default_ein = target_ein

    # SECURITY: Local web servers must bind strictly to 127.0.0.1 by default per Directive 5.
    server = ThreadedHTTPServer((host, port), IRS990RequestHandler)
    launch_token = secrets.token_hex(32)
    IRS990RequestHandler.launch_token = launch_token
    url = f"http://{host}:{port}/?token={launch_token}&ein={target_ein}"

    # Directive 3: Format launch URL as OSC 8 hyperlink on interactive TTY and route to stderr
    clickable_url = format_clickable_url(url, stream=sys.stderr)
    print("\n" + "=" * 70, file=sys.stderr)
    print(" 🚀 IRS 990 Interactive Explorer Server Running!", file=sys.stderr)
    print(f"    URL:    {clickable_url}", file=sys.stderr)
    print(f"    Target: EIN {target_ein}", file=sys.stderr)
    print("=" * 70, file=sys.stderr)

    # Directive 3: Automatically open user's default browser window unless suppressed or headless
    if auto_open and not is_headless_environment():
        try:
            import webbrowser
            timer = threading.Timer(0.8, lambda: webbrowser.open(url))
            timer.daemon = True
            timer.start()
        except Exception as e:
            logger.warning(f"Could not automatically launch browser: {e}")

    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()

    def stop_server():
        try:
            server.shutdown()
        except Exception:
            pass
        try:
            server.server_close()
        except Exception:
            pass
        try:
            storage.close()
        except Exception:
            pass
        try:
            from .cli import restore_terminal
            restore_terminal()
        except Exception:
            pass

    if sys.stdin.isatty():
        print("\n Interactive Control (Terminal accepts all input):", file=sys.stderr)
        print("  • Type 'open' or 'b' to re-open the browser", file=sys.stderr)
        print("  • Type an EIN (e.g. '51-0198509') or name to switch target organization", file=sys.stderr)
        print("  • Type 'status' for server info, 'help' for commands", file=sys.stderr)
        print("  • Type 'q', 'exit', or press Ctrl+C to stop server", file=sys.stderr)
        print("-" * 70, file=sys.stderr)
        try:
            while server_thread.is_alive():
                try:
                    cmd = input("irs990> ").strip()
                except (EOFError, KeyboardInterrupt):
                    print(file=sys.stderr)
                    break

                if not cmd:
                    continue

                lower = cmd.lower()
                if lower in ("q", "quit", "exit", "stop"):
                    break
                elif lower in ("help", "?"):
                    print("\nCommands:", file=sys.stderr)
                    print("  open, b           - Re-open browser at current graph", file=sys.stderr)
                    print("  status            - Display server URL and active target", file=sys.stderr)
                    print("  <EIN or Name>     - Switch target (e.g. '13-3109400' or 'Ford Foundation')", file=sys.stderr)
                    print("  q, exit           - Stop server and return to terminal\n", file=sys.stderr)
                elif lower in ("open", "b", "browser"):
                    curr_ein = IRS990RequestHandler.default_ein
                    curr_url = f"http://{host}:{port}/?ein={curr_ein}"
                    print(f"Opening browser at: {format_clickable_url(curr_url, stream=sys.stderr)}", file=sys.stderr)
                    if not is_headless_environment():
                        try:
                            import webbrowser
                            webbrowser.open(curr_url)
                        except Exception as e:
                            logger.warning(f"Could not open browser: {e}")
                elif lower == "status":
                    curr_ein = IRS990RequestHandler.default_ein
                    print(f"• Server URL: {format_clickable_url(f'http://{host}:{port}/?ein={curr_ein}', stream=sys.stderr)}", file=sys.stderr)
                    print(f"• Target EIN: {curr_ein}", file=sys.stderr)
                    print(f"• Database:   {db_path}", file=sys.stderr)
                else:
                    print(f"Resolving '{cmd}'...", file=sys.stderr)
                    resolved = client.resolve_ein(cmd)
                    if resolved:
                        IRS990RequestHandler.default_ein = resolved
                        node = client.get_organization(resolved)
                        name = node.name if node else resolved
                        new_url = f"http://{host}:{port}/?ein={resolved}"
                        print(f"✓ Active entity switched to '{name}' ({resolved})", file=sys.stderr)
                        print(f"  URL: {format_clickable_url(new_url, stream=sys.stderr)}", file=sys.stderr)
                        if not is_headless_environment():
                            try:
                                import webbrowser
                                webbrowser.open(new_url)
                            except Exception as e:
                                logger.warning(f"Could not open browser: {e}")
                    else:
                        print(f"✗ Could not resolve organization '{cmd}'. Type 'help' for options.", file=sys.stderr)
        finally:
            print("\nStopping server...", file=sys.stderr)
            stop_server()
    else:
        try:
            while server_thread.is_alive():
                import time
                time.sleep(0.5)
        except KeyboardInterrupt:
            print("\nStopping server...", file=sys.stderr)
        finally:
            stop_server()
