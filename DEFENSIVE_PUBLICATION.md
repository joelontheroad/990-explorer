<!--
SPDX-FileCopyrightText: 2026 990-Explorer Authors
SPDX-License-Identifier: AGPL-3.0-or-later
-->

# Defensive Patent Publication & Prior Art Disclosure

**Document Title:** Multi-Bridge Cross-Entity Political Linkage, Statutory Corporate Conduit Resolution, and Tax-Exempt Lineage Graph Architecture  
**Publication Date:** October 18, 2026  
**Assignee / Originator:** 990-Explorer Open Source Project  
**Author:** JoelG & 990-Explorer Contributors  
**Governing Statutory Standard:** Public Prior Art Disclosure under 35 U.S.C. § 102(a)(1) & Patent Cooperation Treaty (PCT) Article 33  
**License:** GNU Affero General Public License v3.0 or later (AGPL-3.0-or-later)  

---

## 1. Notice of Defensive Prior Art Publication

This document serves as an official, public, and irrevocable **Defensive Patent Publication** pursuant to **35 U.S.C. § 102(a)(1)** of the United States patent laws and international patent treaties. 

The technical specifications, architectural designs, algorithms, data structures, and mathematical heuristics disclosed herein are published publicly to establish **conclusive, date-stamped prior art**. Publication establishes that all methods, systems, and processes described in this document entered the public domain and were made available to the public worldwide prior to any subsequent patent filing by any third party. Consequently, any attempt by a third party, commercial competitor, or non-practicing entity (patent troll) to patent the inventions, systems, or variations disclosed herein is precluded under 35 U.S.C. §§ 102 (lack of novelty) and 103 (obviousness).

---

## 2. Technical Field

The present disclosure relates generally to the fields of computer science, relational database engineering, graph theory, public government records processing, and civic transparency systems. 

Specifically, it discloses computer-implemented methods, data schemas, and interactive user interfaces for:
1. Ingesting and cross-indexing heterogeneous public regulatory disclosures, including:
   - IRS Form 990 / 990-PF annual tax returns of tax-exempt organizations;
   - IRS Section 527 Political Organization Filing and Disclosure (POFD) reports (Forms 8871 and 8872);
   - Federal Election Commission (FEC) campaign finance bulk data (Committees, Candidates, Linkages, Independent Expenditures, and Operating Disbursements);
2. Resolving, scoring, and tracing indirect legal, corporate, and financial conduit pipelines between non-profit charities (501(c)(3) entities), social welfare organizations (501(c)(4) entities), and political committees (Super PACs, Hybrid PACs, Traditional PACs, and Section 527 committees);
3. Executing anchor-centric bidirectional lineage graph traversals across multi-hop pass-through grant distributions; and
4. Generating self-contained, single-file, interactive HTML visualizations that operate with complete offline privacy and zero remote network dependencies.

---

## 3. Detailed Technical Disclosures

### Disclosure 1: The 3-Bridge Cross-Entity Linkage & Conduit Resolution Engine

```
+-----------------------------------------------------------------------------------+
|                           Cross-Entity Resolution Engine                          |
+-----------------------------------------------------------------------------------+
|                                                                                   |
|  +--------------------+         Bridge 1: Connected Orgs / Schedule R             |
|  |   501(c)(3) /      | ----------------------------------------------------->    |
|  | 501(c)(4) Entities |     Matches FEC connected_org_nm and 8871 Part IV related  |
|  +--------------------+     entities against Schedule R corporate hierarchy        |
|            |                                                                      |
|            |                    Bridge 2: Leadership Interlocks                   |
|            +----------------------------------------------------------------->    |
|            |     Cross-references Form 990 Part VII officers & trustees against   |
|            |     FEC committee treasurers and Section 527 directors               |
|            |                                                                      |
|            |                    Bridge 3: Shared Commercial Vendors               |
|            +----------------------------------------------------------------->    |
|                  Correlates Form 990 Part VII Section B top contractors           |
|                  (>$100k) with FEC commercial operating disbursements (>$10k)     |
|                                                                                   |
+-----------------------------------------------------------------------------------+
```

The system implements a multi-source cross-entity linkage engine that uncovers and scores the financial and operational bridges connecting tax-exempt nonprofit organizations to political committees.

#### 1. Bridge 1: Connected Organizations & Schedule R Conduits
- **Mechanism:** The engine extracts corporate relationship declarations from IRS Form 990 Schedule R (Parts I through IV), compiling all known parent entities, subsidiaries, sister organizations, and disregarded entities associated with a root organization $O_1$.
- **Normalization:** Organization names are processed through a deterministic normalization function:
  $$\text{Normalize}(S) = \text{RegexReplace}(S, \text{Pattern}_{\text{legal\_suffixes}}, \epsilon)$$
  stripping leading articles ("THE "), punctuation, and corporate entity designations ("INCORPORATED", "INC", "LLC", "FOUNDATION", "ACTION FUND", "ASSOCIATION").
- **Resolution:** The normalized names and EINs are matched against:
  1. The Federal Election Commission `fec_committees.connected_org_name` field (from Committee Master bulk files);
  2. IRS Form 8871 Part IV `irs_527_related.related_org_name` and `irs_527_related.ein` records.
- **Conduit Pipeline Discovery:** When organization $O_1$ is a 501(c)(3) charity, and Schedule R identifies $O_2$ as a sister 501(c)(4) social welfare organization, and $O_2$ is registered as the connected organization of Super PAC $P_1$, the system synthesizes a multi-hop conduit pipeline:
  $$O_1 \xrightarrow{\text{Schedule R Sibling}} O_2 \xrightarrow{\text{Connected Org}} P_1$$
- **Confidence Scoring:** Assigns a deterministic confidence score:
  $$C_{\text{Bridge1}} = \begin{cases} 0.95 & \text{if direct target entity matches connected org} \\ 0.88 & \text{if conduit established via Schedule R affiliate} \end{cases}$$

#### 2. Bridge 2: Leadership Interlocks & Governance Overlaps
- **Mechanism:** The engine extracts natural person identifiers from:
  - Form 990 Part VII Section A & Form 990-PF Part VIII (Officers, Directors, Trustees, and Key Employees);
  - FEC Committee Master records (`treasurer_name`);
  - IRS Form 8871 Part II (`irs_527_officers`).
- **Person Name Normalization:** Names are parsed into structured components (First Name, Last Name, Middle Initial, Suffix) and cleaned of honorifics ("DR.", "ESQ.", "HON.").
- **Matching Criteria:** An interlock edge is instantiated when normalized $\text{LastName}$ matches and $\text{FirstName}$ matches exactly or matches standard nickname/alias dictionaries.
- **Confidence Scoring:**
  $$C_{\text{Bridge2}} = \begin{cases} 0.85 & \text{if exact First, Middle, and Last Name match} \\ 0.75 & \text{if First and Last Name match} \\ 0.65 & \text{if shared address or common entity context is verified} \end{cases}$$

#### 3. Bridge 3: Shared Commercial Political Vendors & Consultants
- **Mechanism:** The system identifies shared commercial contractors (e.g., political strategy firms, media buyers, direct-mail consultants, digital advertising agencies, and law firms) serving both tax-exempt charities and political committees.
- **Data Ingestion:**
  - Form 990 Part VII Section B: Top 5 independent contractors receiving more than $\$100,000$ for services;
  - FEC Operating Expenditures (`oppexp.txt`): Itemized disbursements exceeding $\$10,000$, capturing recipient name, disbursement purpose, date, and dollar amount.
- **Resolution:** Evaluates string similarity between normalized contractor names.
- **Confidence Scoring:**
  $$C_{\text{Bridge3}} = \min\left(0.80, 0.50 + 0.05 \times N_{\text{years\_active}} + 0.10 \times \mathbb{I}_{[\text{Disbursements} > \$500,000]}\right)$$

---

### Disclosure 2: Anchor-Centric Bidirectional Traversal with Secondary Cluster Bounding

```
      [Upstream Funder A] ---> (Grant) ---+
                                          |
      [Upstream Funder B] ---> (Grant) ---+--> [ TARGET ANCHOR ] ---+--> (Grant) ---> [Downstream Grantee X]
                                          |                         |
      [Schedule R Sister] <--(Affiliate)--+                         +--> (Grant) ---> [Downstream Grantee Y]
```

To eliminate the exponential "hairball" graph problem inherent in recursive multi-hop traversals:
1. **Anchor-Centric Hub Formulation:** The target organization is designated as the primary anchor ($D=0$).
2. **Directional BFS Expansion:** Inflows (upstream grantors) and outflows (downstream recipients) are discovered via Breadth-First Search up to user-defined depth $D_{\max} \in [1, 8]$.
3. **Starburst Cluster Suppression:** Direct edges incident to the target anchor are prioritized up to a branch limit $K$ ($K \le 30$). Secondary nodes ($D \ge 1$) are permitted to connect back to the target anchor and to each other (mutual cross-edges), but the system strictly suppresses the expansion of independent starburst clusters around secondary nodes unless the user explicitly recenters the graph.
4. **Multi-Year Edge Aggregation:** Multi-year grant transactions between identical source and destination nodes are aggregated into a single directed edge with cumulative dollar volume, grant count, and tax year range:
   $$V_{\text{edge}} = \sum_{t \in \text{Years}} \text{Amount}_t, \quad N_{\text{grants}} = |\text{Years}|$$

---

### Disclosure 3: Zero-Bandwidth Pre-Flight Freshness Probing

To prevent unnecessary multi-gigabyte downloads of public government archives while maintaining sub-second CLI responsiveness:
1. **Lightweight HTTP HEAD Probing:** Prior to initiating any synchronization of large public files (e.g., IRS EO BMF, IRS 527 POFD bulk zip, FEC committee files), the engine transmits a zero-bandwidth HTTP `HEAD` request (~500 bytes) to the official government endpoint.
2. **Metadata Extraction:** Extracts the server's HTTP `Last-Modified` and `ETag` headers.
3. **Database Comparison:** Queries the local DuckDB ingestion metadata log (`sync_history` / `data_sources`) for the timestamp of the last successful local ingestion.
4. **Conditional Bypass:** If $\text{Timestamp}_{\text{local}} \ge \text{Timestamp}_{\text{server}}$, the entire download, disk write, XML parsing, and database re-indexing pipelines are completely bypassed, completing in $< 1.0$ second with zero network bandwidth consumption.

---

### Disclosure 4: Self-Contained Offline Standalone HTML Graph Architecture

The visualization subsystem generates an entirely self-contained, standalone `.html` snapshot:
1. **Zero External CDN Dependencies:** All styling (CSS), layout rendering logic (Vis.js Network bundle), and icons are embedded directly within the single `.html` document. No external HTTP requests are made to CDNs (e.g., Google Fonts, unpkg, cdnjs).
2. **Embedded Relational Graph Serialization:** The complete graph topology (nodes, edges, financial metrics, Schedule R entities, and cross-entity PAC linkage dossiers) is serialized directly into an immutable JavaScript data structure (`GRAPH_DATA`) embedded in the document.
3. **Client-Side HUD Layer Toggles:** The standalone document incorporates client-side filtering logic allowing users to toggle graph layers (`💸 Grants & Funding`, `🏢 Schedule R Affiliates`, `🗳️ Political PACs & 527s`) and apply real-time minimum dollar threshold filters in $< 5\text{ ms}$ without communicating with any web server.
4. **Dynamic Physics Freeze:** The physics simulation executes a Barnes-Hut quadtree repulsive calculation and automatically stabilizes and freezes node coordinates upon reaching kinetic equilibrium, preventing ongoing CPU utilization.

---

### Disclosure 5: Hardened Localhost Web Server with Ephemeral Launch Tokens

When executed in interactive mode (`--serve` / `-s`):
1. **Localhost-Only Binding:** The server strictly binds to `127.0.0.1` (or `::1`), rejecting external network interface bindings by default.
2. **Cryptographic Ephemeral Token Authentication:** Upon launch, the server generates a cryptographically secure random token:
   $$\tau = \text{secrets.token\_hex}(32)$$
   The launch URL is printed to `stderr` as an OSC 8 clickable link (`http://127.0.0.1:8990/?token=...`). All mutating API endpoints require this token via `SameSite=Strict; HttpOnly` session headers to prevent local Cross-Site Request Forgery (CSRF).
3. **W3C Content Security Policy (CSP):** Every HTTP response emits strict security headers:
   ```http
   Content-Security-Policy: default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; object-src 'none'; frame-ancestors 'none';
   X-Content-Type-Options: nosniff
   X-Frame-Options: DENY
   Referrer-Policy: no-referrer
   ```

---

## 4. Prior Art Citations & Statutory Grounds

The methods and architectures disclosed herein build upon and distinguish themselves from the following statutory and academic foundations:

1. **Statutory Non-Profit & Campaign Disclosures:**
   - 26 U.S.C. § 501(c)(3), § 501(c)(4), § 527 (Internal Revenue Code);
   - 26 U.S.C. § 6033 (Returns by exempt organizations and Schedule R reporting);
   - 52 U.S.C. § 30101 et seq. (Federal Election Campaign Act).
2. **Internet & Data Standards:**
   - IETF RFC 9110 (HTTP Semantics, Section 9.3.2: `HEAD` method conditional validation);
   - REUSE Software Specification v3.0 (SPDX machine-readable software licensing).
3. **Graph Theory & Visualization:**
   - Peter Eades, *A Heuristic for Graph Drawing*, Congressus Numerantium, 42:149-160 (1984);
   - Thomas Fruchterman & Edward Reingold, *Graph Drawing by Force-Directed Placement*, Software: Practice and Experience, 21(11):1129-1164 (1991).

---

## 5. Non-Infringement & Freedom-to-Operate Declarations

The `990-explorer` architecture deliberately operates outside the claim boundaries of existing commercial patent portfolios:
- **Palantir Technologies (US 9,501,761 / US 9,857,960):** `990-explorer` uses a strictly local, single-user architecture with zero multi-tenant role-based data object redactions.
- **Dun & Bradstreet (US 8,700,515):** `990-explorer` relies exclusively on public statutory tax records (Form 990 Schedule R) and federal identifiers (EIN, FEC Committee ID), eschewing commercial securities crosswalks and proprietary D-U-N-S numbers.
- **Quantexa Ltd. (US 20260087059 A1):** `990-explorer` uses static relational SQL queries on DuckDB rather than dynamic multi-layered knowledge graph perspective transformation pipelines.

---

## 6. Conclusion & Legal Effect

By publication of this document on October 18, 2026, the `990-explorer` development team establishes this disclosure as **uncompromising prior art** under 35 U.S.C. § 102. 

Any subsequent patent application attempting to claim the multi-bridge non-profit-to-PAC resolution heuristics, anchor-centric traversal cluster suppression, zero-bandwidth freshness probing, or self-contained offline graph packaging described herein is unpatentable for lack of novelty and obviousness.

---
*End of Defensive Publication.*
