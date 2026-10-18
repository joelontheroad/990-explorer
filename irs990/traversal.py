# SPDX-FileCopyrightText: 2026 990-Explorer Authors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Graph Traversal Engine for IRS 990 Funding Lineage and Corporate Relationships.

Architectural Purpose:
    Implements bidirectional breadth-first search (BFS) recursive traversal
    with cycle prevention, multi-year grant edge aggregation, pruning,
    Schedule R corporate hierarchy expansion, and PAC bridge connectivity.
"""

import logging
from collections import deque
from typing import Optional, List, Dict, Set, Tuple
from .models import (
    OrganizationNode,
    FundingGrant,
    Relationship,
    AggregatedGrantEdge,
    NetworkGraph
)
from .storage import IRS990Storage
from .client import ProPublicaClient

logger = logging.getLogger(__name__)


class FundingTraversalEngine:
    def __init__(self, storage: IRS990Storage, client: Optional[ProPublicaClient] = None):
        self.storage = storage
        self.client = client or ProPublicaClient(storage)

    def traverse(
        self,
        target_ein: str,
        direction: str = "both",          # "both", "upstream", "downstream"
        max_depth: int = 1,
        min_grant_amt: float = 10000.0,
        start_year: Optional[int] = None,
        end_year: Optional[int] = None,
        top_n_per_hop: int = 30,
        include_schedule_r: bool = True,
        include_pacs: bool = True
    ) -> NetworkGraph:
        """
        Execute anchor-centric traversal. The Anchor Entity is the primary hub.
        Direct inflows and outflows are expanded up to top_n_per_hop.
        Secondary nodes connect to the Anchor and mutual cross-edges are added without
        spawning competing 'sub anchor' starburst clusters.
        """
        # Ensure target node exists and has details
        target_node = self.storage.get_organization(target_ein)
        if not target_node:
            target_node = self.client.get_organization(target_ein)
        
        if not target_node:
            target_node = OrganizationNode(
                ein=target_ein,
                name=f"Organization {target_ein}",
                is_target=True
            )
        else:
            target_node.is_target = True

        target_node.depth = 0
        target_node.direction = "target"

        graph = NetworkGraph(target_node=target_node)
        graph.add_node(target_node)

        # BFS queue: (ein, current_depth, path_direction)
        queue = deque()
        visited: Set[Tuple[str, str]] = set()

        dir_clean = (direction or "both").lower().strip()
        if dir_clean in ["upstream", "both", "all"]:
            queue.append((target_ein, 0, "upstream"))
            visited.add((target_ein, "upstream"))

        if dir_clean in ["downstream", "both", "all"]:
            queue.append((target_ein, 0, "downstream"))
            visited.add((target_ein, "downstream"))

        while queue:
            curr_ein, curr_depth, curr_dir = queue.popleft()

            # Schedule R expansion for anchor
            if include_schedule_r and curr_depth == 0:
                rels = self.storage.get_relationships(curr_ein)
                for rel in rels:
                    graph.add_relationship(rel)
                    other_ein = rel.related_ein if rel.entity_ein == curr_ein else rel.entity_ein
                    other_name = rel.related_name if rel.entity_ein == curr_ein else rel.entity_name
                    
                    if other_ein and other_ein not in graph.nodes:
                        rel_node = self.storage.get_organization(other_ein)
                        if not rel_node:
                            rel_node = OrganizationNode(
                                ein=other_ein,
                                name=other_name or f"Related Org {other_ein}",
                                depth=curr_depth + 1,
                                direction="related"
                            )
                        else:
                            rel_node.depth = min(rel_node.depth or (curr_depth + 1), curr_depth + 1)
                            rel_node.direction = "related"
                        graph.add_node(rel_node)

            # PAC & Political Committee expansion for anchor
            if include_pacs and curr_depth == 0:
                try:
                    from .linkage import LinkageResolver
                    resolver = LinkageResolver(self.storage)
                    linkages = resolver.resolve_organization_linkages(curr_ein)
                    for link in linkages:
                        # Determine originating node (sister entity or anchor)
                        origin_ein = curr_ein
                        origin_name = target_node.name
                        rel_role = link.evidence.get("relation_role", "")
                        if "Schedule R" in rel_role:
                            matched = link.evidence.get("matched_entity", "")
                            for n_ein, n_node in graph.nodes.items():
                                if n_node.name == matched:
                                    origin_ein = n_ein
                                    origin_name = n_node.name
                                    break

                        pac_type_label = "Super PAC" if link.target_type == "fec_pac" else "527 Political Org"
                        pac_node = OrganizationNode(
                            ein=link.target_id,
                            name=link.target_name,
                            tax_status=pac_type_label,
                            depth=curr_depth + 1,
                            direction="pac",
                            metadata={
                                "is_pac": True,
                                "target_type": link.target_type,
                                "link_type": link.link_type,
                                "confidence": link.confidence_score,
                                "evidence": link.evidence,
                                "description": link.description
                            }
                        )
                        graph.add_node(pac_node)

                        rel_labels = {
                            "connected_org": "Connected PAC",
                            "schedule_r_conduit": "Sister Conduit PAC",
                            "shared_leadership": "Shared Leadership",
                            "shared_contractor": "Shared Vendor"
                        }
                        rel_type = rel_labels.get(link.link_type, "Affiliated PAC")

                        rel_edge = Relationship(
                            entity_ein=origin_ein,
                            entity_name=origin_name,
                            related_ein=link.target_id,
                            related_name=link.target_name,
                            relationship_type=rel_type,
                            primary_activity=link.description,
                            source_schedule="PAC Linkage"
                        )
                        graph.add_relationship(rel_edge)
                except Exception as e:
                    logger.warning(f"Failed resolving PAC linkages for {curr_ein}: {e}")

            if curr_depth >= max_depth:
                continue

            # Process grants according to current branch direction
            if curr_dir == "upstream":
                inbound = self.storage.get_inbound_grants(
                    recipient_ein=curr_ein,
                    min_amount=min_grant_amt,
                    start_year=start_year,
                    end_year=end_year
                )
                # Sort by amount descending and cap at top_n_per_hop
                inbound.sort(key=lambda g: g.amount, reverse=True)
                for grant in inbound[:top_n_per_hop]:
                    graph.add_grant(grant)
                    grantor_ein = grant.grantor_ein
                    if grantor_ein not in graph.nodes:
                        grantor_node = self.storage.get_organization(grantor_ein)
                        if not grantor_node:
                            grantor_node = OrganizationNode(
                                ein=grantor_ein,
                                name=grant.grantor_name,
                                depth=curr_depth + 1,
                                direction="upstream"
                            )
                        else:
                            grantor_node.depth = min(grantor_node.depth or (curr_depth + 1), curr_depth + 1)
                            grantor_node.direction = "upstream"
                        graph.add_node(grantor_node)

                    if curr_depth + 1 < max_depth and (grantor_ein, "upstream") not in visited:
                        visited.add((grantor_ein, "upstream"))
                        queue.append((grantor_ein, curr_depth + 1, "upstream"))

            elif curr_dir == "downstream":
                outbound = self.storage.get_outbound_grants(
                    grantor_ein=curr_ein,
                    min_amount=min_grant_amt,
                    start_year=start_year,
                    end_year=end_year
                )
                outbound.sort(key=lambda g: g.amount, reverse=True)
                for grant in outbound[:top_n_per_hop]:
                    graph.add_grant(grant)
                    recip_ein = grant.recipient_ein
                    if recip_ein not in graph.nodes:
                        recip_node = self.storage.get_organization(recip_ein)
                        if not recip_node:
                            recip_node = OrganizationNode(
                                ein=recip_ein,
                                name=grant.recipient_name,
                                depth=curr_depth + 1,
                                direction="downstream"
                            )
                        else:
                            recip_node.depth = min(recip_node.depth or (curr_depth + 1), curr_depth + 1)
                            recip_node.direction = "downstream"
                        graph.add_node(recip_node)

                    if curr_depth + 1 < max_depth and (recip_ein, "downstream") not in visited:
                        visited.add((recip_ein, "downstream"))
                        queue.append((recip_ein, curr_depth + 1, "downstream"))

        # Cross-connections pass: add any mutual grants strictly between nodes in active graph
        all_eins = set(graph.nodes.keys())
        for node_ein in all_eins:
            if node_ein == target_ein:
                continue
            outbound_cross = self.storage.get_outbound_grants(
                grantor_ein=node_ein,
                min_amount=min_grant_amt,
                start_year=start_year,
                end_year=end_year
            )
            for cg in outbound_cross:
                if cg.recipient_ein in all_eins:
                    graph.add_grant(cg)

        return graph

