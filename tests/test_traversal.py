# SPDX-FileCopyrightText: 2026 990-Explorer Authors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Unit tests for Graph Traversal and Network Traversal Engine.

Architectural Purpose:
    Validates bidirectional recursive BFS traversal, funding hop thresholding,
    Cycle detection, and Schedule R relationship expansion in NetworkGraph.
"""

from irs990.storage import IRS990Storage
from irs990.seeds import load_seed_data
from irs990.traversal import FundingTraversalEngine
from irs990.visualizer import VisualizerGenerator
import os


def test_bidirectional_traversal():
    storage = IRS990Storage(":memory:")
    load_seed_data(storage)
    engine = FundingTraversalEngine(storage)

    # 1. Target Tides Foundation
    graph = engine.traverse("51-0198509", direction="both", max_depth=3, min_grant_amt=50000.0)
    assert graph.target_node.ein == "51-0198509"
    assert len(graph.nodes) >= 15
    assert len(graph.grant_edges) >= 15
    assert len(graph.relationship_edges) >= 3

    # Upstream check: Ford Foundation should be in nodes
    assert "13-1628106" in graph.nodes
    # Downstream check: Tides Center should be in nodes
    assert "94-3213100" in graph.nodes


def test_upstream_only_traversal():
    storage = IRS990Storage(":memory:")
    load_seed_data(storage)
    engine = FundingTraversalEngine(storage)

    graph = engine.traverse("51-0198509", direction="upstream", max_depth=2, include_schedule_r=False)
    # Check that downstream recipient CCR is NOT traversed
    assert "13-3921876" not in graph.nodes
    # Check that upstream funder Gates Foundation IS traversed
    assert "56-2618866" in graph.nodes


def test_visualizer_generation(tmp_path):
    storage = IRS990Storage(":memory:")
    load_seed_data(storage)
    engine = FundingTraversalEngine(storage)
    graph = engine.traverse("51-0198509", direction="both", max_depth=2)

    gen = VisualizerGenerator()
    out_file = str(tmp_path / "test_out.html")
    gen.generate_html(graph, out_file)

    assert os.path.exists(out_file)
    with open(out_file, "r", encoding="utf-8") as f:
        html = f.read()

    assert "Tides Foundation" in html
    assert "vis.Network" in html
    assert "GRAPH_DATA" in html


def test_rerooting_traversal():
    """Verify that re-rooting the graph from an upstream donor correctly flips downstream links."""
    storage = IRS990Storage(":memory:")
    load_seed_data(storage)
    engine = FundingTraversalEngine(storage)

    # 1. Start with Tides as target
    g_tides = engine.traverse("51-0198509", direction="both", max_depth=2)
    assert g_tides.target_node.ein == "51-0198509"
    assert g_tides.target_node.is_target is True
    fidelity_in_tides = g_tides.nodes.get("04-3132178")
    assert fidelity_in_tides is not None
    assert fidelity_in_tides.direction == "upstream"

    # 2. Re-root on Fidelity (04-3132178)
    g_fidelity = engine.traverse("04-3132178", direction="both", max_depth=2)
    assert g_fidelity.target_node.ein == "04-3132178"
    assert g_fidelity.target_node.is_target is True
    assert g_fidelity.target_node.direction == "target"

    # Tides must now be downstream of Fidelity!
    tides_in_fidelity = g_fidelity.nodes.get("51-0198509")
    assert tides_in_fidelity is not None
    assert tides_in_fidelity.direction == "downstream"

    # Other recipients of Fidelity must also be downstream
    nvf_in_fidelity = g_fidelity.nodes.get("20-5205488")
    assert nvf_in_fidelity is not None
    assert nvf_in_fidelity.direction == "downstream"

