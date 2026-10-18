# SPDX-FileCopyrightText: 2026 990-Explorer Authors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Unit Tests for IRS 990 Interactive Local Server & Dynamic Recenter API.

Architectural Purpose:
    Validates REST API endpoints, OSC 8 terminal hyperlink formatting, headless
    environment detection, security headers, and CLI 'serve' subcommand parsing.
"""

import json
import os
import tempfile
import urllib.request
import urllib.error
import threading
import time
import pytest

from irs990.storage import IRS990Storage
from irs990.client import ProPublicaClient
from irs990.seeds import load_seed_data
from irs990.traversal import FundingTraversalEngine
from irs990.visualizer import VisualizerGenerator
from irs990.server import ThreadedHTTPServer, IRS990RequestHandler


@pytest.fixture(scope="module")
def live_server():
    """Spin up a test HTTP server on an ephemeral port."""
    temp_dir = tempfile.TemporaryDirectory()
    db_path = os.path.join(temp_dir.name, "test_server.duckdb")
    storage = IRS990Storage(db_path)
    client = ProPublicaClient(storage)
    engine = FundingTraversalEngine(storage, client)
    generator = VisualizerGenerator()

    # Load seed data
    load_seed_data(storage)

    # Bind request handler
    IRS990RequestHandler.storage = storage
    IRS990RequestHandler.client = client
    IRS990RequestHandler.engine = engine
    IRS990RequestHandler.generator = generator
    IRS990RequestHandler.default_ein = "51-0198509"

    # Use port 0 to bind an available ephemeral port
    server = ThreadedHTTPServer(("127.0.0.1", 0), IRS990RequestHandler)
    port = server.server_address[1]

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    time.sleep(0.1)

    base_url = f"http://127.0.0.1:{port}"
    yield {"base_url": base_url, "storage": storage, "db_path": db_path}

    server.shutdown()
    server.server_close()
    storage.close()
    temp_dir.cleanup()


def test_server_index(live_server):
    """Test root endpoint serves HTML with server mode enabled."""
    url = f"{live_server['base_url']}/"
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req) as resp:
        assert resp.status == 200
        content = resp.read().decode("utf-8")
        assert "IRS 990 Explorer" in content
        assert "Live Server" in content
        assert "recenterOnEntity" in content
        assert "progress-overlay" in content


def test_server_api_explore(live_server):
    """Test /api/explore endpoint returns full graph JSON for target EIN."""
    url = f"{live_server['base_url']}/api/explore?ein=51-0198509&depth=2&min_grant=10000"
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req) as resp:
        assert resp.status == 200
        data = json.loads(resp.read().decode("utf-8"))
        assert "target" in data
        assert data["target"]["ein"] == "51-0198509"
        assert "nodes" in data
        assert "51-0198509" in data["nodes"]
        assert "stats" in data
        assert data["stats"]["total_nodes"] > 0
        assert "grant_edges" in data
        assert "relationship_edges" in data


def test_server_api_explore_fidelity_direction_all(live_server):
    """Test /api/explore with Fidelity EIN and direction=all connects to Tides Foundation and grantees."""
    url = f"{live_server['base_url']}/api/explore?ein=04-3132178&direction=all&depth=2&min_grant=10000"
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req) as resp:
        assert resp.status == 200
        data = json.loads(resp.read().decode("utf-8"))
        assert data["target"]["ein"] == "04-3132178"
        # Must show connection to Tides Foundation (51-0198509)
        assert "51-0198509" in data["nodes"]
        # Must show connection to other recipients like New Venture Fund (20-5205488)
        assert "20-5205488" in data["nodes"]
        assert data["stats"]["total_nodes"] > 1
        assert data["stats"]["total_grants"] > 1


def test_server_api_search(live_server):
    """Test /api/search endpoint returns matching organizations."""
    url = f"{live_server['base_url']}/api/search?q=Tides"
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req) as resp:
        assert resp.status == 200
        results = json.loads(resp.read().decode("utf-8"))
        assert isinstance(results, list)
        assert len(results) > 0
        assert any("Tides" in r["name"] for r in results)


def test_server_api_export(live_server):
    """Test /api/export endpoint generates standalone HTML file."""
    # First get explore data
    explore_url = f"{live_server['base_url']}/api/explore?ein=51-0198509&depth=2"
    with urllib.request.urlopen(explore_url) as resp:
        data = json.loads(resp.read().decode("utf-8"))

    export_url = f"{live_server['base_url']}/api/export"
    post_data = json.dumps(data).encode("utf-8")
    req = urllib.request.Request(export_url, data=post_data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req) as resp:
        assert resp.status == 200
        res_json = json.loads(resp.read().decode("utf-8"))
        assert res_json.get("success") is True
        filepath = res_json.get("filepath")
        assert os.path.exists(filepath)


def test_server_api_explore_retrieve(live_server):
    """Test /api/explore with retrieve=1 triggers fetch_and_ingest_latest_filing and returns retrieval info."""
    from unittest.mock import patch

    with patch.object(IRS990RequestHandler.client, "fetch_and_ingest_latest_filing") as mock_fetch:
        mock_fetch.return_value = {
            "status": "ingested",
            "ein": "51-0198509",
            "tax_period": "2023-12",
            "grants_ingested": 42
        }
        url = f"{live_server['base_url']}/api/explore?ein=51-0198509&retrieve=1&depth=2"
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req) as resp:
            assert resp.status == 200
            data = json.loads(resp.read().decode("utf-8"))
            assert data["target"]["ein"] == "51-0198509"
            assert "retrieval" in data
            assert data["retrieval"]["status"] == "ingested"
            assert data["retrieval"]["grants_ingested"] == 42
            mock_fetch.assert_called_once_with("51-0198509", force=False)


def test_server_api_spending(live_server):
    """Test /api/organization/{ein}/spending endpoint returns functional expenses and contractors."""
    url = f"{live_server['base_url']}/api/organization/51-0198509/spending"
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req) as resp:
        assert resp.status == 200
        data = json.loads(resp.read().decode("utf-8"))
        assert data["ein"] == "51-0198509"
        assert "Tides Foundation" in data["name"]
        assert len(data["expenses"]) >= 1
        assert data["expenses"][0]["program_percentage"] == 90.0
        assert len(data["contractors"]) >= 1
        assert any("Arabella" in c["contractor_name"] for c in data["contractors"])


def test_server_api_people(live_server):
    """Test /api/organization/{ein}/people endpoint returns officers, trustees, and interlock counts."""
    url = f"{live_server['base_url']}/api/organization/51-0198509/people"
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req) as resp:
        assert resp.status == 200
        data = json.loads(resp.read().decode("utf-8"))
        assert data["ein"] == "51-0198509"
        assert len(data["people"]) >= 3

        # Amanda Keton should have cross-board interlock details
        keton = next(p for p in data["people"] if "AMANDA" in p["clean_name"])
        assert keton["interlocks_count"] >= 1
        assert any(b["ein"] == "94-3213100" for b in keton["other_boards"])


def test_server_api_people_search(live_server):
    """Test /api/people/search endpoint searches individuals across all filings."""
    url = f"{live_server['base_url']}/api/people/search?q=Keton"
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req) as resp:
        assert resp.status == 200
        results = json.loads(resp.read().decode("utf-8"))
        assert len(results) >= 1
        assert any("AMANDA KETON" in r["clean_name"] for r in results)


def test_server_api_interlocks(live_server):
    """Test /api/interlocks endpoint returns cross-organizational leadership pairs."""
    url = f"{live_server['base_url']}/api/interlocks"
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req) as resp:
        assert resp.status == 200
        pairs = json.loads(resp.read().decode("utf-8"))
        assert len(pairs) >= 2
        shared_names = {p["shared_person"] for p in pairs}
        assert "AMANDA KETON" in shared_names


def test_server_api_person_profile(live_server):
    """Test /api/person/profile returns cross-filing affiliations and role capacities for a person."""
    url = f"{live_server['base_url']}/api/person/profile?name=Amanda%20Keton"
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req) as resp:
        assert resp.status == 200
        profile = json.loads(resp.read().decode("utf-8"))
        assert "Amanda Keton" in profile["person_name"]
        assert profile["total_organizations"] >= 2
        assert len(profile["affiliations"]) >= 2
        eins = {a["ein"] for a in profile["affiliations"]}
        assert "51-0198509" in eins  # Tides Foundation
        assert "94-3213100" in eins  # Tides Center
        # Verify roles have title, role_type, comp
        roles = [r for a in profile["affiliations"] for r in a["roles"]]
        assert any(r["title"] for r in roles)
        assert any(r["role_type"] for r in roles)


def test_server_api_search_omni(live_server):
    """Test /api/search/omni multi-entity search endpoint."""
    url = f"{live_server['base_url']}/api/search/omni?q=Tides"
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req) as resp:
        assert resp.status == 200
        results = json.loads(resp.read().decode("utf-8"))
        assert "organizations" in results
        assert len(results["organizations"]) >= 2
        assert any("Tides Foundation" in o["name"] for o in results["organizations"])


def test_server_api_contractor_dossier(live_server):
    """Test /api/contractor/dossier endpoint returns commercial profile."""
    url = f"{live_server['base_url']}/api/contractor/dossier?name=Arabella"
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req) as resp:
        assert resp.status == 200
        dossier = json.loads(resp.read().decode("utf-8"))
        assert "contractor_name" in dossier
        assert "Arabella" in dossier["contractor_name"]
        assert dossier["total_amount"] > 0
        assert len(dossier["clients"]) >= 1


def test_server_api_527_org(live_server):
    """Test /api/527/org/{id} endpoint with sample 527 organization."""
    # Seed a 527 org into the live server storage
    storage = live_server["storage"]
    storage.upsert_527_orgs([(
        "9999", "Majority Forward", "81-1234567", "8871", "611 Pennsylvania Ave", "",
        "Washington", "DC", "20003", "info@majorityforward.org", "John Smith",
        "Engaging citizens in policy dialogue", "2024-01-01"
    )])
    storage.upsert_527_directors([(
        "9999:1:JANE DOE", "9999", "Majority Forward", "81-1234567", "Jane Doe",
        "JANE DOE", "President", "611 Pennsylvania Ave", "Washington", "DC", "20003"
    )])

    url = f"{live_server['base_url']}/api/527/org/9999"
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req) as resp:
        assert resp.status == 200
        data = json.loads(resp.read().decode("utf-8"))
        assert data["org_name"] == "Majority Forward"
        assert data["ein"] == "81-1234567"
        assert len(data["directors"]) >= 1
        assert data["directors"][0]["clean_name"] == "JANE DOE"


def test_server_api_explore_includes_pacs_loaded(live_server):
    """Test /api/explore includes pre-populated pacsLoaded dictionary."""
    url = f"{live_server['base_url']}/api/explore?ein=51-0198509"
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req) as resp:
        assert resp.status == 200
        data = json.loads(resp.read().decode("utf-8"))
        assert "pacsLoaded" in data
        assert isinstance(data["pacsLoaded"], dict)


def test_server_index_includes_layer_controls_and_injection(live_server):
    """Test index HTML contains HUD layer toggles, candidate styling, and injection scripts."""
    url = f"{live_server['base_url']}/"
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req) as resp:
        assert resp.status == 200
        html = resp.read().decode("utf-8")
        assert 'id="layer-grants"' in html
        assert 'id="layer-affiliates"' in html
        assert 'id="layer-pacs"' in html
        assert "applyFilterVisibility" in html
        assert "injectPacIntoGraph" in html
        assert "injectCandidateIntoGraph" in html
        assert "openCandidateDrawer" in html
        assert "pacsLoaded" in html


def test_visualizer_offline_bundle_export(tmp_path, live_server):
    """Test VisualizerGenerator.generate_html pre-populates offline dossiers and linkages."""
    from irs990.models import NetworkGraph, OrganizationNode
    from irs990.visualizer import VisualizerGenerator

    storage = live_server["storage"]
    target = OrganizationNode(ein="51-0198509", name="Tides Foundation", is_target=True)
    graph = NetworkGraph(target_node=target)
    graph.nodes[target.ein] = target

    out_file = str(tmp_path / "offline_snapshot.html")
    gen = VisualizerGenerator()
    gen.generate_html(graph, out_file, is_server_mode=False, storage=storage)

    with open(out_file, "r", encoding="utf-8") as f:
        content = f.read()

    assert "GRAPH_DATA" in content
    assert "pacsLoaded" in content
    assert "fecDossiers" in content
    assert "sec527Dossiers" in content
    assert 'id="layer-pacs"' in content
    assert "applyFilterVisibility" in content


def test_format_clickable_url():
    """Verify OSC 8 clickable link emission on interactive TTY and plain text fallback."""
    import io
    from irs990.server import format_clickable_url

    class MockTTYStream(io.StringIO):
        def isatty(self):
            return True

    class MockNonTTYStream(io.StringIO):
        def isatty(self):
            return False

    url = "http://127.0.0.1:8990/?ein=51-0198509"

    # 1. Non-TTY stream returns plain text URL
    non_tty = MockNonTTYStream()
    assert format_clickable_url(url, stream=non_tty) == url

    # 2. Interactive TTY stream without NO_COLOR returns OSC 8 hyperlink sequence
    tty = MockTTYStream()
    old_no_color = os.environ.pop("NO_COLOR", None)
    try:
        formatted = format_clickable_url(url, stream=tty)
        assert formatted.startswith("\033]8;;")
        assert formatted.endswith("\033]8;;\033\\")
        assert url in formatted

        # 3. Interactive TTY with NO_COLOR active falls back to clean plain text
        os.environ["NO_COLOR"] = "1"
        assert format_clickable_url(url, stream=tty) == url
    finally:
        if old_no_color is not None:
            os.environ["NO_COLOR"] = old_no_color
        else:
            os.environ.pop("NO_COLOR", None)


def test_is_headless_environment(monkeypatch):
    """Verify headless detection under CI and headless Linux environments."""
    from irs990.server import is_headless_environment

    # CI=true forces headless
    monkeypatch.setenv("CI", "true")
    assert is_headless_environment() is True

    # CI unset
    monkeypatch.delenv("CI", raising=False)
    if os.name == "posix":
        # Missing display on Linux is headless
        monkeypatch.delenv("DISPLAY", raising=False)
        monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
        assert is_headless_environment() is True

        # Present display is not headless
        monkeypatch.setenv("DISPLAY", ":0")
        assert is_headless_environment() is False


def test_cli_serve_subcommand_and_flag_parsing():
    """Verify CLI parsing for both 'serve --no-browser' subcommand and '--serve' flag."""
    from irs990.cli import parse_args

    # Subcommand style: irs990 serve --no-browser -p 9999
    args_sub = parse_args(["serve", "--no-browser", "-p", "9999", "--host", "127.0.0.1"])
    assert args_sub.subcommand == "serve"
    assert args_sub.serve is True
    assert args_sub.no_browser is True
    assert args_sub.port == 9999
    assert args_sub.host == "127.0.0.1"

    # Flag style: irs990 --serve --no-browser
    args_flag = parse_args(["--serve", "--no-browser", "--port", "8888"])
    assert args_flag.serve is True
    assert args_flag.no_browser is True
    assert args_flag.port == 8888


def test_server_security_headers(live_server):
    """Verify standard security headers are present on server responses."""
    url = f"{live_server['base_url']}/"
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req) as resp:
        headers = dict(resp.getheaders())
        assert headers.get("X-Content-Type-Options") == "nosniff"
        assert headers.get("X-Frame-Options") == "DENY"
        assert headers.get("Referrer-Policy") == "no-referrer"

