# SPDX-FileCopyrightText: 2026 990-Explorer Authors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Standalone Portable HTML Generator for IRS 990 Network Graph.

Architectural Purpose:
    Renders self-contained interactive network visualizations (Vis.js Network)
    with local bundled assets, physics controls, multi-entity omni-search,
    connected PAC drawers, contractor dossiers, and export capabilities.

Security Invariants:
    - Bundles all CSS, JS, and font assets locally with zero external CDN dependencies per Directive 3.
    - Sanitizes embedded JSON payloads against Cross-Site Scripting (XSS / CWE-79).
"""

import os
import json
import logging
from typing import Dict, Any, Optional
from jinja2 import Template
from .models import NetworkGraph

logger = logging.getLogger(__name__)

ASSETS_DIR = os.path.join(os.path.dirname(__file__), "assets")


def format_currency(val: float) -> str:
    """Format numeric dollar amount into clean currency string."""
    if val >= 1_000_000_000:
        return f"${val / 1_000_000_000:.2f}B"
    elif val >= 1_000_000:
        return f"${val / 1_000_000:.2f}M"
    elif val >= 1_000:
        return f"${val / 1_000:.1f}K"
    else:
        return f"${val:,.0f}"


def format_currency_full(val: float) -> str:
    return f"${val:,.2f}"


HTML_TEMPLATE = """<!--
SPDX-FileCopyrightText: 2026 990-Explorer Authors
SPDX-License-Identifier: AGPL-3.0-or-later
-->
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{{ graph.target_node.name }} - IRS 990 Funding & Lineage Graph</title>
    <style>
        {{ vis_css }}

        :root {
            --bg-color: #0b0f19;
            --surface-color: rgba(17, 24, 39, 0.88);
            --surface-border: rgba(255, 255, 255, 0.1);
            --text-primary: #f3f4f6;
            --text-secondary: #9ca3af;
            --accent-target: #f59e0b;
            --accent-upstream: #06b6d4;
            --accent-downstream: #10b981;
            --accent-rel: #a855f7;
            --card-hover: rgba(255, 255, 255, 0.05);
            --font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
        }

        body.light-mode {
            --bg-color: #f8fafc;
            --surface-color: rgba(255, 255, 255, 0.94);
            --surface-border: rgba(0, 0, 0, 0.1);
            --text-primary: #0f172a;
            --text-secondary: #64748b;
            --card-hover: rgba(0, 0, 0, 0.03);
        }

        * {
            box-sizing: border-box;
            margin: 0;
            padding: 0;
            font-family: var(--font-family);
        }

        body, html {
            width: 100vw;
            height: 100vh;
            max-width: 100vw;
            max-height: 100vh;
            margin: 0;
            padding: 0;
            overflow: hidden !important;
            background-color: var(--bg-color);
            color: var(--text-primary);
            transition: background-color 0.3s ease, color 0.3s ease;
            position: fixed;
            top: 0;
            left: 0;
            right: 0;
            bottom: 0;
        }

        /* App Header */
        header {
            position: fixed;
            top: 0;
            left: 0;
            right: 0;
            width: 100vw;
            max-width: 100vw;
            height: 60px;
            background: var(--surface-color);
            backdrop-filter: blur(14px);
            -webkit-backdrop-filter: blur(14px);
            border-bottom: 1px solid var(--surface-border);
            display: flex;
            align-items: center;
            justify-content: space-between;
            padding: 0 16px;
            z-index: 50;
            box-sizing: border-box;
            gap: 10px;
            overflow: hidden;
        }

        .header-title-group {
            display: flex;
            align-items: center;
            gap: 10px;
            flex: 1 1 auto;
            min-width: 0;
            overflow: hidden;
        }

        .header-title {
            font-size: 1rem;
            font-weight: 700;
            letter-spacing: -0.02em;
            display: flex;
            align-items: center;
            gap: 8px;
            white-space: nowrap;
            flex-shrink: 0;
        }

        .badge-target {
            background: rgba(245, 158, 11, 0.2);
            color: var(--accent-target);
            border: 1px solid rgba(245, 158, 11, 0.4);
            font-size: 0.75rem;
            font-weight: 600;
            padding: 3px 8px;
            border-radius: 9999px;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
            max-width: 180px;
            flex-shrink: 1;
        }

        .server-mode-pill {
            background: rgba(16, 185, 129, 0.15);
            color: #10b981;
            border: 1px solid rgba(16, 185, 129, 0.3);
            font-size: 0.7rem;
            font-weight: 600;
            padding: 2px 7px;
            border-radius: 9999px;
            display: flex;
            align-items: center;
            gap: 4px;
            white-space: nowrap;
            flex-shrink: 0;
        }

        .server-mode-pill::before {
            content: "";
            display: inline-block;
            width: 6px;
            height: 6px;
            border-radius: 50%;
            background: #10b981;
            box-shadow: 0 0 6px #10b981;
            animation: pulse-dot 2s infinite;
        }

        @keyframes pulse-dot {
            0%, 100% { opacity: 1; transform: scale(1); }
            50% { opacity: 0.4; transform: scale(0.85); }
        }

        /* Breadcrumbs Trail */
        .breadcrumbs-container {
            display: flex;
            align-items: center;
            gap: 6px;
            margin-left: 6px;
            overflow-x: auto;
            max-width: 280px;
            scrollbar-width: none;
            flex-shrink: 2;
        }
        .breadcrumbs-container::-webkit-scrollbar { display: none; }

        .breadcrumb-pill {
            background: var(--card-hover);
            border: 1px solid var(--surface-border);
            padding: 3px 10px;
            border-radius: 9999px;
            font-size: 0.72rem;
            font-weight: 600;
            color: var(--text-secondary);
            cursor: pointer;
            white-space: nowrap;
            transition: all 0.2s ease;
        }

        .breadcrumb-pill:hover {
            color: var(--text-primary);
            border-color: rgba(255, 255, 255, 0.3);
            background: rgba(255, 255, 255, 0.08);
        }

        .breadcrumb-pill.active {
            background: rgba(245, 158, 11, 0.2);
            border-color: rgba(245, 158, 11, 0.5);
            color: var(--accent-target);
        }

        .breadcrumb-sep {
            color: var(--text-secondary);
            font-size: 0.72rem;
            opacity: 0.6;
            user-select: none;
        }

        .header-stats {
            display: flex;
            align-items: center;
            gap: 8px;
            flex-shrink: 0;
        }

        .stat-pill {
            background: var(--card-hover);
            border: 1px solid var(--surface-border);
            padding: 4px 9px;
            border-radius: 8px;
            font-size: 0.75rem;
            color: var(--text-secondary);
            white-space: nowrap;
        }

        .stat-pill strong {
            color: var(--text-primary);
        }

        .header-actions {
            display: flex;
            align-items: center;
            gap: 6px;
            flex-shrink: 0;
        }

        .btn {
            background: var(--surface-color);
            border: 1px solid var(--surface-border);
            color: var(--text-primary);
            padding: 6px 11px;
            border-radius: 8px;
            font-size: 0.8rem;
            font-weight: 500;
            cursor: pointer;
            transition: all 0.2s ease;
            display: flex;
            align-items: center;
            gap: 5px;
            white-space: nowrap;
        }

        .btn:hover {
            background: var(--card-hover);
            border-color: rgba(255, 255, 255, 0.2);
            transform: translateY(-1px);
        }

        .btn-primary {
            background: #2563eb;
            border-color: #3b82f6;
            color: #ffffff;
        }
        .btn-primary:hover {
            background: #1d4ed8;
        }

        .btn-success {
            background: #059669;
            border-color: #10b981;
            color: #ffffff;
        }
        .btn-success:hover {
            background: #047857;
        }

        /* Responsive Header Breakpoints */
        @media (max-width: 1280px) {
            .btn-text {
                display: none;
            }
            .header-stats .stat-pill:last-child {
                display: none;
            }
        }

        @media (max-width: 1024px) {
            .header-stats {
                display: none;
            }
            .badge-target {
                max-width: 130px;
            }
            .breadcrumbs-container {
                max-width: 180px;
            }
        }

        @media (max-width: 768px) {
            .header-title span:not(.badge-target) {
                display: none;
            }
            .breadcrumbs-container {
                display: none;
            }
        }

        /* Canvas */
        #network-canvas {
            position: fixed;
            top: 60px;
            left: 0;
            right: 0;
            bottom: 0;
            width: 100vw;
            height: calc(100vh - 60px);
            overflow: hidden;
        }

        /* Left HUD Card */
        .hud-card {
            position: fixed;
            top: 72px;
            left: 16px;
            width: 310px;
            max-width: calc(100vw - 32px);
            max-height: calc(100vh - 86px);
            background: var(--surface-color);
            backdrop-filter: blur(14px);
            -webkit-backdrop-filter: blur(14px);
            border: 1px solid var(--surface-border);
            border-radius: 12px;
            padding: 16px;
            z-index: 40;
            box-shadow: 0 10px 25px -5px rgba(0, 0, 0, 0.5);
            display: flex;
            flex-direction: column;
            gap: 12px;
            overflow-y: auto;
            transition: transform 0.28s cubic-bezier(0.16, 1, 0.3, 1), opacity 0.2s ease;
        }

        .hud-card.collapsed {
            transform: translateX(calc(-100% - 24px));
            opacity: 0;
            pointer-events: none;
        }

        .hud-header {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 8px;
        }

        .hud-header h3 {
            font-size: 0.82rem;
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: 0.05em;
            color: var(--text-secondary);
            margin: 0;
        }

        .hud-collapse-btn {
            background: rgba(255, 255, 255, 0.08);
            border: 1px solid var(--surface-border);
            color: var(--text-secondary);
            width: 26px;
            height: 26px;
            border-radius: 6px;
            display: flex;
            align-items: center;
            justify-content: center;
            cursor: pointer;
            font-size: 0.75rem;
            transition: all 0.2s ease;
            flex-shrink: 0;
        }
        .hud-collapse-btn:hover {
            background: rgba(255, 255, 255, 0.16);
            color: var(--text-primary);
        }

        .hud-expand-pill {
            position: fixed;
            top: 72px;
            left: 16px;
            background: var(--surface-color);
            backdrop-filter: blur(14px);
            -webkit-backdrop-filter: blur(14px);
            border: 1px solid var(--surface-border);
            border-radius: 9999px;
            padding: 7px 14px;
            color: var(--text-primary);
            font-size: 0.8rem;
            font-weight: 600;
            cursor: pointer;
            z-index: 39;
            box-shadow: 0 8px 20px rgba(0, 0, 0, 0.4);
            display: none;
            align-items: center;
            gap: 6px;
            transition: all 0.2s ease;
        }
        .hud-expand-pill:hover {
            background: var(--card-hover);
            transform: translateY(-1px);
            border-color: rgba(255, 255, 255, 0.3);
        }
        .hud-expand-pill.visible {
            display: flex;
        }

        .hud-card h3 {
            font-size: 0.85rem;
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: 0.05em;
            color: var(--text-secondary);
        }

        .search-box {
            position: relative;
        }

        .search-box input {
            width: 100%;
            background: rgba(0, 0, 0, 0.2);
            border: 1px solid var(--surface-border);
            border-radius: 8px;
            padding: 8px 12px;
            color: var(--text-primary);
            font-size: 0.85rem;
            outline: none;
            transition: border-color 0.2s;
        }
        body.light-mode .search-box input {
            background: rgba(255, 255, 255, 0.8);
        }
        .search-box input:focus {
            border-color: #3b82f6;
        }

        /* Autocomplete Suggestions */
        .search-suggestions {
            position: absolute;
            top: 100%;
            left: 0;
            right: 0;
            margin-top: 4px;
            background: var(--surface-color);
            backdrop-filter: blur(16px);
            -webkit-backdrop-filter: blur(16px);
            border: 1px solid var(--surface-border);
            border-radius: 8px;
            box-shadow: 0 12px 28px rgba(0, 0, 0, 0.45);
            max-height: 420px;
            overflow-y: auto;
            z-index: 100;
            display: none;
        }

        .search-suggestions.active {
            display: block;
        }

        .suggestion-category-header {
            padding: 6px 10px;
            font-size: 0.68rem;
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: 0.05em;
            background: rgba(59, 130, 246, 0.12);
            color: var(--accent-primary);
            border-top: 1px solid var(--surface-border);
            border-bottom: 1px solid var(--surface-border);
            display: flex;
            align-items: center;
            justify-content: space-between;
        }
        .suggestion-category-header:first-child {
            border-top: none;
        }
        .suggestion-badge {
            display: inline-block;
            font-size: 0.62rem;
            padding: 1px 5px;
            border-radius: 4px;
            background: rgba(255, 255, 255, 0.08);
            color: var(--text-secondary);
            font-weight: 500;
        }

        .suggestion-item {
            padding: 8px 12px;
            cursor: pointer;
            border-bottom: 1px solid var(--surface-border);
            font-size: 0.8rem;
            transition: background 0.15s ease;
        }
        .suggestion-item:last-child {
            border-bottom: none;
        }
        .suggestion-item:hover {
            background: var(--card-hover);
        }
        .suggestion-name {
            font-weight: 600;
            color: var(--text-primary);
            margin-bottom: 2px;
        }
        .suggestion-meta {
            font-size: 0.72rem;
            color: var(--text-secondary);
        }

        .filter-section {
            display: flex;
            flex-direction: column;
            gap: 6px;
        }

        .layer-toggles-grid {
            display: flex;
            flex-direction: column;
            gap: 5px;
        }

        .layer-toggle-item {
            display: flex;
            align-items: center;
            justify-content: space-between;
            padding: 6px 10px;
            background: rgba(255, 255, 255, 0.03);
            border: 1px solid var(--surface-border);
            border-radius: 6px;
            font-size: 0.76rem;
            font-weight: 500;
            color: var(--text-secondary);
            cursor: pointer;
            transition: all 0.15s ease;
            user-select: none;
        }

        .layer-toggle-item:hover {
            background: rgba(255, 255, 255, 0.07);
            border-color: rgba(255, 255, 255, 0.25);
            color: var(--text-primary);
        }

        .layer-toggle-item.active {
            color: var(--text-primary);
        }

        .layer-toggle-item.active.grants {
            background: rgba(6, 182, 212, 0.12);
            border-color: rgba(6, 182, 212, 0.4);
        }

        .layer-toggle-item.active.rel {
            background: rgba(168, 85, 247, 0.12);
            border-color: rgba(168, 85, 247, 0.4);
        }

        .layer-toggle-item.active.pac {
            background: rgba(239, 68, 68, 0.12);
            border-color: rgba(239, 68, 68, 0.4);
        }

        .layer-checkbox {
            width: 15px;
            height: 15px;
            accent-color: #3b82f6;
            cursor: pointer;
        }
        .layer-toggle-item.grants .layer-checkbox { accent-color: #06b6d4; }
        .layer-toggle-item.rel .layer-checkbox { accent-color: #a855f7; }
        .layer-toggle-item.pac .layer-checkbox { accent-color: #ef4444; }

        .filter-label {
            font-size: 0.78rem;
            color: var(--text-secondary);
            display: flex;
            justify-content: space-between;
        }

        .slider-control {
            width: 100%;
            accent-color: #3b82f6;
            cursor: pointer;
        }

        .btn-group {
            display: flex;
            background: rgba(0, 0, 0, 0.2);
            border-radius: 8px;
            padding: 2px;
            border: 1px solid var(--surface-border);
        }

        .btn-segmented {
            flex: 1;
            background: transparent;
            border: none;
            color: var(--text-secondary);
            padding: 5px 8px;
            font-size: 0.75rem;
            font-weight: 500;
            border-radius: 6px;
            cursor: pointer;
            transition: all 0.2s ease;
        }

        .btn-segmented.active {
            background: var(--surface-color);
            color: var(--text-primary);
            box-shadow: 0 1px 3px rgba(0, 0, 0, 0.2);
        }

        .legend-box {
            border-top: 1px solid var(--surface-border);
            padding-top: 10px;
            display: flex;
            flex-direction: column;
            gap: 6px;
        }

        .legend-item {
            display: flex;
            align-items: center;
            gap: 8px;
            font-size: 0.75rem;
            color: var(--text-secondary);
        }

        .legend-dot {
            width: 10px;
            height: 10px;
            border-radius: 50%;
        }

        /* Right Side Detail Drawer */
        .drawer {
            position: fixed;
            top: 60px;
            right: 0;
            bottom: 0;
            width: 440px;
            max-width: 90vw;
            background: var(--surface-color);
            backdrop-filter: blur(16px);
            -webkit-backdrop-filter: blur(16px);
            border-left: 1px solid var(--surface-border);
            z-index: 45;
            transform: translateX(100%);
            transition: transform 0.3s cubic-bezier(0.16, 1, 0.3, 1), visibility 0.3s;
            display: none;
            flex-direction: column;
            box-shadow: -10px 0 25px rgba(0, 0, 0, 0.35);
            visibility: hidden;
            pointer-events: none;
        }

        .drawer.open {
            transform: translateX(0);
            visibility: visible;
            pointer-events: auto;
            display: flex;
        }

        .drawer-header {
            padding: 16px 20px;
            border-bottom: 1px solid var(--surface-border);
            display: flex;
            align-items: flex-start;
            justify-content: space-between;
            gap: 12px;
        }

        .drawer-title-group h2 {
            font-size: 1.1rem;
            font-weight: 700;
            margin-bottom: 4px;
            line-height: 1.3;
        }

        .drawer-subtitle {
            font-size: 0.78rem;
            color: var(--text-secondary);
        }

        .close-btn {
            background: transparent;
            border: none;
            color: var(--text-secondary);
            font-size: 1.4rem;
            cursor: pointer;
            padding: 4px;
            line-height: 1;
        }

        .close-btn:hover {
            color: var(--text-primary);
        }

        .drawer-tabs {
            display: flex;
            border-bottom: 1px solid var(--surface-border);
            background: rgba(15, 23, 42, 0.4);
            padding: 0 16px;
            gap: 6px;
            flex-shrink: 0;
        }

        .drawer-tab-btn {
            background: transparent;
            border: none;
            border-bottom: 2px solid transparent;
            color: var(--text-secondary);
            font-size: 0.8rem;
            font-weight: 600;
            padding: 10px 12px;
            cursor: pointer;
            transition: all 0.2s ease;
            white-space: nowrap;
        }

        .drawer-tab-btn:hover {
            color: var(--text-primary);
        }

        .drawer-tab-btn.active {
            color: var(--accent-target);
            border-bottom-color: var(--accent-target);
        }

        .drawer-tab-panel {
            display: none;
            flex-direction: column;
            gap: 16px;
        }

        .drawer-tab-panel.active {
            display: flex;
        }

        .spending-ratio-bar {
            height: 14px;
            border-radius: 7px;
            overflow: hidden;
            display: flex;
            background: rgba(255, 255, 255, 0.05);
            margin: 10px 0 8px 0;
        }

        .ratio-prog { background: #10b981; }
        .ratio-admin { background: #f59e0b; }
        .ratio-fund { background: #3b82f6; }

        .ratio-legend {
            display: flex;
            justify-content: space-between;
            font-size: 0.74rem;
            color: var(--text-secondary);
        }

        .ratio-legend-item {
            display: flex;
            align-items: center;
            gap: 5px;
        }

        .ratio-dot {
            width: 8px;
            height: 8px;
            border-radius: 50%;
        }

        .interlock-badge {
            display: inline-flex;
            align-items: center;
            gap: 4px;
            background: rgba(245, 158, 11, 0.18);
            color: #f59e0b;
            border: 1px solid rgba(245, 158, 11, 0.4);
            padding: 2px 7px;
            border-radius: 6px;
            font-size: 0.7rem;
            font-weight: 600;
        }

        .role-pill {
            display: inline-block;
            background: rgba(59, 130, 246, 0.15);
            color: #60a5fa;
            border: 1px solid rgba(59, 130, 246, 0.3);
            padding: 1px 6px;
            border-radius: 4px;
            font-size: 0.68rem;
            font-weight: 500;
        }

        .drawer-content {
            padding: 18px 20px;
            overflow-y: auto;
            flex: 1;
            display: flex;
            flex-direction: column;
            gap: 18px;
        }

        .btn-recenter-main {
            background: linear-gradient(135deg, #f59e0b, #d97706);
            color: #ffffff;
            border: none;
            padding: 9px 14px;
            border-radius: 8px;
            font-size: 0.82rem;
            font-weight: 600;
            cursor: pointer;
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 6px;
            width: 100%;
            margin-top: 8px;
            transition: all 0.2s ease;
            box-shadow: 0 4px 12px rgba(245, 158, 11, 0.25);
        }

        .btn-recenter-main:hover {
            background: linear-gradient(135deg, #fbbf24, #f59e0b);
            transform: translateY(-1px);
            box-shadow: 0 6px 16px rgba(245, 158, 11, 0.35);
        }

        .btn-retrieve-main {
            background: linear-gradient(135deg, #10b981, #059669);
            color: #ffffff;
            border: none;
            padding: 9px 14px;
            border-radius: 8px;
            font-size: 0.82rem;
            font-weight: 600;
            cursor: pointer;
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 6px;
            width: 100%;
            margin-top: 6px;
            transition: all 0.2s ease;
            box-shadow: 0 4px 12px rgba(16, 185, 129, 0.25);
        }

        .btn-retrieve-main:hover {
            background: linear-gradient(135deg, #34d399, #10b981);
            transform: translateY(-1px);
            box-shadow: 0 6px 16px rgba(16, 185, 129, 0.35);
        }

        .btn-table-recenter {
            background: rgba(245, 158, 11, 0.15);
            border: 1px solid rgba(245, 158, 11, 0.3);
            color: var(--accent-target);
            padding: 3px 8px;
            border-radius: 6px;
            font-size: 0.72rem;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.2s ease;
            white-space: nowrap;
        }

        .btn-table-recenter:hover {
            background: var(--accent-target);
            color: #000000;
            border-color: var(--accent-target);
        }

        .financial-grid {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 12px;
        }

        .fin-card {
            background: var(--card-hover);
            border: 1px solid var(--surface-border);
            border-radius: 8px;
            padding: 12px;
        }

        .fin-card .fin-label {
            font-size: 0.72rem;
            text-transform: uppercase;
            color: var(--text-secondary);
            margin-bottom: 4px;
        }

        .fin-card .fin-value {
            font-size: 1.05rem;
            font-weight: 700;
            color: var(--text-primary);
        }

        .data-table {
            width: 100%;
            border-collapse: collapse;
            font-size: 0.8rem;
            margin-top: 8px;
        }

        .data-table th, .data-table td {
            padding: 8px 10px;
            text-align: left;
            border-bottom: 1px solid var(--surface-border);
        }

        .data-table th {
            color: var(--text-secondary);
            font-weight: 600;
            text-transform: uppercase;
            font-size: 0.7rem;
        }

        .data-table tr:hover {
            background: var(--card-hover);
        }

        .text-green { color: #10b981; font-weight: 600; }
        .text-blue { color: #3b82f6; font-weight: 600; }

        /* Progress Modal Overlay */
        .progress-overlay {
            position: fixed;
            top: 0;
            left: 0;
            right: 0;
            bottom: 0;
            background: rgba(11, 15, 25, 0.84);
            backdrop-filter: blur(10px);
            -webkit-backdrop-filter: blur(10px);
            z-index: 9999;
            display: flex;
            align-items: center;
            justify-content: center;
            opacity: 0;
            pointer-events: none;
            transition: opacity 0.3s ease;
        }

        .progress-overlay.active {
            opacity: 1;
            pointer-events: auto;
        }

        .progress-card {
            background: var(--surface-color);
            border: 1px solid var(--surface-border);
            border-radius: 20px;
            padding: 34px 38px;
            width: 480px;
            max-width: 90vw;
            box-shadow: 0 30px 60px -12px rgba(0, 0, 0, 0.6), 0 0 40px rgba(245, 158, 11, 0.2);
            text-align: center;
            position: relative;
            overflow: hidden;
        }

        .progress-spinner {
            width: 58px;
            height: 58px;
            border: 4px solid rgba(245, 158, 11, 0.2);
            border-top: 4px solid var(--accent-target);
            border-radius: 50%;
            margin: 0 auto 18px;
            animation: spin 1s linear infinite;
            box-shadow: 0 0 20px rgba(245, 158, 11, 0.3);
        }

        @keyframes spin {
            0% { transform: rotate(0deg); }
            100% { transform: rotate(360deg); }
        }

        .progress-title {
            font-size: 1.2rem;
            font-weight: 700;
            letter-spacing: -0.01em;
            margin-bottom: 6px;
            color: var(--text-primary);
        }

        .progress-org-name {
            color: var(--accent-target);
            font-size: 1.05rem;
            font-weight: 600;
            margin-bottom: 18px;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }

        .progress-bar-container {
            width: 100%;
            height: 8px;
            background: var(--card-hover);
            border-radius: 9999px;
            overflow: hidden;
            margin-bottom: 14px;
            border: 1px solid var(--surface-border);
        }

        .progress-bar-fill {
            height: 100%;
            width: 15%;
            background: linear-gradient(90deg, #f59e0b, #fbbf24, #10b981);
            border-radius: 9999px;
            transition: width 0.35s ease;
        }

        .progress-status {
            font-size: 0.85rem;
            color: var(--text-secondary);
            margin-bottom: 22px;
            min-height: 20px;
        }

        .progress-steps-list {
            display: flex;
            flex-direction: column;
            gap: 8px;
            text-align: left;
            background: var(--card-hover);
            border: 1px solid var(--surface-border);
            border-radius: 10px;
            padding: 14px 18px;
            font-size: 0.8rem;
        }

        .progress-step-item {
            display: flex;
            align-items: center;
            gap: 10px;
            color: var(--text-secondary);
            transition: all 0.25s ease;
        }

        .progress-step-item.pending {
            opacity: 0.45;
        }

        .progress-step-item.active {
            color: var(--accent-target);
            font-weight: 600;
            opacity: 1;
        }

        .progress-step-item.done {
            color: #10b981;
            font-weight: 500;
            opacity: 1;
        }

        .step-icon {
            display: inline-flex;
            align-items: center;
            justify-content: center;
            width: 18px;
            height: 18px;
            border-radius: 50%;
            font-size: 0.7rem;
        }

        /* Toast Notice */
        .toast-notice {
            position: fixed;
            bottom: 24px;
            right: 24px;
            background: var(--surface-color);
            border: 1px solid var(--surface-border);
            backdrop-filter: blur(12px);
            -webkit-backdrop-filter: blur(12px);
            color: var(--text-primary);
            padding: 12px 18px;
            border-radius: 10px;
            box-shadow: 0 10px 25px rgba(0,0,0,0.45);
            z-index: 9998;
            font-size: 0.85rem;
            display: flex;
            align-items: center;
            gap: 10px;
            transform: translateY(80px);
            opacity: 0;
            transition: all 0.3s cubic-bezier(0.16, 1, 0.3, 1);
            max-width: 420px;
            pointer-events: none;
        }
        .toast-notice.show {
            transform: translateY(0);
            opacity: 1;
        }

        /* Custom Scrollbars */
        ::-webkit-scrollbar {
            width: 6px;
            height: 6px;
        }
        ::-webkit-scrollbar-track {
            background: transparent;
        }
        ::-webkit-scrollbar-thumb {
            background: var(--surface-border);
            border-radius: 3px;
        }

        /* Schedule R & Person Profile Enhancements */
        .person-modal-card {
            background: var(--surface-color);
            border: 1px solid var(--surface-border);
            border-radius: 16px;
            padding: 24px 28px;
            width: 640px;
            max-width: 92vw;
            max-height: 85vh;
            display: flex;
            flex-direction: column;
            box-shadow: 0 30px 60px -12px rgba(0, 0, 0, 0.7), 0 0 40px rgba(59, 130, 246, 0.2);
            text-align: left;
            position: relative;
            overflow: hidden;
        }
        .person-modal-header {
            display: flex;
            justify-content: space-between;
            align-items: flex-start;
            padding-bottom: 12px;
            border-bottom: 1px solid var(--surface-border);
            margin-bottom: 14px;
        }
        .person-modal-title {
            font-size: 1.18rem;
            font-weight: 700;
            color: var(--text-primary);
            display: flex;
            align-items: center;
            gap: 8px;
        }
        .person-modal-sub {
            font-size: 0.75rem;
            color: var(--text-secondary);
            margin-top: 3px;
        }
        .person-modal-body {
            overflow-y: auto;
            flex: 1;
            padding-right: 4px;
            display: flex;
            flex-direction: column;
            gap: 12px;
        }
        .person-affil-card {
            background: var(--card-bg);
            border: 1px solid var(--surface-border);
            border-radius: 10px;
            padding: 12px 14px;
            display: flex;
            flex-direction: column;
            gap: 8px;
            transition: border-color 0.2s ease;
        }
        .person-affil-card:hover {
            border-color: rgba(59, 130, 246, 0.5);
        }
        .person-row-interactive {
            cursor: pointer;
            transition: background 0.15s ease;
        }
        .person-row-interactive:hover {
            background: var(--card-hover) !important;
        }
        .btn-profile-peek {
            background: rgba(59, 130, 246, 0.12);
            border: 1px solid rgba(59, 130, 246, 0.35);
            color: #60a5fa;
            border-radius: 6px;
            padding: 2px 7px;
            font-size: 0.72rem;
            cursor: pointer;
            transition: all 0.2s ease;
        }
        .btn-profile-peek:hover {
            background: rgba(59, 130, 246, 0.3);
            transform: scale(1.05);
        }
        #btn-toggle-affiliates.active {
            background: rgba(168, 85, 247, 0.2);
            border-color: rgba(168, 85, 247, 0.5);
            color: #c084fc;
        }
    </style>
</head>
<body>

    <!-- Header -->
    <header>
        <div class="header-title-group">
            <div class="header-title">
                IRS 990 Explorer
                <span class="badge-target" id="target-badge-name">⚓ {{ graph.target_node.name }}</span>
            </div>
            {% if is_server_mode %}
            <div class="server-mode-pill" title="Connected to live local server with real-time dynamic querying">
                Live Server
            </div>
            {% endif %}
            <!-- Breadcrumbs Navigation -->
            <div class="breadcrumbs-container" id="breadcrumbs-container" title="Lineage Traversal History">
                <!-- Dynamically populated via JS -->
            </div>
        </div>

        <div class="header-stats">
            <div class="stat-pill">Nodes: <strong id="stat-nodes-count">{{ graph.nodes|length }}</strong></div>
            <div class="stat-pill">Grant Links: <strong id="stat-grants-count">{{ graph.grant_edges|length }}</strong></div>
            <div class="stat-pill">Funding Volume: <strong id="stat-volume-amt">{{ format_currency(total_funding_amt) }}</strong></div>
            <div class="stat-pill">Schedule R: <strong id="stat-rels-count">{{ graph.relationship_edges|length }}</strong></div>
        </div>

        <div class="header-actions">
            <button class="btn" id="btn-theme" title="Toggle Dark/Light Mode">☀️ / 🌙</button>
            <button class="btn" id="btn-reset-view" title="Reset View">🎯 <span class="btn-text">Center</span></button>
            {% if is_server_mode %}
            <button class="btn btn-success" id="btn-export-snapshot" title="Save offline standalone snapshot file">💾 <span class="btn-text">Save Snapshot</span></button>
            {% endif %}
            <button class="btn" id="btn-export-csv" title="Export CSV Data">📥 <span class="btn-text">CSV</span></button>
            <button class="btn" id="btn-export-json" title="Export Graph JSON">📋 <span class="btn-text">JSON</span></button>
            <button class="btn btn-primary" id="btn-export-png" title="Export PNG Image">📷 <span class="btn-text">Screenshot</span></button>
            <a href="https://github.com/joelontheroad/990-explorer" target="_blank" rel="noopener noreferrer" class="btn" title="View Source Code on GitHub (GNU AGPLv3)" style="text-decoration: none;">⚖️ <span class="btn-text">Source Code (GNU AGPLv3)</span></a>
        </div>
    </header>

    <!-- Canvas -->
    <div id="network-canvas"></div>

    <!-- HUD Controls -->
    <div class="hud-card" id="hud-card">
        <div class="hud-header">
            <h3>Graph Navigation & Controls</h3>
            <button class="hud-collapse-btn" id="hud-collapse-btn" title="Collapse Controls Panel">◀</button>
        </div>
        
        <div class="search-box">
            <input type="text" id="node-search" placeholder="🔍 Search organization, leader, PAC, Super PAC, or EIN..." autocomplete="off">
            <div class="search-suggestions" id="search-suggestions"></div>
        </div>

        <div class="filter-section">
            <div class="filter-label">
                <span>Min Grant Threshold:</span>
                <span id="threshold-val">$0</span>
            </div>
            <input type="range" class="slider-control" id="threshold-slider" min="0" max="10000000" step="25000" value="0">
        </div>

        <div class="filter-section">
            <div class="filter-label"><span>Lineage Direction:</span></div>
            <div class="btn-group" id="direction-toggle">
                <button class="btn-segmented active" data-dir="all">All</button>
                <button class="btn-segmented" data-dir="upstream">Upstream</button>
                <button class="btn-segmented" data-dir="downstream">Downstream</button>
            </div>
        </div>

        <div class="filter-section">
            <div class="filter-label"><span>Layout Algorithm:</span></div>
            <div class="btn-group" id="layout-toggle">
                <button class="btn-segmented active" data-layout="physics">Force-Directed</button>
                <button class="btn-segmented" data-layout="hierarchical">Hierarchical</button>
            </div>
        </div>

        <div class="filter-section">
            <div class="filter-label"><span>Physics Engine:</span></div>
            <button class="btn" id="btn-toggle-physics" style="width: 100%; justify-content: center;">
                ⏸️ Freeze Movement
            </button>
        </div>

        <div class="filter-section">
            <div class="filter-label"><span>Active Graph Layers:</span></div>
            <div class="layer-toggles-grid">
                <label class="layer-toggle-item active grants" id="lbl-layer-grants" for="layer-grants">
                    <span>💸 Grants & Funding</span>
                    <input type="checkbox" id="layer-grants" class="layer-checkbox" checked>
                </label>
                <label class="layer-toggle-item active rel" id="lbl-layer-affiliates" for="layer-affiliates">
                    <span>🏢 Schedule R Affiliates</span>
                    <input type="checkbox" id="layer-affiliates" class="layer-checkbox" checked>
                </label>
                <label class="layer-toggle-item active pac" id="lbl-layer-pacs" for="layer-pacs">
                    <span>🗳️ Political PACs & 527s</span>
                    <input type="checkbox" id="layer-pacs" class="layer-checkbox" checked>
                </label>
            </div>
        </div>

        <div class="legend-box">
            <div class="filter-label" style="margin-bottom: 2px;"><span>Network Roles & Edges:</span></div>
            <div class="legend-item"><div class="legend-dot" style="background: var(--accent-target);"></div> ⚓ Anchor Entity (Center Hub)</div>
            <div class="legend-item"><div class="legend-dot" style="background: var(--accent-upstream);"></div> Inflows / Upstream Funders (Money In &rarr;)</div>
            <div class="legend-item"><div class="legend-dot" style="background: var(--accent-downstream);"></div> Outflows / Downstream Grantees (&rarr; Money Out)</div>
            <div class="legend-item"><div class="legend-dot" style="background: var(--accent-rel);"></div> Schedule R Corporate Relations (dashed purple)</div>
            <div class="legend-item"><div class="legend-dot" style="background: #ef4444; border-radius: 2px;"></div> 🗳️ Political PAC / 527 (crimson hexagon, dashed red)</div>
            <div class="legend-item"><div class="legend-dot" style="background: #8b5cf6; border-radius: 2px; transform: rotate(45deg);"></div> 👤 Federal Candidate (violet diamond)</div>
            <div class="filter-label" style="margin-top: 8px; margin-bottom: 2px;"><span>Entity Classification:</span></div>
            <div class="legend-item"><span style="display:inline-block; width:10px; height:10px; border-radius:50%; background:#94a3b8; margin-right:8px;"></span> ● Circle: Public Charity / Foundation (Form 990)</div>
            <div class="legend-item"><span style="display:inline-block; width:9px; height:9px; transform:rotate(45deg); background:#f59e0b; margin-right:9px; margin-left:1px;"></span> ◆ Diamond: Private Foundation (Form 990-PF)</div>
            <div class="legend-item"><span style="display:inline-block; width:10px; height:10px; background:#ef4444; clip-path: polygon(50% 0%, 100% 25%, 100% 75%, 50% 100%, 0% 75%, 0% 25%); margin-right:8px;"></span> ⬡ Hexagon: Political Committee (FEC / 527)</div>
            <div style="font-size: 0.72rem; color: var(--text-secondary); margin-top: 6px; line-height: 1.4;">
                💡 <strong>Single-click</strong> node to view details • <strong>Double-click</strong> to re-anchor map & retrieve 990
            </div>
        </div>

    </div>

    <!-- HUD Expand Floating Pill -->
    <button class="hud-expand-pill" id="hud-expand-btn" title="Open Controls Panel">⚙️ Controls</button>

    <!-- Right Side Detail Drawer -->
    <div class="drawer" id="side-drawer">
        <div class="drawer-header">
            <div class="drawer-title-group">
                <h2 id="drawer-org-name">Organization Name</h2>
                <div class="drawer-subtitle" id="drawer-org-meta">EIN 00-0000000 • 501(c)(3)</div>
            </div>
            <button class="close-btn" id="btn-close-drawer">&times;</button>
        </div>
        <div class="drawer-tabs" id="drawer-tabs">
            <button class="drawer-tab-btn active" data-tab="tab-overview" onclick="switchDrawerTab('tab-overview')">📋 Overview</button>
            <button class="drawer-tab-btn" data-tab="tab-spending" onclick="switchDrawerTab('tab-spending')">💸 Spending</button>
            <button class="drawer-tab-btn" data-tab="tab-people" onclick="switchDrawerTab('tab-people')">👥 Leadership</button>
            <button class="drawer-tab-btn" data-tab="tab-pacs" onclick="switchDrawerTab('tab-pacs')">🗳️ PACs</button>
        </div>
        <div class="drawer-content" id="drawer-body">
            <div class="drawer-tab-panel active" id="tab-overview"></div>
            <div class="drawer-tab-panel" id="tab-spending"></div>
            <div class="drawer-tab-panel" id="tab-people"></div>
            <div class="drawer-tab-panel" id="tab-pacs"></div>
            <div class="drawer-tab-panel" id="tab-edge"></div>
        </div>
    </div>

    <!-- Progress Modal Overlay -->
    <div class="progress-overlay" id="progress-overlay">
        <div class="progress-card">
            <div class="progress-spinner"></div>
            <div class="progress-title" id="progress-title">Re-anchoring Graph</div>
            <div class="progress-org-name" id="progress-target-name">Anchor Entity</div>
            <div class="progress-bar-container">
                <div class="progress-bar-fill" id="progress-bar-fill"></div>
            </div>
            <div class="progress-status" id="progress-status">In progress — Connecting to server...</div>
            <div class="progress-steps-list">
                <div class="progress-step-item pending" id="step-resolve">
                    <span class="step-icon">○</span> <span id="step-resolve-label">1. Resolving Organization Identity</span>
                </div>
                <div class="progress-step-item pending" id="step-filings">
                    <span class="step-icon">○</span> <span id="step-filings-label">2. Querying Inbound & Outbound Connections</span>
                </div>
                <div class="progress-step-item pending" id="step-lineage">
                    <span class="step-icon">○</span> <span id="step-lineage-label">3. Traversing Network Lineage & Schedule R</span>
                </div>
                <div class="progress-step-item pending" id="step-layout">
                    <span class="step-icon">○</span> <span id="step-layout-label">4. Rebuilding & Optimizing Visual Graph</span>
                </div>
            </div>
        </div>
    </div>

    <!-- Person Leadership Profile Modal -->
    <div class="progress-overlay" id="person-profile-modal">
        <div class="person-modal-card">
            <div class="person-modal-header">
                <div>
                    <div class="person-modal-title" id="pm-person-name">Person Name</div>
                    <div class="person-modal-sub" id="pm-person-sub">IRS 990 Leadership & Governance Profile</div>
                </div>
                <button class="close-btn" id="btn-close-person-modal">&times;</button>
            </div>
            <div class="person-modal-body" id="pm-modal-body">
                <div style="text-align:center; padding: 30px;"><div class="progress-spinner" style="width:32px;height:32px;margin:0 auto 12px auto;"></div>Querying cross-filing leadership records...</div>
            </div>
        </div>
    </div>

    <!-- Toast Notification -->
    <div class="toast-notice" id="toast-notice">
        <span id="toast-text">Notice message</span>
    </div>

    <script>
        {{ vis_js }}

        // State Variables
        let GRAPH_DATA = {{ graph_json }};
        let TARGET_EIN = "{{ graph.target_node.ein }}";
        const IS_SERVER_MODE = {{ 'true' if is_server_mode else 'false' }};

        let network = null;
        let nodesDataset = null;
        let edgesDataset = null;
        let physicsEnabled = true;

        // Navigation History Trail for Breadcrumbs
        let navHistory = [
            { ein: TARGET_EIN, name: GRAPH_DATA.target ? GRAPH_DATA.target.name : "{{ graph.target_node.name }}" }
        ];

        // Color Palette
        const COLORS = {
            target: { background: "#f59e0b", border: "#d97706", highlight: { background: "#fbbf24", border: "#b45309" } },
            upstream: { background: "#06b6d4", border: "#0891b2", highlight: { background: "#22d3ee", border: "#0e7490" } },
            downstream: { background: "#10b981", border: "#059669", highlight: { background: "#34d399", border: "#047857" } },
            related: { background: "#a855f7", border: "#9333ea", highlight: { background: "#c084fc", border: "#7e22ce" } },
            pac: { background: "#ef4444", border: "#b91c1c", highlight: { background: "#f87171", border: "#991b1b" } },
            edgeGrant: "#3b82f6",
            edgeRel: "#a855f7",
            edgePac: "#ef4444"
        };

        function formatUSD(num) {
            return new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 }).format(num || 0);
        }

        function formatCompactUSD(num) {
            if (num >= 1e9) return '$' + (num / 1e9).toFixed(2) + 'B';
            if (num >= 1e6) return '$' + (num / 1e6).toFixed(1) + 'M';
            if (num >= 1e3) return '$' + (num / 1e3).toFixed(0) + 'K';
            return '$' + (num || 0).toLocaleString();
        }

        function escapeHtml(str) {
            if (!str) return '';
            return String(str).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
        }

        function escapeJs(str) {
            if (!str) return '';
            return encodeURIComponent(String(str)).replace(/'/g, "%27");
        }

        function showToast(msg) {
            const toast = document.getElementById("toast-notice");
            const text = document.getElementById("toast-text");
            text.textContent = msg;
            toast.classList.add("show");
            setTimeout(() => toast.classList.remove("show"), 3200);
        }

        // Breadcrumb Rendering
        function updateBreadcrumbsUI() {
            const container = document.getElementById("breadcrumbs-container");
            if (!container) return;
            container.innerHTML = "";

            navHistory.forEach((item, index) => {
                if (index > 0) {
                    const sep = document.createElement("span");
                    sep.className = "breadcrumb-sep";
                    sep.textContent = ">";
                    container.appendChild(sep);
                }
                const pill = document.createElement("span");
                pill.className = "breadcrumb-pill" + (item.ein === TARGET_EIN ? " active" : "");
                pill.textContent = item.name;
                pill.title = `Jump to ${item.name} (${item.ein})`;
                pill.addEventListener("click", () => {
                    if (item.ein !== TARGET_EIN) {
                        navHistory = navHistory.slice(0, index + 1);
                        recenterOnEntity(item.ein, item.name, false);
                    }
                });
                container.appendChild(pill);
            });
        }

        function buildRawNodesAndEdges(graphData) {
            const rawNodes = [];
            const rawEdges = [];

            // Group nodes by direction for structured spatial distribution
            const upstreamNodes = [];
            const downstreamNodes = [];
            const relatedNodes = [];
            const pacNodes = [];
            const candidateNodes = [];
            let anchorNodeEntry = null;

            for (const [ein, node] of Object.entries(graphData.nodes)) {
                if (node.is_target || ein === TARGET_EIN) {
                    anchorNodeEntry = [ein, node];
                } else if (node.direction === "pac" || (node.metadata && node.metadata.is_pac)) {
                    pacNodes.push([ein, node]);
                } else if (node.direction === "candidate" || (node.metadata && node.metadata.is_candidate)) {
                    candidateNodes.push([ein, node]);
                } else if (node.direction === "upstream") {
                    upstreamNodes.push([ein, node]);
                } else if (node.direction === "related") {
                    relatedNodes.push([ein, node]);
                } else {
                    downstreamNodes.push([ein, node]);
                }
            }

            function isPF(n) {
                if (!n) return false;
                if (n.is_private_foundation) return true;
                const ts = (n.tax_status || '').toLowerCase();
                return ts.includes('private foundation') || ts.includes('990-pf') || ts.includes('990pf');
            }

            // 1. Process Anchor Entity (Dead center at origin)
            if (anchorNodeEntry) {
                const [ein, node] = anchorNodeEntry;
                const pf = isPF(node);
                rawNodes.push({
                    id: ein,
                    label: node.name,
                    title: `⚓ ANCHOR ENTITY [${pf ? '🏛️ Private Foundation (990-PF)' : '🏢 Public Charity (990)'}]\n${node.name}\nEIN: ${node.ein}\nRevenue: ${formatUSD(node.total_revenue)}\nAssets: ${formatUSD(node.total_assets)}\n(Double-click any connected node to re-anchor map)`,
                    color: COLORS.target,
                    size: pf ? 48 : 42,
                    x: 0,
                    y: 0,
                    fixed: { x: true, y: true }, // Anchored at physical center
                    font: { color: "#ffffff", size: 15, face: "sans-serif", strokeWidth: 3, strokeColor: "#0b0f19" },
                    shape: pf ? "diamond" : "dot",
                    borderWidth: 4,
                    data: node
                });
            }

            // 2. Process Upstream Inflows and Downstream Outflows
            const uTotal = upstreamNodes.length;
            const dTotal = downstreamNodes.length;

            if (uTotal === 0 && dTotal > 0) {
                // Symmetrical Radial Orbit: Anchor Entity is at dead center (0, 0), all grantees radiate outward
                downstreamNodes.forEach(([ein, node], idx) => {
                    const angle = (idx / dTotal) * 2 * Math.PI - Math.PI / 2;
                    const ring = idx % 2 === 0 ? 340 : 470;
                    const xPos = Math.round(Math.cos(angle) * ring);
                    const yPos = Math.round(Math.sin(angle) * ring);
                    const pf = isPF(node);

                    rawNodes.push({
                        id: ein,
                        label: node.name,
                        title: `OUTFLOW (Downstream Grantee) [${pf ? '🏛️ Private Foundation (990-PF)' : '🏢 Public Charity (990)'}]\n${node.name}\nEIN: ${node.ein}\nRevenue: ${formatUSD(node.total_revenue)}\n(Double-click to make Anchor Entity)`,
                        color: COLORS.downstream,
                        size: pf ? 28 : 24,
                        x: xPos,
                        y: yPos,
                        fixed: false,
                        font: { color: "#ffffff", size: 12, face: "sans-serif" },
                        shape: pf ? "diamond" : "dot",
                        borderWidth: pf ? 3 : 2,
                        data: node
                    });
                });
            } else if (dTotal === 0 && uTotal > 0) {
                // Symmetrical Radial Orbit: Anchor Entity is at dead center (0, 0), all funders converge inward
                upstreamNodes.forEach(([ein, node], idx) => {
                    const angle = (idx / uTotal) * 2 * Math.PI - Math.PI / 2;
                    const ring = idx % 2 === 0 ? 340 : 470;
                    const xPos = Math.round(Math.cos(angle) * ring);
                    const yPos = Math.round(Math.sin(angle) * ring);
                    const pf = isPF(node);

                    rawNodes.push({
                        id: ein,
                        label: node.name,
                        title: `INFLOW (Upstream Funder) [${pf ? '🏛️ Private Foundation (990-PF)' : '🏢 Public Charity (990)'}]\n${node.name}\nEIN: ${node.ein}\nRevenue: ${formatUSD(node.total_revenue)}\n(Double-click to make Anchor Entity)`,
                        color: COLORS.upstream,
                        size: pf ? 30 : 26,
                        x: xPos,
                        y: yPos,
                        fixed: false,
                        font: { color: "#ffffff", size: 12, face: "sans-serif" },
                        shape: pf ? "diamond" : "dot",
                        borderWidth: pf ? 3 : 2,
                        data: node
                    });
                });
            } else {
                // Bilateral Left-to-Right Layout: Funders on Left, Anchor in Middle, Grantees on Right
                upstreamNodes.forEach(([ein, node], idx) => {
                    const col = idx % 2;
                    const row = Math.floor(idx / 2) - Math.floor(uTotal / 4);
                    const xPos = -320 - col * 140;
                    const yPos = row * 85 + (col === 1 ? 40 : 0);
                    const pf = isPF(node);

                    rawNodes.push({
                        id: ein,
                        label: node.name,
                        title: `INFLOW (Upstream Funder) [${pf ? '🏛️ Private Foundation (990-PF)' : '🏢 Public Charity (990)'}]\n${node.name}\nEIN: ${node.ein}\nRevenue: ${formatUSD(node.total_revenue)}\n(Double-click to make Anchor Entity)`,
                        color: COLORS.upstream,
                        size: pf ? 30 : 26,
                        x: xPos,
                        y: yPos,
                        fixed: false,
                        font: { color: "#ffffff", size: 12, face: "sans-serif" },
                        shape: pf ? "diamond" : "dot",
                        borderWidth: pf ? 3 : 2,
                        data: node
                    });
                });

                downstreamNodes.forEach(([ein, node], idx) => {
                    const col = idx % 2;
                    const row = Math.floor(idx / 2) - Math.floor(dTotal / 4);
                    const xPos = 320 + col * 140;
                    const yPos = row * 85 + (col === 1 ? 40 : 0);
                    const pf = isPF(node);

                    rawNodes.push({
                        id: ein,
                        label: node.name,
                        title: `OUTFLOW (Downstream Grantee) [${pf ? '🏛️ Private Foundation (990-PF)' : '🏢 Public Charity (990)'}]\n${node.name}\nEIN: ${node.ein}\nRevenue: ${formatUSD(node.total_revenue)}\n(Double-click to make Anchor Entity)`,
                        color: COLORS.downstream,
                        size: pf ? 28 : 24,
                        x: xPos,
                        y: yPos,
                        fixed: false,
                        font: { color: "#ffffff", size: 12, face: "sans-serif" },
                        shape: pf ? "diamond" : "dot",
                        borderWidth: pf ? 3 : 2,
                        data: node
                    });
                });
            }

            // 3. Process Corporate Relationships (Clustered neatly below Anchor)
            const rTotal = relatedNodes.length;
            relatedNodes.forEach(([ein, node], idx) => {
                const angle = Math.PI / 2 + ((idx - (rTotal - 1) / 2) * (rTotal > 1 ? 0.42 : 0));
                const dist = 180 + (idx % 2) * 35;
                const xPos = Math.round(Math.cos(angle) * dist);
                const yPos = Math.round(Math.sin(angle) * dist);
                const pf = isPF(node);

                rawNodes.push({
                    id: ein,
                    label: node.name,
                    title: `CORPORATE RELATION (Schedule R) [${pf ? '🏛️ Private Foundation (990-PF)' : '🏢 Public Charity (990)'}]\n${node.name}\nEIN: ${node.ein}\n(Shared governance/legal affiliation; double-click to make Anchor Entity)`,
                    color: COLORS.related,
                    size: pf ? 26 : 22,
                    x: xPos,
                    y: yPos,
                    fixed: false,
                    font: { color: "#ffffff", size: 12, face: "sans-serif" },
                    shape: pf ? "diamond" : "dot",
                    borderWidth: pf ? 3 : 2,
                    hidden: (typeof affiliatesVisible !== "undefined") ? !affiliatesVisible : false,
                    data: node
                });
            });

            // 4. Process PAC & Political Committees (Clustered neatly above Anchor)
            const pTotal = pacNodes.length;
            pacNodes.forEach(([ein, node], idx) => {
                const angle = -Math.PI / 2 + ((idx - (pTotal - 1) / 2) * (pTotal > 1 ? 0.45 : 0));
                const dist = 200 + (idx % 2) * 35;
                const xPos = Math.round(Math.cos(angle) * dist);
                const yPos = Math.round(Math.sin(angle) * dist);

                rawNodes.push({
                    id: ein,
                    label: node.name,
                    title: `🗳️ POLITICAL ACTION COMMITTEE [${node.tax_status || 'PAC'}]\n${node.name}\nID: ${node.ein}\n(Click to inspect PAC details and disbursements)`,
                    color: COLORS.pac,
                    size: 28,
                    x: xPos,
                    y: yPos,
                    fixed: false,
                    font: { color: "#ffffff", size: 12, face: "sans-serif" },
                    shape: "hexagon",
                    borderWidth: 3,
                    data: node
                });
            });

            // 5. Process Candidates (Clustered neatly above PACs)
            const cTotal = candidateNodes.length;
            candidateNodes.forEach(([id, node], idx) => {
                const angle = -Math.PI / 2 + ((idx - (cTotal - 1) / 2) * (cTotal > 1 ? 0.35 : 0));
                const dist = 320 + (idx % 2) * 45;
                const xPos = Math.round(Math.cos(angle) * dist);
                const yPos = Math.round(Math.sin(angle) * dist);

                rawNodes.push({
                    id: id,
                    label: node.name,
                    title: `👤 CANDIDATE [${node.tax_status || 'Federal Candidate'}]\n${node.name}\nID: ${node.ein}\n(Click to view candidate support & opposition)`,
                    color: { background: "#8b5cf6", border: "#7c3aed" },
                    size: 24,
                    x: xPos,
                    y: yPos,
                    fixed: false,
                    font: { color: "#ffffff", size: 12, face: "sans-serif" },
                    shape: "diamond",
                    borderWidth: 2,
                    data: node
                });
            });


            // Process Grant Edges
            for (const [key, edge] of Object.entries(graphData.grant_edges)) {
                const width = Math.min(10, Math.max(1.5, Math.log10(edge.total_amount / 10000 + 1) * 2.5));
                rawEdges.push({
                    id: key,
                    from: edge.grantor_ein,
                    to: edge.recipient_ein,
                    arrows: "to",
                    label: formatCompactUSD(edge.total_amount),
                    font: { size: 10, color: "#9ca3af", align: "middle", strokeWidth: 0 },
                    color: { color: COLORS.edgeGrant, opacity: 0.8 },
                    width: width,
                    smooth: { type: "curvedCW", roundness: 0.15 },
                    title: `Grant: ${formatUSD(edge.total_amount)}\nYears: ${edge.years.join(', ')}`,
                    edgeType: "grant",
                    amount: edge.total_amount,
                    data: edge
                });
            }

            // Process Relationship Edges
            for (const [key, rel] of Object.entries(graphData.relationship_edges)) {
                const isPacRel = (rel.source_schedule === "PAC Linkage");
                const isCandidateExpenditure = (rel.source_schedule === "Candidate Independent Expenditure");
                const isSupport = (rel.relationship_type && rel.relationship_type.toLowerCase().includes("support"));
                const edgeColor = isCandidateExpenditure ? (isSupport ? "#10b981" : "#ef4444") : (isPacRel ? COLORS.edgePac : COLORS.edgeRel);
                rawEdges.push({
                    id: "rel:" + key,
                    from: rel.entity_ein,
                    to: rel.related_ein,
                    arrows: isCandidateExpenditure ? "to" : "",
                    label: rel.relationship_type,
                    font: { size: 9, color: edgeColor, align: "middle", strokeWidth: 0 },
                    color: { color: edgeColor, opacity: 0.95 },
                    width: isCandidateExpenditure ? 2.5 : (isPacRel ? 2.8 : 2.5),
                    dashes: (isPacRel || isCandidateExpenditure) ? [4, 4] : [6, 4],
                    smooth: { type: "curvedCCW", roundness: 0.2 },
                    title: isCandidateExpenditure ? `Independent Expenditure: ${rel.relationship_type}\n${rel.primary_activity || ''}` : (isPacRel ? `Political Action Committee Bridge: ${rel.relationship_type}\n${rel.primary_activity || ''}` : `Schedule R Corporate Affiliation: ${rel.relationship_type}\nNo grant arrows because this reflects corporate governance, not monetary transfers.`),
                    edgeType: isCandidateExpenditure ? "pac_expenditure" : (isPacRel ? "pac_linkage" : "relationship"),
                    length: isCandidateExpenditure ? 160 : (isPacRel ? 150 : 130),
                    physics: true,
                    amount: 0,
                    data: rel
                });
            }

            return { rawNodes, rawEdges };
        }

        function initGraph() {
            const { rawNodes, rawEdges } = buildRawNodesAndEdges(GRAPH_DATA);

            nodesDataset = new vis.DataSet(rawNodes);
            edgesDataset = new vis.DataSet(rawEdges);

            const container = document.getElementById("network-canvas");
            const data = { nodes: nodesDataset, edges: edgesDataset };
            const options = {
                physics: {
                    solver: "barnesHut",
                    barnesHut: {
                        gravitationalConstant: -18000,
                        centralGravity: 0.2,
                        springLength: 220,
                        springConstant: 0.035,
                        damping: 0.09
                    },
                    stabilization: {
                        enabled: true,
                        iterations: 140,
                        updateInterval: 25
                    }
                },
                interaction: {
                    hover: true,
                    tooltipDelay: 150,
                    zoomView: true
                },
                layout: {
                    improvedLayout: true
                }
            };

            network = new vis.Network(container, data, options);
            network.fit({ animation: { duration: 600, easingFunction: "easeInOutQuad" } });

            // Robust Interaction Handlers:
            // Single-click: Select node & open drawer (immediate/debounced, NO camera panning that breaks double-click)
            // Double-click: Re-anchor map on node & make it the Anchor Entity
            let lastClickedNodeId = null;
            let lastClickTime = 0;
            let singleClickTimer = null;

            function triggerNodeDoubleClick(nodeId) {
                if (!nodeId) return;
                if (singleClickTimer) {
                    clearTimeout(singleClickTimer);
                    singleClickTimer = null;
                }
                lastClickedNodeId = null;
                lastClickTime = 0;

                const nodeObj = GRAPH_DATA.nodes[nodeId];
                const name = nodeObj ? nodeObj.name : `Org ${nodeId}`;

                if (nodeId === TARGET_EIN) {
                    showToast(`⚓ ${name} is already the Anchor Entity.`);
                    return;
                }

                recenterOnEntity(nodeId, name, true, true);
            }

            function triggerNodeSingleClick(nodeId) {
                const nodeObj = GRAPH_DATA.nodes[nodeId];
                if (nodeObj) {
                    if (nodeObj.direction === "candidate" || (nodeObj.metadata && (nodeObj.metadata.is_candidate || nodeObj.metadata.target_type === "candidate"))) {
                        openCandidateDrawer(nodeObj);
                    } else if (nodeObj.direction === "pac" || (nodeObj.metadata && nodeObj.metadata.is_pac)) {
                        if (nodeObj.metadata && nodeObj.metadata.target_type === "fec_pac") {
                            openFECDrawer(nodeId);
                        } else {
                            open527Drawer(nodeId);
                        }
                    } else {
                        openNodeDrawer(nodeObj);
                    }
                }
                network.selectNodes([nodeId]);
            }

            // Vis.js Network Click Event
            network.on("click", function (params) {
                if (params.nodes && params.nodes.length > 0) {
                    const nodeId = params.nodes[0];
                    const now = Date.now();

                    // Detect rapid successive clicks on the same node (Double-click)
                    if (lastClickedNodeId === nodeId && (now - lastClickTime) < 450) {
                        triggerNodeDoubleClick(nodeId);
                        return;
                    }

                    lastClickedNodeId = nodeId;
                    lastClickTime = now;

                    if (singleClickTimer) {
                        clearTimeout(singleClickTimer);
                    }
                    singleClickTimer = setTimeout(() => {
                        singleClickTimer = null;
                        triggerNodeSingleClick(nodeId);
                    }, 280);

                } else if (params.edges && params.edges.length > 0) {
                    if (singleClickTimer) {
                        clearTimeout(singleClickTimer);
                        singleClickTimer = null;
                    }
                    lastClickedNodeId = null;
                    lastClickTime = 0;
                    const edgeId = params.edges[0];
                    const edgeObj = edgesDataset.get(edgeId);
                    if (edgeObj) {
                        openEdgeDrawer(edgeObj);
                    }
                } else {
                    lastClickedNodeId = null;
                    lastClickTime = 0;
                }
            });

            // Vis.js Network Double-Click Event (Built-in event handler backup)
            network.on("doubleClick", function (params) {
                let nodeId = (params.nodes && params.nodes.length > 0) ? params.nodes[0] : null;
                if (!nodeId && params.pointer && params.pointer.DOM) {
                    nodeId = network.getNodeAt(params.pointer.DOM);
                }
                if (nodeId) {
                    triggerNodeDoubleClick(nodeId);
                }
            });

            // Native DOM dblclick listener on network canvas container (Browser event backup)
            container.addEventListener("dblclick", function (e) {
                const rect = container.getBoundingClientRect();
                const pos = { x: e.clientX - rect.left, y: e.clientY - rect.top };
                const nodeId = network.getNodeAt(pos);
                if (nodeId) {
                    triggerNodeDoubleClick(nodeId);
                }
            });

            updateBreadcrumbsUI();
        }

        // Offline Re-centering Function: re-roots the existing graph around the selected entity
        function recenterOfflineGraph(targetEin) {
            TARGET_EIN = targetEin;
            const targetNode = GRAPH_DATA.nodes[targetEin];
            if (!targetNode) return;

            // Reclassify all nodes relative to targetEin
            for (const [ein, node] of Object.entries(GRAPH_DATA.nodes)) {
                if (ein === targetEin) {
                    node.is_target = true;
                    node.direction = "target";
                    node.depth = 0;
                } else {
                    node.is_target = false;
                    let isInbound = false;
                    let isOutbound = false;
                    for (const edge of Object.values(GRAPH_DATA.grant_edges)) {
                        if (edge.recipient_ein === targetEin && edge.grantor_ein === ein) isInbound = true;
                        if (edge.grantor_ein === targetEin && edge.recipient_ein === ein) isOutbound = true;
                    }
                    if (isInbound && !isOutbound) {
                        node.direction = "upstream";
                    } else if (isOutbound) {
                        node.direction = "downstream";
                    } else {
                        let isRel = false;
                        for (const rel of Object.values(GRAPH_DATA.relationship_edges)) {
                            if ((rel.entity_ein === targetEin && rel.related_ein === ein) ||
                                (rel.related_ein === targetEin && rel.entity_ein === ein)) {
                                isRel = true;
                                break;
                            }
                        }
                        node.direction = isRel ? "related" : "downstream";
                    }
                }
            }

            // Update Header HUD Stats
            document.getElementById("target-badge-name").textContent = "⚓ " + targetNode.name;

            // Sync browser URL bar query parameter
            try {
                const newUrl = new URL(window.location.href);
                newUrl.searchParams.set("ein", targetEin);
                window.history.pushState({ ein: targetEin }, "", newUrl.toString());
            } catch (e) {}

            // Rebuild datasets
            const { rawNodes, rawEdges } = buildRawNodesAndEdges(GRAPH_DATA);
            nodesDataset.clear();
            nodesDataset.add(rawNodes);
            edgesDataset.clear();
            edgesDataset.add(rawEdges);

            if (network) {
                network.setData({ nodes: nodesDataset, edges: edgesDataset });
                network.selectNodes([targetEin]);
                network.fit({
                    animation: { duration: 600, easingFunction: "easeInOutQuad" }
                });
            }
            openNodeDrawer(targetNode);

        }

        // Dynamic Entity Recentering Function
        async function recenterOnEntity(ein, orgName, pushHistory = true, retrieve = false) {
            if (!ein) return;
            if (orgName && orgName.includes('%')) {
                try { orgName = decodeURIComponent(orgName); } catch (e) {}
            }

            if (!IS_SERVER_MODE) {
                // Standalone offline mode: re-center map on clicked entity
                if (GRAPH_DATA.nodes && GRAPH_DATA.nodes[ein]) {
                    recenterOfflineGraph(ein);
                    if (pushHistory) {
                        navHistory.push({ ein: ein, name: orgName || GRAPH_DATA.nodes[ein]?.name });
                        if (navHistory.length > 8) navHistory.shift();
                    }
                    updateBreadcrumbsUI();
                    if (retrieve) {
                        showToast(`Re-centered on ${orgName}. (Run with --serve for live IRS 990 retrieval)`);
                    } else {
                        showToast(`Re-centered on ${orgName}`);
                    }
                } else {
                    showToast(`Offline mode: Start with 'python main.py --ein "${ein}" --serve' to fetch full network.`);
                }
                return;
            }

            // Server mode: dynamic fetch with animated progress modal
            const overlay = document.getElementById("progress-overlay");
            const modalTitle = document.getElementById("progress-title");
            const targetNameEl = document.getElementById("progress-target-name");
            const barFill = document.getElementById("progress-bar-fill");
            const statusText = document.getElementById("progress-status");

            if (modalTitle) {
                modalTitle.textContent = retrieve ? "Retrieving Latest IRS 990 Filing" : "Recentering Graph View";
            }
            if (targetNameEl) {
                targetNameEl.textContent = orgName || `EIN ${ein}`;
            }

            // Setup step labels depending on whether we are fetching live XML or querying local DB
            const stepResolveLabel = document.getElementById("step-resolve-label");
            const stepFilingsLabel = document.getElementById("step-filings-label");
            const stepLineageLabel = document.getElementById("step-lineage-label");
            const stepLayoutLabel = document.getElementById("step-layout-label");

            if (retrieve) {
                if (stepResolveLabel) stepResolveLabel.textContent = "1. Resolving Organization & Index Records";
                if (stepFilingsLabel) stepFilingsLabel.textContent = "2. Fetching & Parsing Latest Form 990 XML";
                if (stepLineageLabel) stepLineageLabel.textContent = "3. Ingesting Grants & Relationships into DB";
                if (stepLayoutLabel) stepLayoutLabel.textContent = "4. Traversing Network Lineage & Rebuilding Graph";
                barFill.style.background = "linear-gradient(90deg, #10b981, #059669, #3b82f6)";
            } else {
                if (stepResolveLabel) stepResolveLabel.textContent = "1. Resolving Organization Identity";
                if (stepFilingsLabel) stepFilingsLabel.textContent = "2. Querying Inbound & Outbound Connections";
                if (stepLineageLabel) stepLineageLabel.textContent = "3. Traversing Network Lineage & Schedule R";
                if (stepLayoutLabel) stepLayoutLabel.textContent = "4. Rebuilding & Optimizing Visual Graph";
                barFill.style.background = "linear-gradient(90deg, #f59e0b, #fbbf24, #10b981)";
            }

            overlay.classList.add("active");

            const setStep = (stepIdx, pct, statusMsg) => {
                barFill.style.width = pct + "%";
                statusText.textContent = statusMsg;
                const steps = ["step-resolve", "step-filings", "step-lineage", "step-layout"];
                steps.forEach((sId, idx) => {
                    const el = document.getElementById(sId);
                    if (!el) return;
                    el.className = "progress-step-item " + (idx < stepIdx ? "done" : (idx === stepIdx ? "active" : "pending"));
                    const icon = el.querySelector(".step-icon");
                    if (icon) icon.textContent = idx < stepIdx ? "✓" : (idx === stepIdx ? "⏳" : "○");
                });
            };

            setStep(0, 20, retrieve ? "In progress — Locating latest electronic filing index..." : "In progress — Resolving organization identity...");

            try {
                let timer1, timer2;
                if (retrieve) {
                    timer1 = setTimeout(() => setStep(1, 48, "In progress — Downloading & parsing Form 990 Schedule I grants..."), 450);
                    timer2 = setTimeout(() => setStep(2, 75, "In progress — Ingesting recipients and corporate relationships..."), 1300);
                } else {
                    timer1 = setTimeout(() => setStep(1, 50, "In progress — Querying funding connections & Schedule R..."), 200);
                    timer2 = setTimeout(() => setStep(2, 75, "In progress — Traversing network lineage..."), 400);
                }

                let currentDirection = document.querySelector("#direction-toggle .btn-segmented.active")?.dataset?.dir || "both";
                if (currentDirection === "all") currentDirection = "both";
                const currentMinGrant = document.getElementById("threshold-slider")?.value || 10000;

                const url = `/api/explore?ein=${encodeURIComponent(ein)}&direction=${currentDirection}&min_grant=${currentMinGrant}&depth=1&top_n=30${retrieve ? '&retrieve=1' : ''}`;
                const res = await fetch(url);
                clearTimeout(timer1);
                clearTimeout(timer2);

                if (!res.ok) {
                    throw new Error(`Server returned status ${res.status}`);
                }

                const data = await res.json();
                if (data.error) {
                    throw new Error(data.error);
                }

                setStep(3, 96, "In progress — Reconstructing network graph and optimizing layout...");

                // Update local state
                GRAPH_DATA = data;
                TARGET_EIN = data.target.ein;

                if (pushHistory) {
                    navHistory.push({ ein: TARGET_EIN, name: data.target.name });
                    if (navHistory.length > 8) navHistory.shift();
                }
                updateBreadcrumbsUI();

                // Sync browser address bar URL with active Anchor Entity
                try {
                    const newUrl = new URL(window.location.href);
                    newUrl.searchParams.set("ein", TARGET_EIN);
                    window.history.pushState({ ein: TARGET_EIN }, "", newUrl.toString());
                } catch (e) {}


                // Update Header HUD Stats
                document.getElementById("target-badge-name").textContent = "⚓ " + data.target.name;
                document.getElementById("stat-nodes-count").textContent = data.stats.total_nodes;
                document.getElementById("stat-grants-count").textContent = data.stats.total_grants;
                document.getElementById("stat-volume-amt").textContent = formatCompactUSD(data.stats.total_funding_amt);
                document.getElementById("stat-rels-count").textContent = data.stats.total_relationships;

                // Rebuild datasets
                const { rawNodes, rawEdges } = buildRawNodesAndEdges(data);
                nodesDataset.clear();
                nodesDataset.add(rawNodes);
                edgesDataset.clear();
                edgesDataset.add(rawEdges);

                if (network) {
                    network.setData({ nodes: nodesDataset, edges: edgesDataset });
                }
                applyFilterVisibility();

                setStep(3, 100, "Complete!");

                setTimeout(() => {
                    overlay.classList.remove("active");
                    if (network) {
                        network.selectNodes([TARGET_EIN]);
                        network.fit({
                            animation: { duration: 600, easingFunction: "easeInOutQuad" }
                        });
                    }
                    openNodeDrawer(data.target);

                    if (data.retrieval) {
                        const r = data.retrieval;
                        if (r.status === "ingested") {
                            showToast(`✓ Retrieved latest 990 (${r.tax_period || 'Latest'}): Added ${r.grants_ingested || 0} grants. ⚓ Re-anchored on ${data.target.name}.`);
                        } else if (r.status === "already_ingested") {
                            showToast(`✓ Latest 990 cached. ⚓ Graph re-anchored on ${data.target.name}.`);
                        } else if (r.status === "no_xml_found") {
                            showToast(`Notice: No electronic 990 XML found on IRS data lake. ⚓ Re-anchored on ${data.target.name}.`);
                        } else {
                            showToast(`⚓ Graph re-anchored on ${data.target.name}`);
                        }
                    } else {
                        showToast(`⚓ Graph re-anchored on ${data.target.name}`);
                    }
                }, 300);

            } catch (err) {
                console.error("Recenter failed:", err);
                statusText.textContent = "Error: " + err.message;
                barFill.style.width = "100%";
                barFill.style.background = "#ef4444";
                setTimeout(() => {
                    overlay.classList.remove("active");
                    showToast("Failed: " + err.message);
                }, 1800);
            }
        }

        function openNodeDrawer(node) {
            const drawer = document.getElementById("side-drawer");
            const isAnchor = Boolean(node.ein === TARGET_EIN || node.is_target);
            document.getElementById("drawer-org-name").textContent = (isAnchor ? "⚓ " : "") + node.name;
            document.getElementById("drawer-org-meta").textContent = `${isAnchor ? "Anchor Entity • " : ""}EIN ${node.ein} • ${node.tax_status}`;

            // Inbound & Outbound Grants
            const inbound = [];
            const outbound = [];
            for (const edge of Object.values(GRAPH_DATA.grant_edges)) {
                if (edge.recipient_ein === node.ein) inbound.push(edge);
                if (edge.grantor_ein === node.ein) outbound.push(edge);
            }

            // Corporate Relationships
            const rels = [];
            for (const rel of Object.values(GRAPH_DATA.relationship_edges)) {
                if (rel.entity_ein === node.ein || rel.related_ein === node.ein) {
                    rels.push(rel);
                }
            }

            let html = `
                <div style="display: flex; flex-direction: column; gap: 8px; margin-bottom: 14px;">
                    ${!isAnchor ? `
                        <button class="btn-recenter-main" onclick="recenterOnEntity('${node.ein}', '${escapeJs(node.name)}', true, true)">
                            ⚓ Make Anchor Entity & Re-center Map
                        </button>
                    ` : `
                        <button class="btn-retrieve-main" onclick="recenterOnEntity('${node.ein}', '${escapeJs(node.name)}', true, true)">
                            📥 Refresh Latest 990 (Live IRS Fetch)
                        </button>
                    `}
                    <div style="font-size: 0.72rem; color: var(--text-secondary); text-align: center; margin-top: -2px;">
                        💡 Single-click node to view • Double-click node to make Anchor Entity
                    </div>
                </div>
            `;

            const isPF = Boolean(
                node.is_private_foundation ||
                (node.tax_status && node.tax_status.toLowerCase().includes("private foundation")) ||
                (node.tax_status && node.tax_status.toLowerCase().includes("990-pf"))
            );
            const foundationBadge = isPF ?
                `<div style="display: inline-flex; align-items: center; gap: 6px; background: rgba(245, 158, 11, 0.15); color: #f59e0b; border: 1px solid rgba(245, 158, 11, 0.45); padding: 5px 12px; border-radius: 8px; font-weight: 600; font-size: 0.8rem; margin-bottom: 12px; width: 100%; justify-content: center;">🏛️ 501(c)(3) Private Foundation (Form 990-PF)</div>` :
                `<div style="display: inline-flex; align-items: center; gap: 6px; background: rgba(16, 185, 129, 0.15); color: #10b981; border: 1px solid rgba(16, 185, 129, 0.45); padding: 5px 12px; border-radius: 8px; font-weight: 600; font-size: 0.8rem; margin-bottom: 12px; width: 100%; justify-content: center;">🏢 501(c)(3) Public Charity / Foundation (Form 990)</div>`;

            html += `
                ${foundationBadge}
                <div class="financial-grid">
                    <div class="fin-card">

                        <div class="fin-label">Total Revenue</div>
                        <div class="fin-value">${formatUSD(node.total_revenue)}</div>
                    </div>
                    <div class="fin-card">
                        <div class="fin-label">Total Assets</div>
                        <div class="fin-value">${formatUSD(node.total_assets)}</div>
                    </div>
                </div>

                <div style="font-size: 0.8rem; color: var(--text-secondary); line-height: 1.6;">
                    <div><strong>Location:</strong> ${node.city || 'Unknown'}, ${node.state || ''} ${node.zipcode || ''}</div>
                    ${node.address ? `<div><strong>Address:</strong> ${escapeHtml(node.address)}</div>` : ''}
                    ${node.ntee_code ? `<div><strong>NTEE Code:</strong> ${escapeHtml(node.ntee_code)}</div>` : ''}
                    <div><strong>Lineage Role:</strong> ${(node.direction || 'TARGET').toUpperCase()} (Depth: ${node.depth})</div>
                    <div style="margin-top: 8px;">
                        <a href="https://projects.propublica.org/nonprofits/organizations/${node.ein.replace('-', '')}" target="_blank" style="color: #3b82f6; text-decoration: none;">
                            🔗 View on ProPublica Nonprofit Explorer &rarr;
                        </a>
                    </div>
                </div>
            `;

            // Schedule R Corporate Relationships with prominent recenter actions
            if (rels.length > 0) {
                html += `<h3 style="font-size: 0.85rem; margin-top: 10px; color: var(--accent-rel);">Schedule R Corporate Tree (${rels.length})</h3>`;
                html += `<table class="data-table"><thead><tr><th>Related Org</th><th>Relationship</th><th>Activity</th><th>Action</th></tr></thead><tbody>`;
                for (const r of rels) {
                    const isEntity = r.entity_ein === node.ein;
                    const otherName = isEntity ? r.related_name : r.entity_name;
                    const otherEin = isEntity ? r.related_ein : r.entity_ein;
                    html += `
                        <tr style="cursor: pointer;" onclick="recenterOnEntity('${otherEin}', '${escapeJs(otherName)}')" title="Recenter graph on ${escapeHtml(otherName)}">
                            <td><strong>${escapeHtml(otherName)}</strong><br><span style="font-size:0.7rem; color:var(--text-secondary);">${otherEin}</span></td>
                            <td style="color: var(--accent-rel);">${escapeHtml(r.relationship_type)}</td>
                            <td>${escapeHtml(r.primary_activity || 'N/A')}</td>
                            <td>
                                <button class="btn-table-recenter" onclick="event.stopPropagation(); recenterOnEntity('${otherEin}', '${escapeJs(otherName)}')" title="Recenter graph around ${escapeHtml(otherName)}">
                                    🎯 Recenter
                                </button>
                            </td>
                        </tr>
                    `;
                }
                html += `</tbody></table>`;
            }

            // Inbound Funding Sources
            html += `<h3 style="font-size: 0.85rem; margin-top: 10px;">Inbound Funding Sources (${inbound.length})</h3>`;
            if (inbound.length > 0) {
                html += `
                    <table class="data-table">
                        <thead>
                            <tr><th>Grantor (Click to Recenter)</th><th>Amount</th><th>Years</th></tr>
                        </thead>
                        <tbody>
                `;
                for (const g of inbound) {
                    html += `
                        <tr style="cursor: pointer;" onclick="recenterOnEntity('${g.grantor_ein}', '${escapeJs(g.grantor_name)}')" title="Recenter graph on ${escapeHtml(g.grantor_name)}">
                            <td>
                                <div style="display:flex; justify-content:space-between; align-items:flex-start; gap: 6px;">
                                    <div>
                                        <strong>${escapeHtml(g.grantor_name)}</strong><br>
                                        <span style="font-size:0.7rem; color:var(--text-secondary);">${escapeHtml(g.purposes.join('; ') || 'General Support')}</span>
                                    </div>
                                    <button class="btn-table-recenter" onclick="event.stopPropagation(); recenterOnEntity('${g.grantor_ein}', '${escapeJs(g.grantor_name)}')" title="Recenter on ${escapeHtml(g.grantor_name)}">🎯</button>
                                </div>
                            </td>
                            <td class="text-green">${formatUSD(g.total_amount)}</td>
                            <td>${g.years.join(', ')}</td>
                        </tr>
                    `;
                }
                html += `</tbody></table>`;
            } else {
                html += `<div style="font-size: 0.8rem; color: var(--text-secondary);">No inbound grants recorded in this query.</div>`;
            }

            // Outbound Grants Awarded
            html += `<h3 style="font-size: 0.85rem; margin-top: 10px;">Outbound Grants Awarded (${outbound.length})</h3>`;
            if (outbound.length > 0) {
                html += `
                    <table class="data-table">
                        <thead>
                            <tr><th>Recipient (Click to Recenter)</th><th>Amount</th><th>Years</th></tr>
                        </thead>
                        <tbody>
                `;
                for (const g of outbound) {
                    html += `
                        <tr style="cursor: pointer;" onclick="recenterOnEntity('${g.recipient_ein}', '${escapeJs(g.recipient_name)}')" title="Recenter graph on ${escapeHtml(g.recipient_name)}">
                            <td>
                                <div style="display:flex; justify-content:space-between; align-items:flex-start; gap: 6px;">
                                    <div>
                                        <strong>${escapeHtml(g.recipient_name)}</strong><br>
                                        <span style="font-size:0.7rem; color:var(--text-secondary);">${escapeHtml(g.purposes.join('; ') || 'Programmatic Grant')}</span>
                                    </div>
                                    <button class="btn-table-recenter" onclick="event.stopPropagation(); recenterOnEntity('${g.recipient_ein}', '${escapeJs(g.recipient_name)}')" title="Recenter on ${escapeHtml(g.recipient_name)}">🎯</button>
                                </div>
                            </td>
                            <td class="text-blue">${formatUSD(g.total_amount)}</td>
                            <td>${g.years.join(', ')}</td>
                        </tr>
                    `;
                }
                html += `</tbody></table>`;
            } else {
                html += `<div style="font-size: 0.8rem; color: var(--text-secondary);">No outbound grants recorded in this query.</div>`;
            }

            const overviewPanel = document.getElementById("tab-overview");
            if (overviewPanel) overviewPanel.innerHTML = html;

            const drawerTabs = document.getElementById("drawer-tabs");
            if (drawerTabs) drawerTabs.style.display = "flex";

            const edgePanel = document.getElementById("tab-edge");
            if (edgePanel) edgePanel.style.display = "none";

            currentActiveNode = node;
            renderSpendingTab(node);
            renderPeopleTab(node);
            switchDrawerTab(currentDrawerTab || "tab-overview");

            drawer.classList.add("open");
        }

        let currentDrawerTab = "tab-overview";
        let currentActiveNode = null;

        function switchDrawerTab(tabId) {
            currentDrawerTab = tabId;
            document.querySelectorAll(".drawer-tab-btn").forEach(btn => {
                btn.classList.toggle("active", btn.getAttribute("data-tab") === tabId);
            });
            document.querySelectorAll(".drawer-tab-panel").forEach(panel => {
                if (panel.id !== "tab-edge") {
                    panel.classList.toggle("active", panel.id === tabId);
                }
            });
            if (currentActiveNode) {
                if (tabId === "tab-spending") renderSpendingTab(currentActiveNode);
                if (tabId === "tab-people") renderPeopleTab(currentActiveNode);
                if (tabId === "tab-pacs") renderPacsTab(currentActiveNode);
            }
        }

        function renderSpendingTab(node) {
            const panel = document.getElementById("tab-spending");
            if (!panel || !node) return;

            if (!GRAPH_DATA.spendingLoaded) GRAPH_DATA.spendingLoaded = {};
            if (!GRAPH_DATA._spendingFetching) GRAPH_DATA._spendingFetching = {};

            const isLoaded = Boolean(GRAPH_DATA.spendingLoaded[node.ein]);
            const cached = (GRAPH_DATA.expenses && GRAPH_DATA.expenses[node.ein]) ? GRAPH_DATA.expenses[node.ein][0] : null;
            const contractors = (GRAPH_DATA.contractors && GRAPH_DATA.contractors[node.ein]) ? GRAPH_DATA.contractors[node.ein] : [];

            if (!isLoaded && IS_SERVER_MODE) {
                if (GRAPH_DATA._spendingFetching[node.ein]) return;
                GRAPH_DATA._spendingFetching[node.ein] = true;
                panel.innerHTML = `<div style="text-align:center; padding: 24px 16px; color: var(--text-secondary);"><div class="progress-spinner" style="width:28px;height:28px;margin:0 auto 12px auto;"></div>Loading Part IX functional expenses...</div>`;

                fetch(`/api/organization/${encodeURIComponent(node.ein)}/spending`)
                    .then(r => {
                        if (!r.ok) throw new Error(`HTTP ${r.status}`);
                        return r.json();
                    })
                    .then(data => {
                        delete GRAPH_DATA._spendingFetching[node.ein];
                        if (!GRAPH_DATA.expenses) GRAPH_DATA.expenses = {};
                        if (!GRAPH_DATA.contractors) GRAPH_DATA.contractors = {};
                        GRAPH_DATA.expenses[node.ein] = data.expenses || [];
                        GRAPH_DATA.contractors[node.ein] = data.contractors || [];
                        GRAPH_DATA.spendingLoaded[node.ein] = true;
                        if (currentActiveNode && currentActiveNode.ein === node.ein) {
                            renderSpendingTab(node);
                        }
                    })
                    .catch(err => {
                        delete GRAPH_DATA._spendingFetching[node.ein];
                        GRAPH_DATA.spendingLoaded[node.ein] = true;
                        if (currentActiveNode && currentActiveNode.ein === node.ein) {
                            panel.innerHTML = `<div style="color: var(--text-secondary); font-size: 0.82rem; padding: 16px; text-align: center;">Could not load expense data: ${escapeHtml(err.message)}</div>`;
                        }
                    });
                return;
            }

            if (!cached) {
                panel.innerHTML = `
                    <div style="background: var(--card-bg); border: 1px solid var(--surface-border); border-radius: 8px; padding: 16px; text-align: center;">
                        <div style="font-size: 1.5rem; margin-bottom: 8px;">💸</div>
                        <div style="font-weight: 600; font-size: 0.9rem; margin-bottom: 4px;">No Functional Expense Breakdown Found</div>
                        <div style="font-size: 0.76rem; color: var(--text-secondary); line-height: 1.5;">
                            Part IX Statement of Functional Expenses is filed on Form 990 for 501(c)(3) public charities and operating organizations.<br>
                            Click <strong>Refresh Latest 990</strong> in the Overview tab to fetch the latest XML filing.
                        </div>
                    </div>
                `;
                return;
            }

            let progPct = Math.round(cached.program_percentage || 0);
            let adminPct = Math.round(cached.admin_percentage || 0);
            let fundPct = Math.round(cached.fundraising_percentage || 0);

            let sHtml = `
                <div class="spending-bar-wrapper">
                    <div style="display:flex; justify-content:space-between; align-items:baseline;">
                        <span style="font-weight: 700; font-size: 0.85rem;">Charitable Efficiency Allocation</span>
                        <span style="font-size: 0.72rem; color: var(--text-secondary);">Tax Year ${cached.tax_year || ''}</span>
                    </div>
                    <div class="spending-ratio-bar">
                        <div class="ratio-prog" style="width: ${progPct}%;" title="Program Services: ${progPct}%"></div>
                        <div class="ratio-admin" style="width: ${adminPct}%;" title="Admin & Overhead: ${adminPct}%"></div>
                        <div class="ratio-fund" style="width: ${fundPct}%;" title="Fundraising: ${fundPct}%"></div>
                    </div>
                    <div class="ratio-legend">
                        <div class="ratio-legend-item"><span class="ratio-dot ratio-prog"></span>Program: <strong>${progPct}%</strong></div>
                        <div class="ratio-legend-item"><span class="ratio-dot ratio-admin"></span>Admin: <strong>${adminPct}%</strong></div>
                        <div class="ratio-legend-item"><span class="ratio-dot ratio-fund"></span>Fundraising: <strong>${fundPct}%</strong></div>
                    </div>
                </div>

                <div class="financial-grid">
                    <div class="fin-card">
                        <div class="fin-label">Total Expenses</div>
                        <div class="fin-value">${formatUSD(cached.total_expenses)}</div>
                    </div>
                    <div class="fin-card">
                        <div class="fin-label">Program Services</div>
                        <div class="fin-value text-green">${formatUSD(cached.program_services)}</div>
                    </div>
                </div>

                <h3 style="font-size: 0.85rem; margin-top: 4px;">Key Expenditure Categories</h3>
                <table class="data-table">
                    <tbody>
                        ${cached.grants_paid > 0 ? `<tr><td>🤝 Grants & Assistance</td><td class="text-blue">${formatUSD(cached.grants_paid)}</td></tr>` : ''}
                        ${cached.salaries_total > 0 ? `<tr><td>👔 Personnel & Salaries</td><td>${formatUSD(cached.salaries_total)}</td></tr>` : ''}
                        ${cached.professional_fees > 0 ? `<tr><td>⚖️ Professional Fees (Legal, Lobbying)</td><td>${formatUSD(cached.professional_fees)}</td></tr>` : ''}
                        ${cached.office_and_it > 0 ? `<tr><td>💻 Office, IT & Occupancy</td><td>${formatUSD(cached.office_and_it)}</td></tr>` : ''}
                        ${cached.travel_and_conferences > 0 ? `<tr><td>✈️ Travel & Conferences</td><td>${formatUSD(cached.travel_and_conferences)}</td></tr>` : ''}
                        <tr><td>🏢 Management & Overhead</td><td class="text-amber">${formatUSD(cached.management_general)}</td></tr>
                        <tr><td>📣 Fundraising Activities</td><td>${formatUSD(cached.fundraising)}</td></tr>
                    </tbody>
                </table>
            `;

            if (contractors && contractors.length > 0) {
                sHtml += `
                    <h3 style="font-size: 0.85rem; margin-top: 10px;">Top Independent Contractors (&gt; $100k)</h3>
                    <div style="font-size: 0.72rem; color: var(--text-secondary); margin-top: -8px;">Disclosed under Form 990 Part VII Section B</div>
                    <table class="data-table">
                        <thead>
                            <tr><th>Contractor / Services</th><th>Compensation</th></tr>
                        </thead>
                        <tbody>
                `;
                for (const c of contractors) {
                    const loc = (c.city || c.state) ? ` • ${c.city || ''}, ${c.state || ''}` : '';
                    sHtml += `
                        <tr>
                            <td>
                                <strong style="cursor:pointer; color:var(--accent-primary);" title="Click to view cross-nonprofit contractor dossier" onclick="openContractorDrawer('${escapeJs(c.contractor_name)}')">${escapeHtml(c.contractor_name)} ↗</strong>
                                <span style="font-size:0.7rem; color:var(--text-secondary);">${loc}</span><br>
                                <span style="font-size:0.72rem; color:var(--text-secondary);">${escapeHtml(c.description_of_services || 'Services')}</span>
                            </td>
                            <td class="text-amber" style="font-weight:600;">${formatUSD(c.amount)}</td>
                        </tr>
                    `;
                }
                sHtml += `</tbody></table>`;
            }

            panel.innerHTML = sHtml;
        }

        function renderPeopleTab(node) {
            const panel = document.getElementById("tab-people");
            if (!panel || !node) return;

            if (!GRAPH_DATA.peopleLoaded) GRAPH_DATA.peopleLoaded = {};
            if (!GRAPH_DATA._peopleFetching) GRAPH_DATA._peopleFetching = {};

            const isLoaded = Boolean(GRAPH_DATA.peopleLoaded[node.ein]);
            const people = (GRAPH_DATA.people && GRAPH_DATA.people[node.ein]) ? GRAPH_DATA.people[node.ein] : [];

            if (!isLoaded && IS_SERVER_MODE) {
                if (GRAPH_DATA._peopleFetching[node.ein]) return;
                GRAPH_DATA._peopleFetching[node.ein] = true;
                panel.innerHTML = `<div style="text-align:center; padding: 24px 16px; color: var(--text-secondary);"><div class="progress-spinner" style="width:28px;height:28px;margin:0 auto 12px auto;"></div>Loading officers & trustees...</div>`;

                fetch(`/api/organization/${encodeURIComponent(node.ein)}/people`)
                    .then(r => {
                        if (!r.ok) throw new Error(`HTTP ${r.status}`);
                        return r.json();
                    })
                    .then(data => {
                        delete GRAPH_DATA._peopleFetching[node.ein];
                        if (!GRAPH_DATA.people) GRAPH_DATA.people = {};
                        GRAPH_DATA.people[node.ein] = data.people || [];
                        GRAPH_DATA.peopleLoaded[node.ein] = true;
                        if (currentActiveNode && currentActiveNode.ein === node.ein) {
                            renderPeopleTab(node);
                        }
                    })
                    .catch(err => {
                        delete GRAPH_DATA._peopleFetching[node.ein];
                        GRAPH_DATA.peopleLoaded[node.ein] = true;
                        if (currentActiveNode && currentActiveNode.ein === node.ein) {
                            panel.innerHTML = `<div style="color: var(--text-secondary); font-size: 0.82rem; padding: 16px; text-align: center;">Could not load leadership data: ${escapeHtml(err.message)}</div>`;
                        }
                    });
                return;
            }

            if (people.length === 0) {
                panel.innerHTML = `
                    <div style="background: var(--card-bg); border: 1px solid var(--surface-border); border-radius: 8px; padding: 16px; text-align: center;">
                        <div style="font-size: 1.5rem; margin-bottom: 8px;">👥</div>
                        <div style="font-weight: 600; font-size: 0.9rem; margin-bottom: 4px;">No Leadership Disclosures Found</div>
                        <div style="font-size: 0.76rem; color: var(--text-secondary); line-height: 1.5;">
                            Officers, directors, and trustees are disclosed on Form 990 Part VII or 990-PF Part VIII.<br>
                            Click <strong>Refresh Latest 990</strong> in the Overview tab to fetch the latest XML filing.
                        </div>
                    </div>
                `;
                return;
            }

            let pHtml = `
                <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom: 2px;">
                    <span style="font-weight: 700; font-size: 0.85rem;">Officers, Directors & Trustees (${people.length})</span>
                    <span style="font-size: 0.72rem; color: var(--text-secondary);">Tax Year ${people[0]?.tax_year || ''}</span>
                </div>
                <div style="font-size: 0.72rem; color: var(--text-secondary); margin-bottom: 8px; line-height: 1.4;">
                    💡 <strong>Double-click</strong> any row or click 🔍 to view cross-board affiliations and role capacities across other non-profit filings.
                </div>
                <table class="data-table">
                    <thead>
                        <tr><th>Name & Role</th><th>Time</th><th>Compensation</th></tr>
                    </thead>
                    <tbody>
            `;

            for (const p of people) {
                const hasInterlocks = (p.interlocks_count && p.interlocks_count > 0) || (p.other_boards && p.other_boards.length > 0);
                const interlockCount = p.interlocks_count || (p.other_boards ? p.other_boards.length : 0);
                const otherNames = (p.other_boards || []).map(b => `${escapeHtml(b.name)} (${escapeHtml(b.title)})`).join('; ');

                pHtml += `
                    <tr class="person-row-interactive"
                        ondblclick="openPersonProfile('${escapeJs(p.person_name)}', '${escapeJs(p.clean_name || p.person_name)}', '${escapeJs(node.ein)}', '${escapeJs(node.name)}')"
                        title="Double-click to check for other non-profit filings & leadership roles">
                        <td>
                            <div style="display:flex; justify-content:space-between; align-items:flex-start; gap: 4px;">
                                <div>
                                    <div style="font-weight: 600; font-size: 0.82rem;">${escapeHtml(p.person_name)}</div>
                                    <div style="font-size: 0.72rem; color: var(--text-secondary);">${escapeHtml(p.title || 'Trustee')}</div>
                                </div>
                                <button class="btn-profile-peek"
                                    onclick="event.stopPropagation(); openPersonProfile('${escapeJs(p.person_name)}', '${escapeJs(p.clean_name || p.person_name)}', '${escapeJs(node.ein)}', '${escapeJs(node.name)}')"
                                    title="View cross-board affiliations">🔍</button>
                            </div>
                            <div style="display:flex; gap: 4px; margin-top: 4px; flex-wrap: wrap;">
                                <span class="role-pill">${escapeHtml(p.role_type || 'Trustee')}</span>
                                ${hasInterlocks ? `<span class="interlock-badge" title="Also sits on: ${otherNames}">🔗 Sits on ${interlockCount + 1} boards!</span>` : ''}
                            </div>
                        </td>
                        <td style="font-size: 0.76rem; white-space: nowrap;">
                            ${p.hours_per_week > 0 ? `⏱️ ${p.hours_per_week}h/wk` : '<span style="color:var(--text-secondary);">Volunteer</span>'}
                        </td>
                        <td style="font-size: 0.78rem; white-space: nowrap;">
                            ${p.total_comp > 0 ? `<strong class="text-green">${formatUSD(p.total_comp)}</strong>` : '<span style="color:var(--text-secondary);">$0</span>'}
                        </td>
                    </tr>
                `;
            }

            pHtml += `</tbody></table>`;
            panel.innerHTML = pHtml;
        }

        function closePersonProfileModal() {
            const modal = document.getElementById("person-profile-modal");
            if (modal) modal.classList.remove("active");
        }

        function openPersonProfile(personName, cleanName, currentEin, currentOrgName) {
            const modal = document.getElementById("person-profile-modal");
            const titleEl = document.getElementById("pm-person-name");
            const subEl = document.getElementById("pm-person-sub");
            const bodyEl = document.getElementById("pm-modal-body");
            if (!modal || !bodyEl) return;

            titleEl.textContent = personName;
            subEl.textContent = `Cross-Filing Leadership & Governance Profile • ${currentOrgName || 'Current Organization'}`;
            bodyEl.innerHTML = `<div style="text-align:center; padding: 36px 16px; color: var(--text-secondary);"><div class="progress-spinner" style="width:32px;height:32px;margin:0 auto 12px auto;"></div>Searching all nonprofit filings for <strong>${escapeHtml(personName)}</strong>...</div>`;
            modal.classList.add("active");

            function renderProfileData(data) {
                const totalOrgs = data.total_organizations || (data.affiliations ? data.affiliations.length : 1);
                const hasInterlocks = totalOrgs > 1;

                let html = "";
                if (hasInterlocks) {
                    html += `
                        <div style="background: rgba(245, 158, 11, 0.12); border: 1px solid rgba(245, 158, 11, 0.35); border-radius: 10px; padding: 12px 14px; font-size: 0.8rem; color: #fbbf24; display: flex; align-items: center; gap: 10px;">
                            <span style="font-size: 1.3rem;">🔗</span>
                            <div>
                                <div style="font-weight: 700;">Cross-Board Leadership Interlock Detected</div>
                                <div style="color: var(--text-secondary); font-size: 0.74rem;">This individual sits on the leadership of <strong>${totalOrgs} distinct non-profit organizations</strong> in our database filings.</div>
                            </div>
                        </div>
                    `;
                } else {
                    html += `
                        <div style="background: rgba(59, 130, 246, 0.1); border: 1px solid rgba(59, 130, 246, 0.3); border-radius: 10px; padding: 12px 14px; font-size: 0.8rem; color: #93c5fd; display: flex; align-items: center; gap: 10px;">
                            <span style="font-size: 1.3rem;">👤</span>
                            <div>
                                <div style="font-weight: 700;">Solo Leadership Affiliation</div>
                                <div style="color: var(--text-secondary); font-size: 0.74rem;">No other non-profit board or officer disclosures were found in the current filings database for this individual.</div>
                            </div>
                        </div>
                    `;
                }

                html += `<div style="display: flex; flex-direction: column; gap: 10px; margin-top: 6px;">`;

                const affiliations = data.affiliations || [];
                for (const aff of affiliations) {
                    const isCurrent = (aff.ein === currentEin);
                    html += `
                        <div class="person-affil-card">
                            <div style="display: flex; justify-content: space-between; align-items: flex-start; gap: 8px;">
                                <div>
                                    <div style="display: flex; align-items: center; gap: 6px; flex-wrap: wrap;">
                                        <strong style="font-size: 0.88rem; color: var(--text-primary);">${escapeHtml(aff.name)}</strong>
                                        ${isCurrent ? 
                                            `<span style="background: rgba(16, 185, 129, 0.18); color: #10b981; border: 1px solid rgba(16, 185, 129, 0.4); padding: 1px 7px; border-radius: 4px; font-size: 0.68rem; font-weight: 600;">Current Entity</span>` : 
                                            `<span style="background: rgba(245, 158, 11, 0.18); color: #f59e0b; border: 1px solid rgba(245, 158, 11, 0.4); padding: 1px 7px; border-radius: 4px; font-size: 0.68rem; font-weight: 600;">🔗 Cross-Board Interlock</span>`
                                        }
                                    </div>
                                    <div style="font-size: 0.72rem; color: var(--text-secondary); margin-top: 1px;">EIN: ${aff.ein}</div>
                                </div>
                                ${!isCurrent ? `
                                    <button class="btn-table-recenter" onclick="closePersonProfileModal(); recenterOnEntity('${aff.ein}', '${escapeJs(aff.name)}')" title="Recenter network graph on this organization">
                                        🎯 Recenter Graph
                                    </button>
                                ` : ''}
                            </div>
                            <div style="display: flex; flex-direction: column; gap: 4px; margin-top: 2px;">
                    `;

                    for (const role of (aff.roles || [])) {
                        const yearsStr = (role.start_year && role.end_year) ? 
                            (role.start_year === role.end_year ? `Tax Year ${role.start_year}` : `Years: ${role.start_year} – ${role.end_year}`) : '';
                        html += `
                            <div style="display: flex; justify-content: space-between; align-items: center; background: rgba(255, 255, 255, 0.03); padding: 6px 10px; border-radius: 6px; font-size: 0.78rem;">
                                <div>
                                    <span style="font-weight: 600;">${escapeHtml(role.title || 'Leadership')}</span>
                                    <span class="role-pill" style="margin-left: 6px;">${escapeHtml(role.role_type || 'Trustee')}</span>
                                    ${yearsStr ? `<span style="font-size: 0.7rem; color: var(--text-secondary); margin-left: 6px;">(${yearsStr})</span>` : ''}
                                </div>
                                <div style="display: flex; gap: 10px; font-size: 0.76rem;">
                                    <span style="color: var(--text-secondary);">${role.hours_per_week > 0 ? `⏱️ ${role.hours_per_week}h/wk` : 'Volunteer'}</span>
                                    <span>${role.total_comp > 0 ? `<strong class="text-green">${formatUSD(role.total_comp)}</strong>` : '<span style="color:var(--text-secondary);">$0</span>'}</span>
                                </div>
                            </div>
                        `;
                    }

                    html += `
                            </div>
                        </div>
                    `;
                }

                html += `</div>`;
                bodyEl.innerHTML = html;
            }

            if (IS_SERVER_MODE) {
                fetch(`/api/person/profile?name=${encodeURIComponent(cleanName || personName)}`)
                    .then(r => {
                        if (!r.ok) throw new Error(`HTTP ${r.status}`);
                        return r.json();
                    })
                    .then(data => {
                        renderProfileData(data);
                    })
                    .catch(err => {
                        fallbackToLocal();
                    });
            } else {
                fallbackToLocal();
            }

            function fallbackToLocal() {
                const orgsMap = {};
                orgsMap[currentEin] = {
                    ein: currentEin,
                    name: currentOrgName || (GRAPH_DATA.nodes[currentEin] ? GRAPH_DATA.nodes[currentEin].name : `Org ${currentEin}`),
                    roles: []
                };

                const peopleList = (GRAPH_DATA.people && GRAPH_DATA.people[currentEin]) ? GRAPH_DATA.people[currentEin] : [];
                const personObj = peopleList.find(p => (p.clean_name === cleanName || p.person_name === personName));
                if (personObj) {
                    orgsMap[currentEin].roles.push({
                        title: personObj.title,
                        role_type: personObj.role_type,
                        hours_per_week: personObj.hours_per_week,
                        total_comp: personObj.total_comp,
                        start_year: personObj.tax_year,
                        end_year: personObj.tax_year
                    });

                    if (personObj.other_boards) {
                        for (const b of personObj.other_boards) {
                            if (!orgsMap[b.ein]) {
                                orgsMap[b.ein] = {
                                    ein: b.ein,
                                    name: b.name,
                                    roles: []
                                };
                            }
                            orgsMap[b.ein].roles.push({
                                title: b.title,
                                role_type: b.role_type,
                                hours_per_week: 0,
                                total_comp: 0,
                                start_year: null,
                                end_year: null
                            });
                        }
                    }
                }

                renderProfileData({
                    person_name: personName,
                    total_organizations: Object.keys(orgsMap).length,
                    affiliations: Object.values(orgsMap)
                });
            }
        }

        function renderPacsTab(node) {
            const panel = document.getElementById("tab-pacs");
            if (!panel || !node) return;

            if (!GRAPH_DATA.pacsLoaded) GRAPH_DATA.pacsLoaded = {};
            if (!GRAPH_DATA._pacsFetching) GRAPH_DATA._pacsFetching = {};

            const isLoaded = Boolean(GRAPH_DATA.pacsLoaded[node.ein]);

            if (!isLoaded && IS_SERVER_MODE) {
                if (GRAPH_DATA._pacsFetching[node.ein]) return;
                GRAPH_DATA._pacsFetching[node.ein] = true;
                panel.innerHTML = `<div style="text-align:center; padding: 24px 16px; color: var(--text-secondary);"><div class="progress-spinner" style="width:28px;height:28px;margin:0 auto 12px auto;"></div>Scanning cross-entity PAC & 527 linkages...</div>`;

                fetch(`/api/organization/${encodeURIComponent(node.ein)}/pacs`)
                    .then(r => {
                        if (!r.ok) throw new Error(`HTTP ${r.status}`);
                        return r.json();
                    })
                    .then(data => {
                        GRAPH_DATA.pacsLoaded[node.ein] = data.linkages || [];
                        GRAPH_DATA._pacsFetching[node.ein] = false;
                        renderPacsTab(node);
                    })
                    .catch(err => {
                        console.error("Failed loading PAC linkages:", err);
                        GRAPH_DATA._pacsFetching[node.ein] = false;
                        GRAPH_DATA.pacsLoaded[node.ein] = [];
                        panel.innerHTML = `<div style="padding:16px; color:var(--text-secondary); font-size:0.85rem;">No active political committee connections identified.</div>`;
                    });
                return;
            }

            const linkages = GRAPH_DATA.pacsLoaded[node.ein] || [];
            if (!linkages || linkages.length === 0) {
                panel.innerHTML = `
                    <div style="padding: 24px 14px; text-align: center; color: var(--text-secondary);">
                        <div style="font-size: 2.2rem; margin-bottom: 8px;">🗳️</div>
                        <div style="font-weight: 600; color: var(--text-primary); margin-bottom: 4px;">No Political Committee Connections Found</div>
                        <div style="font-size: 0.78rem; line-height: 1.4;">
                            No connected Super PACs, Form 8871 527 registrations, shared political leadership, or shared vendors detected for <strong>${escapeHtml(node.name)}</strong>.
                        </div>
                    </div>
                `;
                return;
            }

            let html = `
                <div style="padding: 10px 0 14px 0;">
                    <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 12px;">
                        <span style="font-weight: 700; font-size: 0.95rem; color: #f87171;">🗳️ Connected PACs & Conduits (${linkages.length})</span>
                        <span style="font-size: 0.72rem; color: var(--text-secondary);">Cross-Entity Engine</span>
                    </div>
            `;

            for (const link of linkages) {
                const isFec = (link.target_type === "fec_pac");
                const badgeColor = isFec ? "rgba(239, 68, 68, 0.15)" : "rgba(245, 158, 11, 0.15)";
                const badgeTextColor = isFec ? "#ef4444" : "#f59e0b";
                const badgeBorder = isFec ? "rgba(239, 68, 68, 0.4)" : "rgba(245, 158, 11, 0.4)";
                const typeIcon = isFec ? "🗳️ FEC Federal PAC" : "⚡ IRS 527 Org";
                const confPct = Math.round((link.confidence_score || 0) * 100);

                const clickFn = isFec ? `openFECDrawer('${escapeJs(link.target_id)}')` : `open527Drawer('${escapeJs(link.target_id)}')`;

                const inGraph = Boolean(nodesDataset && nodesDataset.get(link.target_id));
                const actionBtn = inGraph ?
                    `<button class="btn-profile-peek" style="margin-top:8px; font-size:0.75rem; width:100%; justify-content:center; padding:4px 8px;" onclick="event.stopPropagation(); focusNodeInGraph('${escapeJs(link.target_id)}');">🎯 Center in Map</button>` :
                    `<button class="btn-profile-peek" style="margin-top:8px; font-size:0.75rem; width:100%; justify-content:center; padding:4px 8px;" onclick="event.stopPropagation(); injectPacIntoGraph('${escapeJs(link.target_id)}', '${escapeJs(link.target_name)}', '${escapeJs(node.ein)}', '${escapeJs(link.link_type)}', '${escapeJs(link.target_type)}');">➕ Inject PAC into Graph</button>`;

                html += `
                    <div style="background: rgba(15, 23, 42, 0.6); border: 1px solid var(--border-color); border-radius: 8px; padding: 12px; margin-bottom: 10px; cursor: pointer; transition: all 0.15s ease;"
                         onmouseover="this.style.borderColor='#f87171'" onmouseout="this.style.borderColor='var(--border-color)'"
                         onclick="${clickFn}">
                        <div style="display: flex; justify-content: space-between; align-items: flex-start; gap: 8px; margin-bottom: 6px;">
                            <div style="font-weight: 700; color: #f1f5f9; font-size: 0.88rem;">${escapeHtml(link.target_name)}</div>
                            <span style="display: inline-block; padding: 2px 8px; border-radius: 12px; font-size: 0.7rem; font-weight: 600; background: ${badgeColor}; color: ${badgeTextColor}; border: 1px solid ${badgeBorder}; white-space: nowrap;">
                                ${typeIcon}
                            </span>
                        </div>
                        <div style="font-size: 0.74rem; color: #94a3b8; margin-bottom: 6px; line-height: 1.35;">
                            ${escapeHtml(link.description)}
                        </div>
                        <div style="display: flex; justify-content: space-between; align-items: center; font-size: 0.7rem; color: #64748b;">
                            <span>Link Type: <strong style="color: #cbd5e1;">${escapeHtml(link.link_type.replace(/_/g, ' '))}</strong></span>
                            <span>Confidence: <strong style="color: ${confPct >= 85 ? '#10b981' : '#f59e0b'};">${confPct}%</strong></span>
                        </div>
                        ${actionBtn}
                    </div>
                `;
            }

            html += `</div>`;
            panel.innerHTML = html;
        }

        function openEdgeDrawer(edge) {
            const drawer = document.getElementById("side-drawer");
            const drawerTabs = document.getElementById("drawer-tabs");
            if (drawerTabs) drawerTabs.style.display = "none";

            document.querySelectorAll(".drawer-tab-panel").forEach(p => p.classList.remove("active"));
            const edgePanel = document.getElementById("tab-edge");
            if (edgePanel) {
                edgePanel.style.display = "flex";
                edgePanel.classList.add("active");
            }

            const data = edge.data;
            if (edge.edgeType === "grant") {
                document.getElementById("drawer-org-name").textContent = "Grant Funding Link";
                document.getElementById("drawer-org-meta").textContent = `${data.grantor_name} → ${data.recipient_name}`;

                let breakdownHtml = "";
                if (data.annual_breakdown) {
                    for (const [yr, amt] of Object.entries(data.annual_breakdown)) {
                        breakdownHtml += `<tr><td>Tax Year ${yr}</td><td class="text-green">${formatUSD(amt)}</td></tr>`;
                    }
                }

                const content = `
                    <div class="financial-grid">
                        <div class="fin-card">
                            <div class="fin-label">Cumulative Grant</div>
                            <div class="fin-value">${formatUSD(data.total_amount)}</div>
                        </div>
                        <div class="fin-card">
                            <div class="fin-label">Filings Count</div>
                            <div class="fin-value">${data.grant_count} Returns</div>
                        </div>
                    </div>
                    <div style="font-size: 0.85rem; color: var(--text-secondary); line-height: 1.6;">
                        <div><strong>Grantor:</strong> ${escapeHtml(data.grantor_name)} (EIN ${data.grantor_ein})</div>
                        <div><strong>Recipient:</strong> ${escapeHtml(data.recipient_name)} (EIN ${data.recipient_ein})</div>
                        <div><strong>Stated Purposes:</strong> ${escapeHtml(data.purposes.join(', ') || 'General Support')}</div>
                        <div><strong>Source Schedule:</strong> ${escapeHtml((data.source_schedules || []).join(', ') || 'Schedule I')}</div>
                    </div>
                    ${breakdownHtml ? `
                        <h3 style="font-size: 0.85rem; margin-top: 10px;">Annual Breakdown</h3>
                        <table class="data-table">
                            <thead><tr><th>Year</th><th>Amount</th></tr></thead>
                            <tbody>${breakdownHtml}</tbody>
                        </table>
                    ` : ''}
                `;
                if (edgePanel) edgePanel.innerHTML = content;
            } else {
                document.getElementById("drawer-org-name").textContent = "Corporate Relationship (Schedule R)";
                document.getElementById("drawer-org-meta").textContent = `${data.entity_name} & ${data.related_name}`;
                const content = `
                    <div class="fin-card">
                        <div class="fin-label">Relationship Type</div>
                        <div class="fin-value" style="color: var(--accent-rel);">${escapeHtml(data.relationship_type)}</div>
                    </div>
                    <div style="font-size: 0.85rem; color: var(--text-secondary); margin-top: 14px; line-height: 1.6;">
                        <div><strong>Primary Activity:</strong> ${escapeHtml(data.primary_activity || 'Governance / Charitable Support')}</div>
                        <div><strong>Schedule:</strong> Schedule R</div>
                    </div>
                    <div style="display: flex; gap: 10px; margin-top: 16px;">
                        <button class="btn-recenter-main" onclick="recenterOnEntity('${data.entity_ein}', '${escapeJs(data.entity_name)}')">
                            🎯 Center on ${escapeHtml(data.entity_name)}
                        </button>
                        <button class="btn-recenter-main" onclick="recenterOnEntity('${data.related_ein}', '${escapeJs(data.related_name)}')">
                            🎯 Center on ${escapeHtml(data.related_name)}
                        </button>
                    </div>
                `;
                if (edgePanel) edgePanel.innerHTML = content;
            }
            drawer.classList.add("open");
        }

        // Event Listeners
        document.getElementById("btn-close-drawer").addEventListener("click", () => {
            document.getElementById("side-drawer").classList.remove("open");
        });

        // Theme Toggle
        document.getElementById("btn-theme").addEventListener("click", () => {
            document.body.classList.toggle("light-mode");
        });

        // Center View
        document.getElementById("btn-reset-view").addEventListener("click", () => {
            if (network) network.fit({ animation: { duration: 600, easingFunction: "easeInOutQuad" } });
        });

        // Live Search & Autocomplete
        const searchInput = document.getElementById("node-search");
        const suggestionsBox = document.getElementById("search-suggestions");
        let searchDebounceTimer = null;

        searchInput.addEventListener("input", (e) => {
            const term = e.target.value.toLowerCase().trim();
            if (!term) {
                suggestionsBox.classList.remove("active");
                return;
            }

            // Local node search match
            const localMatches = [];
            nodesDataset.forEach(n => {
                if (n.label.toLowerCase().includes(term) || n.id.includes(term)) {
                    localMatches.push({ id: n.id, name: n.label, local: true });
                }
            });

            if (IS_SERVER_MODE && term.length >= 2) {
                clearTimeout(searchDebounceTimer);
                searchDebounceTimer = setTimeout(async () => {
                    try {
                        const res = await fetch(`/api/search/omni?q=${encodeURIComponent(term)}`);
                        if (res.ok) {
                            const apiResults = await res.json();
                            renderOmniSuggestions(localMatches, apiResults, term);
                        }
                    } catch (err) {
                        renderOmniSuggestions(localMatches, {}, term);
                    }
                }, 200);
            } else {
                renderOmniSuggestions(localMatches, {}, term);
            }
        });

        // Pressing Enter immediately selects top suggestion or triggers direct omni search
        searchInput.addEventListener("keydown", async (e) => {
            if (e.key === "Enter") {
                e.preventDefault();
                const firstItem = suggestionsBox.querySelector(".suggestion-item");
                if (firstItem && suggestionsBox.classList.contains("active")) {
                    firstItem.click();
                    return;
                }
                const term = searchInput.value.trim();
                if (!term || !IS_SERVER_MODE) return;

                try {
                    const res = await fetch(`/api/search/omni?q=${encodeURIComponent(term)}`);
                    if (res.ok) {
                        const results = await res.json();
                        if (results.fec_pacs && results.fec_pacs.length > 0) {
                            suggestionsBox.classList.remove("active");
                            openFECDrawer(results.fec_pacs[0].cmte_id);
                            return;
                        }
                        if (results.pacs_527 && results.pacs_527.length > 0) {
                            suggestionsBox.classList.remove("active");
                            open527Drawer(results.pacs_527[0].form_id || results.pacs_527[0].ein);
                            return;
                        }
                        if (results.organizations && results.organizations.length > 0) {
                            suggestionsBox.classList.remove("active");
                            recenterOnEntity(results.organizations[0].ein, results.organizations[0].name);
                            return;
                        }
                        if (results.people && results.people.length > 0) {
                            suggestionsBox.classList.remove("active");
                            openPersonProfileModal(results.people[0].name);
                            return;
                        }
                        showToast(`No entities found matching "${term}".`);
                    }
                } catch (err) {
                    showToast("Search error: " + err.message);
                }
            }
        });

        function renderOmniSuggestions(localMatches, apiResults, term = "") {
            suggestionsBox.innerHTML = "";
            let hasAny = false;

            // 1. Nonprofits
            const seenOrgs = new Set();
            const orgItems = [];
            localMatches.forEach(m => {
                seenOrgs.add(m.id);
                orgItems.push({ ein: m.id, name: m.name, meta: "In Current Graph", inGraph: true });
            });
            const remoteOrgs = apiResults.organizations || (Array.isArray(apiResults) ? apiResults : []);
            remoteOrgs.forEach(r => {
                if (!seenOrgs.has(r.ein)) {
                    seenOrgs.add(r.ein);
                    const rev = r.revenue > 0 ? ` • Rev: ${formatCompactUSD(r.revenue)}` : '';
                    orgItems.push({
                        ein: r.ein,
                        name: r.name,
                        meta: `${r.city || ''}, ${r.state || ''} • EIN ${r.ein}${rev}`,
                        inGraph: false
                    });
                }
            });

            if (orgItems.length > 0) {
                hasAny = true;
                const hdr = document.createElement("div");
                hdr.className = "suggestion-category-header";
                hdr.innerHTML = `<span>🏛️ Nonprofit Organizations</span> <span class="suggestion-badge">${orgItems.length}</span>`;
                suggestionsBox.appendChild(hdr);

                orgItems.slice(0, 5).forEach(item => {
                    const div = document.createElement("div");
                    div.className = "suggestion-item";
                    div.innerHTML = `
                        <div class="suggestion-name">${escapeHtml(item.name)}</div>
                        <div class="suggestion-meta">${escapeHtml(item.meta)}</div>
                    `;
                    div.addEventListener("click", () => {
                        suggestionsBox.classList.remove("active");
                        searchInput.value = item.name;
                        if (nodesDataset.get(item.ein)) {
                            network.selectNodes([item.ein]);
                            network.focus(item.ein, { scale: 1.2, animation: { duration: 500 } });
                            const nodeObj = GRAPH_DATA.nodes[item.ein];
                            if (nodeObj) openNodeDrawer(nodeObj);
                        } else {
                            recenterOnEntity(item.ein, item.name);
                        }
                    });
                    suggestionsBox.appendChild(div);
                });
            }

            // 2. People & Board Members
            const people = apiResults.people || [];
            if (people.length > 0) {
                hasAny = true;
                const hdr = document.createElement("div");
                hdr.className = "suggestion-category-header";
                hdr.innerHTML = `<span>👤 Leadership & Trustees</span> <span class="suggestion-badge">${people.length}</span>`;
                suggestionsBox.appendChild(hdr);

                people.slice(0, 4).forEach(item => {
                    const div = document.createElement("div");
                    div.className = "suggestion-item";
                    div.innerHTML = `
                        <div class="suggestion-name">${escapeHtml(item.name)}</div>
                        <div class="suggestion-meta">${item.org_count} board seat(s) • ${escapeHtml(item.titles || 'Officer')}</div>
                    `;
                    div.addEventListener("click", () => {
                        suggestionsBox.classList.remove("active");
                        searchInput.value = item.name;
                        openPersonProfileModal(item.name);
                    });
                    suggestionsBox.appendChild(div);
                });
            }

            // 3. Commercial Contractors & Vendors
            const contractors = apiResults.contractors || [];
            if (contractors.length > 0) {
                hasAny = true;
                const hdr = document.createElement("div");
                hdr.className = "suggestion-category-header";
                hdr.innerHTML = `<span>💼 Commercial Contractors</span> <span class="suggestion-badge">${contractors.length}</span>`;
                suggestionsBox.appendChild(hdr);

                contractors.slice(0, 4).forEach(item => {
                    const div = document.createElement("div");
                    div.className = "suggestion-item";
                    div.innerHTML = `
                        <div class="suggestion-name">${escapeHtml(item.contractor_name)}</div>
                        <div class="suggestion-meta">Total: ${formatCompactUSD(item.total_amount)} • ${item.client_count} client charity(s)</div>
                    `;
                    div.addEventListener("click", () => {
                        suggestionsBox.classList.remove("active");
                        searchInput.value = item.contractor_name;
                        openContractorDrawer(item.contractor_name);
                    });
                    suggestionsBox.appendChild(div);
                });
            }

            // 4. Schedule R Corporate Affiliates
            const affiliates = apiResults.affiliates || [];
            if (affiliates.length > 0) {
                hasAny = true;
                const hdr = document.createElement("div");
                hdr.className = "suggestion-category-header";
                hdr.innerHTML = `<span>🏢 Corporate Affiliates</span> <span class="suggestion-badge">${affiliates.length}</span>`;
                suggestionsBox.appendChild(hdr);

                affiliates.slice(0, 3).forEach(item => {
                    const div = document.createElement("div");
                    div.className = "suggestion-item";
                    div.innerHTML = `
                        <div class="suggestion-name">${escapeHtml(item.related_name)}</div>
                        <div class="suggestion-meta">[${escapeHtml(item.relationship_type)}] ⟷ ${escapeHtml(item.entity_name)}</div>
                    `;
                    div.addEventListener("click", () => {
                        suggestionsBox.classList.remove("active");
                        searchInput.value = item.related_name;
                        const targetEin = item.related_ein || item.entity_ein;
                        if (targetEin) recenterOnEntity(targetEin, item.related_name);
                    });
                    suggestionsBox.appendChild(div);
                });
            }

            // 5. Section 527 Political Committees
            const pacs = apiResults.pacs_527 || [];
            if (pacs.length > 0) {
                hasAny = true;
                const hdr = document.createElement("div");
                hdr.className = "suggestion-category-header";
                hdr.innerHTML = `<span>⚡ Section 527 Political Orgs</span> <span class="suggestion-badge">${pacs.length}</span>`;
                suggestionsBox.appendChild(hdr);

                pacs.slice(0, 3).forEach(item => {
                    const div = document.createElement("div");
                    div.className = "suggestion-item";
                    div.innerHTML = `
                        <div class="suggestion-name">${escapeHtml(item.name)}</div>
                        <div class="suggestion-meta">Form ${item.form_type} • ${escapeHtml(item.city || '')}, ${escapeHtml(item.state || '')}</div>
                    `;
                    div.addEventListener("click", () => {
                        suggestionsBox.classList.remove("active");
                        searchInput.value = item.name;
                        open527Drawer(item.form_id || item.ein);
                    });
                    suggestionsBox.appendChild(div);
                });
            }

            // 6. FEC Federal Political Committees & Super PACs
            const fecPacs = apiResults.fec_pacs || [];
            if (fecPacs.length > 0) {
                hasAny = true;
                const hdr = document.createElement("div");
                hdr.className = "suggestion-category-header";
                hdr.innerHTML = `<span>🗳️ Federal PACs & Super PACs</span> <span class="suggestion-badge">${fecPacs.length}</span>`;
                suggestionsBox.appendChild(hdr);

                fecPacs.slice(0, 5).forEach(item => {
                    const div = document.createElement("div");
                    div.className = "suggestion-item";
                    const isSuper = (item.cmte_type === 'O' || (item.type_label && item.type_label.toLowerCase().includes('super pac')));
                    const badgeStyle = isSuper ?
                        'background:rgba(245,158,11,0.18); color:#f59e0b; border:1px solid rgba(245,158,11,0.3);' :
                        'background:rgba(59,130,246,0.15); color:#60a5fa;';
                    const sponsor = item.connected_org ? ` • Spons: ${item.connected_org}` : '';
                    div.innerHTML = `
                        <div style="display:flex; justify-content:space-between; align-items:center;">
                            <div class="suggestion-name">${escapeHtml(item.name)}</div>
                            <span style="font-size:0.68rem; padding:2px 6px; border-radius:4px; font-weight:700; ${badgeStyle}">
                                ${escapeHtml(item.type_label)}
                            </span>
                        </div>
                        <div class="suggestion-meta">ID: ${item.cmte_id} • ${escapeHtml(item.state || 'US')}${escapeHtml(sponsor)}</div>
                    `;
                    div.addEventListener("click", () => {
                        suggestionsBox.classList.remove("active");
                        searchInput.value = item.name;
                        openFECDrawer(item.cmte_id);
                    });
                    suggestionsBox.appendChild(div);
                });
            } else if (IS_SERVER_MODE && (term.includes("pac") || term.includes("527") || term.includes("committ") || term.includes("super"))) {
                hasAny = true;
                const hintDiv = document.createElement("div");
                hintDiv.className = "suggestion-item";
                hintDiv.style.background = "rgba(59, 130, 246, 0.08)";
                hintDiv.style.borderLeft = "3px solid var(--accent-primary, #3b82f6)";
                hintDiv.innerHTML = `
                    <div class="suggestion-name" style="color:var(--text-primary); font-weight:600;">⚡ Quick-Sync FEC Federal PACs</div>
                    <div class="suggestion-meta">Populate 35k+ registered federal PACs & Super PACs into local database (~2.5 MB)</div>
                `;
                hintDiv.addEventListener("click", async () => {
                    suggestionsBox.classList.remove("active");
                    showToast("⏳ Rapidly syncing FEC Committee Master data in background...");
                    try {
                        const res = await fetch("/api/fec/sync-committees");
                        if (res.ok) {
                            const data = await res.json();
                            showToast(`✅ Ingested ${data.total_ingested || 0} FEC committees! Search again.`);
                        } else {
                            showToast("⚠️ Could not sync FEC committees from upstream.");
                        }
                    } catch (e) {
                        showToast("⚠️ Sync error: " + e.message);
                    }
                });
                suggestionsBox.appendChild(hintDiv);
            }

            if (!hasAny) {
                suggestionsBox.classList.remove("active");
                return;
            }

            suggestionsBox.classList.add("active");
        }

        async function openContractorDrawer(contractorName) {
            const drawer = document.getElementById("side-drawer");
            document.getElementById("drawer-org-name").textContent = "💼 " + contractorName;
            document.getElementById("drawer-org-meta").textContent = "Commercial Contractor & Independent Vendor • Form 990 Part VII Sec B";

            const drawerTabs = document.getElementById("drawer-tabs");
            if (drawerTabs) drawerTabs.style.display = "none";

            const overviewPanel = document.getElementById("tab-overview");
            overviewPanel.classList.add("active");
            document.querySelectorAll(".drawer-tab-panel").forEach(p => {
                if (p.id !== "tab-overview") p.classList.remove("active");
            });

            overviewPanel.innerHTML = `
                <div style="text-align:center; padding: 40px 16px;">
                    <div class="progress-spinner" style="width:32px;height:32px;margin:0 auto 12px auto;"></div>
                    Loading commercial profile for <strong>${escapeHtml(contractorName)}</strong>...
                </div>
            `;
            drawer.classList.add("open");

            try {
                const res = await fetch(`/api/contractor/dossier?name=${encodeURIComponent(contractorName)}`);
                if (!res.ok) throw new Error("Contractor profile not found");
                const d = await res.json();

                let clientsHtml = "";
                d.clients.forEach((c, idx) => {
                    const serv = c.services && c.services.length > 0 ? c.services.join("; ") : "Commercial Professional Services";
                    const yrs = c.years && c.years.length > 0 ? c.years.join(", ") : "N/A";
                    clientsHtml += `
                        <div style="padding: 12px; margin-bottom: 10px; background: rgba(255,255,255,0.03); border: 1px solid var(--surface-border); border-radius: 8px;">
                            <div style="display:flex; justify-content:space-between; align-items:flex-start; margin-bottom:4px;">
                                <div>
                                    <div style="font-weight: 600; color: var(--text-primary); font-size: 0.88rem;">${escapeHtml(c.filer_name)}</div>
                                    <div style="font-size: 0.72rem; color: var(--text-secondary);">EIN: ${escapeHtml(c.filer_ein)} • Tax Years: ${escapeHtml(yrs)}</div>
                                </div>
                                <div style="font-weight: 700; color: #10b981; font-size: 0.92rem; text-align:right;">
                                    ${formatUSD(c.total_paid)}
                                </div>
                            </div>
                            <div style="font-size: 0.75rem; color: var(--text-secondary); margin-bottom: 8px;">
                                🛠️ ${escapeHtml(serv)}
                            </div>
                            <button class="btn btn-sm btn-primary" style="width:100%; font-size: 0.72rem; padding: 4px 8px; justify-content:center;" onclick="recenterOnEntity('${c.filer_ein}', '${escapeJs(c.filer_name)}')">
                                🎯 Center Map on This Charity
                            </button>
                        </div>
                    `;
                });

                overviewPanel.innerHTML = `
                    <div style="display:grid; grid-template-columns: 1fr 1fr; gap: 8px; margin-bottom: 14px;">
                        <div class="financial-card">
                            <div class="financial-label">Total Billings (All Nonprofits)</div>
                            <div class="financial-val" style="color: #10b981;">${formatUSD(d.total_amount)}</div>
                        </div>
                        <div class="financial-card">
                            <div class="financial-label">Client Charities</div>
                            <div class="financial-val" style="color: var(--accent-primary);">${d.client_count}</div>
                        </div>
                    </div>
                    ${d.services && d.services.length > 0 ? `
                        <div style="margin-bottom: 14px; font-size: 0.78rem; color: var(--text-secondary);">
                            <strong>Known Services:</strong> ${escapeHtml(d.services.join(", "))}
                        </div>
                    ` : ''}
                    <div class="section-title" style="margin-bottom: 10px;">
                        Nonprofit Clients & Contracts (${d.clients.length})
                    </div>
                    ${clientsHtml}
                `;
            } catch (err) {
                overviewPanel.innerHTML = `
                    <div style="padding: 20px; text-align: center; color: var(--text-secondary);">
                        ⚠️ Failed to load contractor dossier: ${escapeHtml(err.message)}
                    </div>
                `;
            }
        }

        async function open527Drawer(einOrId) {
            const drawer = document.getElementById("side-drawer");
            document.getElementById("drawer-org-name").textContent = "⚡ Political Organization";
            document.getElementById("drawer-org-meta").textContent = "IRS Section 527 Political Committee • Loading...";

            const drawerTabs = document.getElementById("drawer-tabs");
            if (drawerTabs) drawerTabs.style.display = "none";

            const overviewPanel = document.getElementById("tab-overview");
            overviewPanel.classList.add("active");
            document.querySelectorAll(".drawer-tab-panel").forEach(p => {
                if (p.id !== "tab-overview") p.classList.remove("active");
            });

            overviewPanel.innerHTML = `
                <div style="text-align:center; padding: 40px 16px;">
                    <div class="progress-spinner" style="width:32px;height:32px;margin:0 auto 12px auto;"></div>
                    Loading Section 527 Committee Profile...
                </div>
            `;
            drawer.classList.add("open");

            try {
                let org = null;
                if (GRAPH_DATA.sec527Dossiers && GRAPH_DATA.sec527Dossiers[einOrId]) {
                    org = GRAPH_DATA.sec527Dossiers[einOrId];
                } else if (IS_SERVER_MODE) {
                    const res = await fetch(`/api/527/org/${encodeURIComponent(einOrId)}`);
                    if (!res.ok) throw new Error("527 organization not found");
                    org = await res.json();
                } else {
                    throw new Error("Section 527 dossier not bundled in this offline snapshot");
                }

                document.getElementById("drawer-org-name").textContent = "⚡ " + org.name;
                document.getElementById("drawer-org-meta").textContent = `IRS Section 527 • Form ${org.form_type} • EIN: ${org.ein || 'N/A'}`;

                const s527Id = org.ein || einOrId;
                const inGraph = Boolean(nodesDataset && nodesDataset.get(s527Id));
                const s527GraphBtn = inGraph ?
                    `<button class="btn" style="margin-bottom:12px; width:100%; justify-content:center; font-size:0.8rem;" onclick="focusNodeInGraph('${escapeJs(s527Id)}');">🎯 Center 527 in Graph</button>` :
                    `<button class="btn" style="margin-bottom:12px; width:100%; justify-content:center; font-size:0.8rem;" onclick="injectPacIntoGraph('${escapeJs(s527Id)}', '${escapeJs(org.name)}', TARGET_EIN, 'form_8871_notice', '527_org');">➕ Inject 527 into Graph</button>`;

                let dirHtml = "";
                if (org.directors && org.directors.length > 0) {
                    dirHtml = `
                        <div class="section-title" style="margin-top:14px; margin-bottom:8px;">Officers & Directors (${org.directors.length})</div>
                        <div style="display:flex; flex-direction:column; gap:6px; margin-bottom:14px;">
                            ${org.directors.map(d => `
                                <div style="display:flex; justify-content:space-between; align-items:center; padding:6px 10px; background:rgba(255,255,255,0.03); border:1px solid var(--surface-border); border-radius:6px; font-size:0.78rem;">
                                    <div>
                                        <strong style="color:var(--text-primary);">${escapeHtml(d.name)}</strong>
                                        <span style="color:var(--text-secondary); margin-left:6px;">${escapeHtml(d.title || 'Officer')}</span>
                                    </div>
                                    <button class="btn-profile-peek" onclick="openPersonProfileModal('${escapeJs(d.name)}')">👤 View</button>
                                </div>
                            `).join("")}
                        </div>
                    `;
                }

                let relHtml = "";
                if (org.related_entities && org.related_entities.length > 0) {
                    relHtml = `
                        <div class="section-title" style="margin-top:14px; margin-bottom:8px;">Connected & Related Organizations (${org.related_entities.length})</div>
                        <div style="display:flex; flex-direction:column; gap:6px; margin-bottom:14px;">
                            ${org.related_entities.map(r => `
                                <div style="padding:8px 10px; background:rgba(255,255,255,0.03); border:1px solid var(--surface-border); border-radius:6px; font-size:0.78rem;">
                                    <div style="font-weight:600; color:var(--text-primary);">${escapeHtml(r.related_name)}</div>
                                    <div style="font-size:0.72rem; color:var(--text-secondary);">Relationship: ${escapeHtml(r.relationship)} • Location: ${escapeHtml(r.city || '')}, ${escapeHtml(r.state || '')}</div>
                                </div>
                            `).join("")}
                        </div>
                    `;
                }

                let repHtml = "";
                if (org.reports && org.reports.length > 0) {
                    repHtml = `
                        <div class="section-title" style="margin-top:14px; margin-bottom:8px;">Recent Form 8872 Filings</div>
                        <div style="display:flex; flex-direction:column; gap:6px;">
                            ${org.reports.map(rep => `
                                <div style="padding:8px 10px; background:rgba(255,255,255,0.03); border:1px solid var(--surface-border); border-radius:6px; font-size:0.78rem;">
                                    <div style="display:flex; justify-content:space-between; margin-bottom:4px;">
                                        <span style="color:var(--text-secondary);">${escapeHtml(rep.begin)} to ${escapeHtml(rep.end)}</span>
                                        <span style="font-weight:600; color:#10b981;">+${formatUSD(rep.contributions)}</span>
                                    </div>
                                    <div style="display:flex; justify-content:flex-end;">
                                        <span style="font-weight:600; color:#ef4444;">Disbursements: ${formatUSD(rep.expenditures)}</span>
                                    </div>
                                </div>
                            `).join("")}
                        </div>
                    `;
                }

                overviewPanel.innerHTML = `
                    ${s527GraphBtn}
                    <div style="font-size:0.8rem; color:var(--text-secondary); margin-bottom:12px; line-height:1.4;">
                        ${org.purpose ? `<strong>Stated Purpose:</strong> ${escapeHtml(org.purpose)}<br/>` : ''}
                        ${org.custodian_name ? `<strong>Custodian of Records:</strong> ${escapeHtml(org.custodian_name)}<br/>` : ''}
                        ${org.email ? `<strong>Email:</strong> ${escapeHtml(org.email)}<br/>` : ''}
                        ${org.city ? `<strong>Location:</strong> ${escapeHtml(org.city)}, ${escapeHtml(org.state)} ${escapeHtml(org.zip)}` : ''}
                    </div>
                    ${dirHtml}
                    ${relHtml}
                    ${repHtml}
                `;
            } catch (err) {
                overviewPanel.innerHTML = `
                    <div style="padding: 20px; text-align: center; color: var(--text-secondary);">
                        ⚠️ Failed to load Section 527 profile: ${escapeHtml(err.message)}
                    </div>
                `;
            }
        }

        async function openFECDrawer(cmteId) {
            const drawer = document.getElementById("side-drawer");
            document.getElementById("drawer-org-name").textContent = "🗳️ Political Committee";
            document.getElementById("drawer-org-meta").textContent = "Federal Election Commission (FEC) • Loading...";

            const drawerTabs = document.getElementById("drawer-tabs");
            if (drawerTabs) drawerTabs.style.display = "none";

            const overviewPanel = document.getElementById("tab-overview");
            overviewPanel.classList.add("active");
            document.querySelectorAll(".drawer-tab-panel").forEach(p => {
                if (p.id !== "tab-overview") p.classList.remove("active");
            });

            overviewPanel.innerHTML = `
                <div style="text-align:center; padding: 40px 16px;">
                    <div class="progress-spinner" style="width:32px;height:32px;margin:0 auto 12px auto;"></div>
                    Loading FEC Committee Dossier...
                </div>
            `;
            drawer.classList.add("open");

            try {
                let cmte = null;
                if (GRAPH_DATA.fecDossiers && GRAPH_DATA.fecDossiers[cmteId]) {
                    cmte = GRAPH_DATA.fecDossiers[cmteId];
                } else if (IS_SERVER_MODE) {
                    const res = await fetch(`/api/fec/committee/${encodeURIComponent(cmteId)}`);
                    if (!res.ok) throw new Error("FEC committee not found");
                    cmte = await res.json();
                } else {
                    throw new Error("FEC Committee dossier not bundled in this offline snapshot");
                }

                const isSuper = (cmte.cmte_type === 'O' || (cmte.type_label && cmte.type_label.toLowerCase().includes('super pac')));
                const typeBadge = isSuper ?
                    `<span style="background:rgba(245,158,11,0.18); color:#f59e0b; border:1px solid rgba(245,158,11,0.3); padding:2px 8px; border-radius:4px; font-weight:700; font-size:0.75rem;">Super PAC</span>` :
                    `<span style="background:rgba(59,130,246,0.15); color:#60a5fa; padding:2px 8px; border-radius:4px; font-weight:600; font-size:0.75rem;">${escapeHtml(cmte.type_label || 'PAC')}</span>`;

                document.getElementById("drawer-org-name").textContent = "🗳️ " + cmte.name;
                document.getElementById("drawer-org-meta").innerHTML = `FEC ID: ${cmte.cmte_id} • ${typeBadge} • Cycle: ${cmte.cycle || 'Active'}`;

                const inGraph = Boolean(nodesDataset && nodesDataset.get(cmte.cmte_id));
                const cmteGraphBtn = inGraph ?
                    `<button class="btn" style="margin-bottom:12px; width:100%; justify-content:center; font-size:0.8rem;" onclick="focusNodeInGraph('${escapeJs(cmte.cmte_id)}');">🎯 Center Committee in Graph</button>` :
                    `<button class="btn" style="margin-bottom:12px; width:100%; justify-content:center; font-size:0.8rem;" onclick="injectPacIntoGraph('${escapeJs(cmte.cmte_id)}', '${escapeJs(cmte.name)}', TARGET_EIN, 'fec_committee', 'fec_pac');">➕ Inject Committee into Graph</button>`;

                let candHtml = "";
                if (cmte.candidates && cmte.candidates.length > 0) {
                    candHtml = `
                        <div class="section-title" style="margin-top:14px; margin-bottom:8px;">Linked Candidates (${cmte.candidates.length})</div>
                        <div style="display:flex; flex-direction:column; gap:6px; margin-bottom:14px;">
                            ${cmte.candidates.map(c => {
                                const cInGraph = Boolean(nodesDataset && nodesDataset.get(c.candidate_id));
                                const cActionBtn = cInGraph ?
                                    `<button class="btn-profile-peek" style="padding:2px 8px; font-size:0.72rem;" onclick="focusNodeInGraph('${escapeJs(c.candidate_id)}');">🎯 Focus</button>` :
                                    `<button class="btn-profile-peek" style="padding:2px 8px; font-size:0.72rem;" onclick="injectCandidateIntoGraph('${escapeJs(c.candidate_id)}', '${escapeJs(c.candidate_name)}', '${escapeJs(c.party || '')}', '${escapeJs(c.office || '')}', '${escapeJs(cmte.cmte_id)}', '${escapeJs(cmte.name)}');">➕ Graph</button>`;

                                return `
                                    <div style="display:flex; justify-content:space-between; align-items:center; padding:6px 10px; background:rgba(255,255,255,0.03); border:1px solid var(--surface-border); border-radius:6px; font-size:0.78rem;">
                                        <div>
                                            <strong style="color:var(--text-primary); cursor:pointer;" onclick="openCandidateDrawer({ id: '${escapeJs(c.candidate_id)}', name: '${escapeJs(c.candidate_name)}', metadata: { party: '${escapeJs(c.party||'')}', office: '${escapeJs(c.office||'')}', office_state: '${escapeJs(c.office_state||'')}', cmte_id: '${escapeJs(cmte.cmte_id)}', cmte_name: '${escapeJs(cmte.name)}' } })">${escapeHtml(c.candidate_name)}</strong>
                                            <span style="color:var(--text-secondary); margin-left:6px;">${escapeHtml(c.party)} • ${escapeHtml(c.office)} ${escapeHtml(c.office_state || '')}</span>
                                        </div>
                                        <div style="display:flex; align-items:center; gap:6px;">
                                            ${cActionBtn}
                                            <span class="badge" style="background:rgba(99,102,241,0.15); color:#818cf8;">${c.candidate_id}</span>
                                        </div>
                                    </div>
                                `;
                            }).join("")}
                        </div>
                    `;
                }

                let txHtml = "";
                const tx = cmte.expenditures_summary || {};
                const hasTx = (tx.supporting && tx.supporting.length > 0) || (tx.opposing && tx.opposing.length > 0);
                if (hasTx) {
                    txHtml = `
                        <div class="section-title" style="margin-top:14px; margin-bottom:8px;">Top Independent Expenditures</div>
                        <div style="display:flex; flex-direction:column; gap:6px; margin-bottom:14px;">
                            ${(tx.supporting || []).map(s => `
                                <div style="padding:6px 10px; background:rgba(16,185,129,0.05); border:1px solid rgba(16,185,129,0.2); border-radius:6px; font-size:0.78rem;">
                                    <div style="display:flex; justify-content:space-between;">
                                        <span style="color:#10b981; font-weight:600;">🟢 SUPPORT: ${escapeHtml(s.recipient_name)}</span>
                                        <span style="font-weight:700; color:#10b981;">${formatUSD(s.total_amount)}</span>
                                    </div>
                                </div>
                            `).join("")}
                            ${(tx.opposing || []).map(o => `
                                <div style="padding:6px 10px; background:rgba(239,68,68,0.05); border:1px solid rgba(239,68,68,0.2); border-radius:6px; font-size:0.78rem;">
                                    <div style="display:flex; justify-content:space-between;">
                                        <span style="color:#ef4444; font-weight:600;">🔴 OPPOSE: ${escapeHtml(o.recipient_name)}</span>
                                        <span style="font-weight:700; color:#ef4444;">${formatUSD(o.total_amount)}</span>
                                    </div>
                                </div>
                            `).join("")}
                        </div>
                    `;
                }

                let vendorHtml = "";
                if (cmte.top_vendors && cmte.top_vendors.length > 0) {
                    vendorHtml = `
                        <div class="section-title" style="margin-top:14px; margin-bottom:8px;">Top Campaign Vendors & Media Firms</div>
                        <div style="display:flex; flex-direction:column; gap:6px; margin-bottom:14px;">
                            ${cmte.top_vendors.map(v => `
                                <div style="display:flex; justify-content:space-between; align-items:center; padding:6px 10px; background:rgba(255,255,255,0.03); border:1px solid var(--surface-border); border-radius:6px; font-size:0.78rem;">
                                    <div>
                                        <strong style="color:var(--text-primary);">${escapeHtml(v.payee_name)}</strong>
                                        <div style="color:var(--text-secondary); font-size:0.72rem;">${escapeHtml(v.purposes || 'Operating Expense')}</div>
                                    </div>
                                    <span style="font-weight:700; color:var(--text-primary);">${formatUSD(v.total_amount)}</span>
                                </div>
                            `).join("")}
                        </div>
                    `;
                }

                let sponsorHtml = "";
                if (cmte.connected_org) {
                    sponsorHtml = `
                        <div style="padding:10px 12px; margin-bottom:12px; background:rgba(99,102,241,0.08); border:1px solid rgba(99,102,241,0.25); border-radius:8px; font-size:0.78rem;">
                            <strong style="color:#818cf8;">🏢 Connected Sponsoring Organization:</strong><br/>
                            <span style="color:var(--text-primary); font-size:0.85rem; font-weight:600;">${escapeHtml(cmte.connected_org)}</span>
                            <div style="margin-top:4px; font-size:0.72rem; color:var(--text-secondary);">Direct bridge to sponsoring 501(c) charity, labor union, or trade association.</div>
                        </div>
                    `;
                }

                overviewPanel.innerHTML = `
                    ${cmteGraphBtn}
                    ${sponsorHtml}
                    <div style="font-size:0.8rem; color:var(--text-secondary); margin-bottom:12px; line-height:1.4;">
                        ${cmte.party ? `<strong>Party Affiliation:</strong> ${escapeHtml(cmte.party)}<br/>` : ''}
                        ${cmte.treasurer_name ? `<strong>Treasurer:</strong> ${escapeHtml(cmte.treasurer_name)}<br/>` : ''}
                        ${cmte.city ? `<strong>Location:</strong> ${escapeHtml(cmte.city)}, ${escapeHtml(cmte.state)} ${escapeHtml(cmte.zip)}` : ''}
                    </div>
                    ${candHtml}
                    ${txHtml}
                    ${vendorHtml}
                `;
            } catch (err) {
                overviewPanel.innerHTML = `
                    <div style="padding: 20px; text-align: center; color: var(--text-secondary);">
                        ⚠️ Failed to load FEC Committee profile: ${escapeHtml(err.message)}
                    </div>
                `;
            }
        }

        function openCandidateDrawer(nodeObj) {
            const drawer = document.getElementById("side-drawer");
            const candId = nodeObj.id || (nodeObj.data && nodeObj.data.ein) || nodeObj.ein;
            const candName = nodeObj.name || (nodeObj.data && nodeObj.data.name) || nodeObj.label;
            const meta = nodeObj.metadata || (nodeObj.data && nodeObj.data.metadata) || {};

            document.getElementById("drawer-org-name").textContent = "👤 " + candName;
            document.getElementById("drawer-org-meta").textContent = `Federal Candidate • ID: ${candId} • Party: ${meta.party || 'N/A'}`;

            const drawerTabs = document.getElementById("drawer-tabs");
            if (drawerTabs) drawerTabs.style.display = "none";

            const overviewPanel = document.getElementById("tab-overview");
            overviewPanel.classList.add("active");
            document.querySelectorAll(".drawer-tab-panel").forEach(p => {
                if (p.id !== "tab-overview") p.classList.remove("active");
            });

            const inGraph = Boolean(nodesDataset && nodesDataset.get(candId));
            const graphBtn = inGraph ?
                `<button class="btn" style="margin-bottom:14px; width:100%; justify-content:center;" onclick="focusNodeInGraph('${escapeJs(candId)}');">🎯 Center Candidate in Graph</button>` :
                `<button class="btn" style="margin-bottom:14px; width:100%; justify-content:center;" onclick="injectCandidateIntoGraph('${escapeJs(candId)}', '${escapeJs(candName)}', '${escapeJs(meta.party||'')}', '${escapeJs(meta.office||'')}', '${escapeJs(meta.cmte_id||'')}');">➕ Add Candidate to Graph</button>`;

            overviewPanel.innerHTML = `
                ${graphBtn}
                <div style="background: rgba(139, 92, 246, 0.08); border: 1px solid rgba(139, 92, 246, 0.25); border-radius: 8px; padding: 12px; margin-bottom: 14px; font-size: 0.8rem;">
                    <div style="font-weight: 700; color: #a78bfa; margin-bottom: 4px;">Federal Election Commission Candidate Record</div>
                    <div style="color: var(--text-secondary); line-height: 1.5;">
                        <strong>Candidate ID:</strong> ${escapeHtml(candId)}<br/>
                        <strong>Party:</strong> ${escapeHtml(meta.party || 'Not Listed')}<br/>
                        <strong>Office Sought:</strong> ${escapeHtml(meta.office || 'Federal Office')} ${escapeHtml(meta.office_state || '')}<br/>
                        ${meta.cmte_name ? `<strong>Linked Committee:</strong> ${escapeHtml(meta.cmte_name)} (${escapeHtml(meta.cmte_id)})` : ''}
                    </div>
                </div>
                <div style="font-size: 0.78rem; color: var(--text-secondary); line-height: 1.4;">
                    Independent expenditures and campaign committees associated with this candidate can be filtered and analyzed using the HUD layer controls and PAC inspector.
                </div>
            `;
            drawer.classList.add("open");
        }

        function focusNodeInGraph(nodeId) {
            if (!network || !nodesDataset) return;
            const node = nodesDataset.get(nodeId);
            if (!node) return;
            network.focus(nodeId, {
                scale: 1.25,
                animation: { duration: 600, easingFunction: "easeInOutQuad" }
            });
            network.selectNodes([nodeId]);
        }

        function injectPacIntoGraph(pacId, pacName, anchorEin, linkType, targetType) {
            if (!nodesDataset) return;
            const existingNode = nodesDataset.get(pacId);
            if (!existingNode) {
                const isFec = (targetType === "fec_pac");
                const newNode = {
                    id: pacId,
                    label: pacName,
                    title: `🗳️ POLITICAL ACTION COMMITTEE [${isFec ? 'FEC PAC' : 'IRS 527'}]\n${pacName}\nID: ${pacId}\n(Click to inspect PAC details and disbursements)`,
                    color: COLORS.pac,
                    size: 28,
                    shape: "hexagon",
                    borderWidth: 3,
                    font: { color: "#ffffff", size: 12, face: "sans-serif" },
                    direction: "pac",
                    metadata: { is_pac: true, target_type: targetType, link_type: linkType },
                    data: { ein: pacId, name: pacName, direction: "pac", metadata: { is_pac: true, target_type: targetType } }
                };
                nodesDataset.add(newNode);
                GRAPH_DATA.nodes[pacId] = newNode.data;
            }

            const edgeKey = `pac_${pacId}_${anchorEin}`;
            const edgeId = `rel:` + edgeKey;
            if (!edgesDataset.get(edgeId)) {
                const labelText = (linkType || "PAC Linkage").replace(/_/g, " ");
                const newEdge = {
                    id: edgeId,
                    from: anchorEin,
                    to: pacId,
                    arrows: "",
                    label: labelText,
                    font: { size: 9, color: COLORS.edgePac, align: "middle", strokeWidth: 0 },
                    color: { color: COLORS.edgePac, opacity: 0.95 },
                    width: 2.8,
                    dashes: [4, 4],
                    smooth: { type: "curvedCCW", roundness: 0.2 },
                    title: `Political Action Committee Bridge: ${labelText}`,
                    edgeType: "pac_linkage",
                    length: 150,
                    physics: true,
                    amount: 0,
                    data: {
                        entity_ein: anchorEin,
                        related_ein: pacId,
                        relationship_type: labelText,
                        source_schedule: "PAC Linkage"
                    }
                };
                edgesDataset.add(newEdge);
                GRAPH_DATA.relationship_edges[edgeKey] = newEdge.data;
            }

            const pacToggle = document.getElementById("layer-pacs");
            if (pacToggle && !pacToggle.checked) {
                pacToggle.checked = true;
            }
            applyFilterVisibility();
            focusNodeInGraph(pacId);
            showToast(`🗳️ Injected ${pacName} into graph`);

            if (currentActiveNode) {
                renderPacsTab(currentActiveNode);
            }
        }

        function injectCandidateIntoGraph(candidateId, candidateName, party, office, cmteId, cmteName) {
            if (!nodesDataset) return;
            const existingNode = nodesDataset.get(candidateId);
            if (!existingNode) {
                const newCandNode = {
                    id: candidateId,
                    label: candidateName,
                    title: `👤 CANDIDATE [${party || ''} • ${office || 'Federal Candidate'}]\n${candidateName}\nID: ${candidateId}\n(Click to view candidate support & opposition)`,
                    color: { background: "#8b5cf6", border: "#7c3aed" },
                    size: 24,
                    shape: "diamond",
                    borderWidth: 2,
                    font: { color: "#ffffff", size: 12, face: "sans-serif" },
                    direction: "candidate",
                    metadata: { is_candidate: true, party: party, office: office, cmte_id: cmteId, cmte_name: cmteName },
                    data: { ein: candidateId, name: candidateName, direction: "candidate", metadata: { is_candidate: true, party: party, office: office, cmte_id: cmteId, cmte_name: cmteName } }
                };
                nodesDataset.add(newCandNode);
                GRAPH_DATA.nodes[candidateId] = newCandNode.data;
            }

            if (cmteId) {
                const edgeKey = `exp_${cmteId}_${candidateId}`;
                const edgeId = `rel:` + edgeKey;
                if (!edgesDataset.get(edgeId)) {
                    const newEdge = {
                        id: edgeId,
                        from: cmteId,
                        to: candidateId,
                        arrows: "to",
                        label: "Expenditure",
                        font: { size: 9, color: "#10b981", align: "middle", strokeWidth: 0 },
                        color: { color: "#10b981", opacity: 0.95 },
                        width: 2.5,
                        dashes: [4, 4],
                        smooth: { type: "curvedCCW", roundness: 0.2 },
                        title: `Candidate Independent Expenditure by ${cmteName || cmteId}`,
                        edgeType: "pac_expenditure",
                        length: 160,
                        physics: true,
                        amount: 0,
                        data: {
                            entity_ein: cmteId,
                            related_ein: candidateId,
                            relationship_type: "Independent Expenditure",
                            source_schedule: "Candidate Independent Expenditure",
                            primary_activity: `Campaign spending by ${cmteName || cmteId}`
                        }
                    };
                    edgesDataset.add(newEdge);
                    GRAPH_DATA.relationship_edges[edgeKey] = newEdge.data;
                }
            }

            const pacToggle = document.getElementById("layer-pacs");
            if (pacToggle && !pacToggle.checked) {
                pacToggle.checked = true;
            }
            applyFilterVisibility();
            focusNodeInGraph(candidateId);
            showToast(`👤 Injected candidate ${candidateName} into graph`);
        }

        document.addEventListener("click", (e) => {
            if (!searchInput.contains(e.target) && !suggestionsBox.contains(e.target)) {
                suggestionsBox.classList.remove("active");
            }
        });

        // Centralized Filter Visibility Engine
        function applyFilterVisibility() {
            const minAmt = parseFloat(document.getElementById("threshold-slider").value) || 0;
            const dirToggle = document.querySelector("#direction-toggle .btn-segmented.active");
            const dir = dirToggle ? dirToggle.dataset.dir : "all";

            const layerGrants = document.getElementById("layer-grants") ? document.getElementById("layer-grants").checked : true;
            const layerAffiliates = document.getElementById("layer-affiliates") ? document.getElementById("layer-affiliates").checked : true;
            const layerPacs = document.getElementById("layer-pacs") ? document.getElementById("layer-pacs").checked : true;

            const lblGrants = document.getElementById("lbl-layer-grants");
            if (lblGrants) lblGrants.classList.toggle("active", layerGrants);
            const lblAffiliates = document.getElementById("lbl-layer-affiliates");
            if (lblAffiliates) lblAffiliates.classList.toggle("active", layerAffiliates);
            const lblPacs = document.getElementById("lbl-layer-pacs");
            if (lblPacs) lblPacs.classList.toggle("active", layerPacs);

            edgesDataset.forEach(edge => {
                let isVisible = true;
                if (edge.edgeType === "grant") {
                    if (!layerGrants) {
                        isVisible = false;
                    } else if (edge.amount < minAmt) {
                        isVisible = false;
                    } else if (dir === "upstream" && edge.to !== TARGET_EIN) {
                        isVisible = false;
                    } else if (dir === "downstream" && edge.from !== TARGET_EIN) {
                        isVisible = false;
                    }
                } else if (edge.edgeType === "relationship") {
                    if (!layerAffiliates || dir !== "all") {
                        isVisible = false;
                    }
                } else if (edge.edgeType === "pac_linkage" || edge.edgeType === "pac_expenditure") {
                    if (!layerPacs || dir !== "all") {
                        isVisible = false;
                    }
                }
                edgesDataset.update({ id: edge.id, hidden: !isVisible });
            });

            nodesDataset.forEach(node => {
                if (node.id === TARGET_EIN) {
                    nodesDataset.update({ id: node.id, hidden: false });
                    return;
                }

                const nDir = node.direction || (node.data ? node.data.direction : "");
                const isPac = (nDir === "pac" || (node.metadata && node.metadata.is_pac));
                const isCandidate = (nDir === "candidate" || (node.metadata && node.metadata.is_candidate));

                let isVisible = true;
                if (isPac || isCandidate) {
                    isVisible = layerPacs && (dir === "all");
                } else if (nDir === "related") {
                    isVisible = layerAffiliates && (dir === "all");
                } else {
                    if (!layerGrants) {
                        isVisible = false;
                    } else if (dir === "all") {
                        isVisible = true;
                    } else {
                        isVisible = (nDir === dir);
                    }
                }

                nodesDataset.update({ id: node.id, hidden: !isVisible });
            });

            if (network) network.redraw();
        }

        // Min Grant Slider
        const slider = document.getElementById("threshold-slider");
        const sliderVal = document.getElementById("threshold-val");
        if (slider) {
            slider.addEventListener("input", (e) => {
                const minAmt = parseFloat(e.target.value);
                if (sliderVal) sliderVal.textContent = formatCompactUSD(minAmt);
                applyFilterVisibility();
            });
        }

        // Direction Filter
        const dirToggle = document.getElementById("direction-toggle");
        if (dirToggle) {
            dirToggle.addEventListener("click", (e) => {
                if (!e.target.dataset.dir) return;
                document.querySelectorAll("#direction-toggle .btn-segmented").forEach(b => b.classList.remove("active"));
                e.target.classList.add("active");
                applyFilterVisibility();
            });
        }

        // Layer Toggles
        ["layer-grants", "layer-affiliates", "layer-pacs"].forEach(id => {
            const el = document.getElementById(id);
            if (el) {
                el.addEventListener("change", applyFilterVisibility);
            }
        });

        // Layout Toggle
        document.getElementById("layout-toggle").addEventListener("click", (e) => {
            if (!e.target.dataset.layout) return;
            document.querySelectorAll("#layout-toggle .btn-segmented").forEach(b => b.classList.remove("active"));
            e.target.classList.add("active");

            const layout = e.target.dataset.layout;
            if (layout === "hierarchical") {
                network.setOptions({
                    layout: {
                        hierarchical: {
                            direction: "UD",
                            sortMethod: "directed",
                            levelSeparation: 150
                        }
                    },
                    physics: { hierarchicalRepulsion: { nodeDistance: 180 } }
                });
            } else {
                network.setOptions({
                    layout: { hierarchical: false },
                    physics: {
                        solver: "barnesHut",
                        barnesHut: { gravitationalConstant: -18000, centralGravity: 0.4, springLength: 160 }
                    }
                });
            }
        });

        // Freeze Physics
        document.getElementById("btn-toggle-physics").addEventListener("click", (e) => {
            physicsEnabled = !physicsEnabled;
            network.setOptions({ physics: { enabled: physicsEnabled } });
            e.target.textContent = physicsEnabled ? "⏸️ Freeze Movement" : "▶️ Resume Physics";
        });

        // Person Leadership Modal Close Handlers
        const btnClosePersonModal = document.getElementById("btn-close-person-modal");
        if (btnClosePersonModal) {
            btnClosePersonModal.addEventListener("click", closePersonProfileModal);
        }
        const personModalOverlay = document.getElementById("person-profile-modal");
        if (personModalOverlay) {
            personModalOverlay.addEventListener("click", (e) => {
                if (e.target === personModalOverlay) closePersonProfileModal();
            });
        }
        window.addEventListener("keydown", (e) => {
            if (e.key === "Escape") {
                closePersonProfileModal();
            }
        });

        // Save Snapshot in Server Mode
        {% if is_server_mode %}
        const btnSaveSnap = document.getElementById("btn-export-snapshot");
        if (btnSaveSnap) {
            btnSaveSnap.addEventListener("click", async () => {
                btnSaveSnap.textContent = "⏳ Saving...";
                try {
                    const res = await fetch("/api/export", {
                        method: "POST",
                        headers: { "Content-Type": "application/json" },
                        body: JSON.stringify(GRAPH_DATA)
                    });
                    const resJson = await res.json();
                    if (resJson.success) {
                        showToast(`💾 Snapshot saved to ${resJson.filename}`);
                    } else {
                        showToast(`Export failed: ${resJson.error}`);
                    }
                } catch (e) {
                    showToast(`Export error: ${e.message}`);
                } finally {
                    btnSaveSnap.textContent = "💾 Save Snapshot";
                }
            });
        }
        {% endif %}

        // Export CSV
        document.getElementById("btn-export-csv").addEventListener("click", () => {
            let csv = "GrantorEIN,GrantorName,RecipientEIN,RecipientName,TotalAmount,Years,Purposes\\n";
            for (const g of Object.values(GRAPH_DATA.grant_edges)) {
                csv += `"${g.grantor_ein}","${g.grantor_name}","${g.recipient_ein}","${g.recipient_name}",${g.total_amount},"${g.years.join(';')}","${g.purposes.join(';')}"\\n`;
            }
            const blob = new Blob([csv], { type: "text/csv;charset=utf-8;" });
            const url = URL.createObjectURL(blob);
            const a = document.createElement("a");
            a.href = url;
            a.download = `${TARGET_EIN}_funding_grants.csv`;
            a.click();
        });

        // Export JSON
        document.getElementById("btn-export-json").addEventListener("click", () => {
            const str = JSON.stringify(GRAPH_DATA, null, 2);
            const blob = new Blob([str], { type: "application/json" });
            const url = URL.createObjectURL(blob);
            const a = document.createElement("a");
            a.href = url;
            a.download = `${TARGET_EIN}_funding_graph.json`;
            a.click();
        });

        // Export PNG
        document.getElementById("btn-export-png").addEventListener("click", () => {
            const canvas = document.querySelector("#network-canvas canvas");
            if (canvas) {
                const img = canvas.toDataURL("image/png");
                const a = document.createElement("a");
                a.href = img;
                a.download = `${TARGET_EIN}_graph.png`;
                a.click();
            }
        });

        // HUD Collapse & Expand Controls
        const hudCard = document.getElementById("hud-card");
        const btnHudCollapse = document.getElementById("hud-collapse-btn");
        const btnHudExpand = document.getElementById("hud-expand-btn");

        function setHudCollapsed(collapsed) {
            if (collapsed) {
                if (hudCard) hudCard.classList.add("collapsed");
                if (btnHudExpand) btnHudExpand.classList.add("visible");
            } else {
                if (hudCard) hudCard.classList.remove("collapsed");
                if (btnHudExpand) btnHudExpand.classList.remove("visible");
            }
        }

        if (btnHudCollapse) {
            btnHudCollapse.addEventListener("click", () => setHudCollapsed(true));
        }
        if (btnHudExpand) {
            btnHudExpand.addEventListener("click", () => setHudCollapsed(false));
        }

        window.addEventListener("resize", () => {
            if (network) {
                network.redraw();
            }
        });

        // Initialize on load
        if (document.readyState === "loading") {
            window.addEventListener("DOMContentLoaded", initGraph);
        } else {
            initGraph();
        }
    </script>
</body>
</html>
"""


class VisualizerGenerator:
    """HTML visualization generator embedding Vis.js network graph and data payloads."""

    def __init__(self) -> None:
        """Initialize generator and load locally bundled CSS and JavaScript assets."""
        self.vis_js_content = ""
        self.vis_css_content = ""
        self._load_assets()

    def _load_assets(self) -> None:
        """Load embedded Vis.js scripts and stylesheets from local assets directory."""
        js_path = os.path.join(ASSETS_DIR, "vis-network.min.js")
        css_path = os.path.join(ASSETS_DIR, "vis-network.min.css")

        # SECURITY: Verify assets exist locally to prevent remote CDN dependencies per Directive 3
        if os.path.exists(js_path):
            with open(js_path, "r", encoding="utf-8") as f:
                self.vis_js_content = f.read()
        else:
            logger.warning(f"vis-network.min.js not found in {ASSETS_DIR}, falling back to CDN script tag")
            self.vis_js_content = "/* Vis.js loaded via CDN */"

        if os.path.exists(css_path):
            with open(css_path, "r", encoding="utf-8") as f:
                self.vis_css_content = f.read()
        else:
            self.vis_css_content = "/* Vis.css */"

    def generate_html(
        self,
        graph: NetworkGraph,
        output_filepath: str,
        is_server_mode: bool = False,
        storage: Optional[Any] = None
    ) -> str:
        """Generate a standalone self-contained HTML visualization from NetworkGraph.

        Args:
            graph: Populated NetworkGraph instance with nodes and edges.
            output_filepath: Destination filesystem path for HTML file.
            is_server_mode: If True, activates dynamic server API synchronization hooks.
            storage: Optional active DuckDB storage backend for pre-populating dossiers.

        Returns:
            Absolute filepath string of the generated HTML output.
        """
        expenses_dict = {}
        contractors_dict = {}
        people_dict = {}
        pacs_loaded_dict = {}
        fec_dossiers_dict = {}
        sec527_dossiers_dict = {}

        if storage:
            for ein in graph.nodes:
                exp = storage.get_expenses(ein)
                if exp:
                    expenses_dict[ein] = [e.to_dict() for e in exp]
                con = storage.get_contractors(ein)
                if con:
                    contractors_dict[ein] = [c.to_dict() for c in con]
                ppl = storage.get_people_by_organization(ein)
                if ppl:
                    people_dict[ein] = [p.to_dict() for p in ppl]

            try:
                from .linkage import LinkageResolver
                resolver = LinkageResolver(storage)
                for ein in graph.nodes:
                    links = resolver.resolve_organization_linkages(ein)
                    if links:
                        pacs_loaded_dict[ein] = [l.to_dict() for l in links]
                        for l in links:
                            if l.target_type == "fec_pac":
                                if l.target_id not in fec_dossiers_dict:
                                    cmte_prof = storage.get_fec_committee(l.target_id)
                                    if cmte_prof:
                                        fec_dossiers_dict[l.target_id] = cmte_prof
                            elif l.target_type == "527_org":
                                if l.target_id not in sec527_dossiers_dict:
                                    s527_prof = storage.get_527_org(l.target_id)
                                    if s527_prof:
                                        sec527_dossiers_dict[l.target_id] = s527_prof
            except Exception as e:
                logger.warning(f"Could not pre-populate political dossiers for offline snapshot: {e}")

        # Serialize graph to JSON dictionary
        graph_dict = {
            "target": graph.target_node.to_dict(),
            "nodes": {ein: node.to_dict() for ein, node in graph.nodes.items()},
            "grant_edges": {k: edge.to_dict() for k, edge in graph.grant_edges.items()},
            "relationship_edges": {k: rel.to_dict() for k, rel in graph.relationship_edges.items()},
            "expenses": expenses_dict,
            "contractors": contractors_dict,
            "people": people_dict,
            "pacsLoaded": pacs_loaded_dict,
            "fecDossiers": fec_dossiers_dict,
            "sec527Dossiers": sec527_dossiers_dict
        }

        total_funding_amt = sum(e.total_amount for e in graph.grant_edges.values())

        template = Template(HTML_TEMPLATE)
        rendered_html = template.render(
            graph=graph,
            graph_json=json.dumps(graph_dict),
            total_funding_amt=total_funding_amt,
            format_currency=format_currency,
            vis_js=self.vis_js_content,
            vis_css=self.vis_css_content,
            is_server_mode=is_server_mode
        )

        os.makedirs(os.path.dirname(os.path.abspath(output_filepath)), exist_ok=True)
        with open(output_filepath, "w", encoding="utf-8") as f:
            f.write(rendered_html)

        logger.info(f"Successfully generated portable HTML file: {output_filepath}")
        return output_filepath
