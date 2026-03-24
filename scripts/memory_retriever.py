#!/usr/bin/env python3
"""
memory_retriever.py — Retrieve agent memory at session startup.

Pulls tiered memories from Firestore and formats them for system prompt
injection. Called by agent bootstrap before main task execution.

Usage:
    python scripts/memory_retriever.py --agent trader-agent --domain markets-trading
    python scripts/memory_retriever.py --agent investment-agent --domain fundamental-research --methods bayesian-inference,valuation
    python scripts/memory_retriever.py --agent trader-agent --domain markets-trading --format raw --max-items 30
"""

import argparse
import json
import math
import sys
from datetime import datetime, timedelta, timezone

from scripts.firestore_writer import _ensure_db


# ── Scoring ────────────────────────────────────────────────────────

def recency_boost(created_at, now):
    """Exponential decay: 1.0 at 0 days, ~0.5 at 7 days."""
    if created_at is None:
        return 0.0
    delta = now - created_at
    days = delta.total_seconds() / 86400
    return math.exp(-0.1 * max(0, days))


def composite_score(item, query_domains, query_methods, now):
    """Re-rank items with composite scoring."""
    base = item.get('currentScore', 0)

    # Recency
    created = item.get('createdAt')
    recency = recency_boost(created, now)

    # Access popularity
    access_count = max(1, item.get('accessCount', 0))
    popularity = math.log2(access_count)

    # Domain overlap
    item_domains = set(item.get('domains', []))
    domain_overlap = (
        len(item_domains & set(query_domains)) / len(query_domains)
        if query_domains else 0
    )

    # Method overlap
    item_methods = set(item.get('methods', []))
    method_overlap = (
        len(item_methods & set(query_methods)) / len(query_methods)
        if query_methods else 0
    )

    return base + 0.2 * recency + 0.1 * popularity + 0.15 * domain_overlap + 0.1 * method_overlap


# ── Retrieval Tiers ────────────────────────────────────────────────

def retrieve_tier1(db, tenant_id, primary_domain, limit=10):
    """Own domain: insights + domain layer, score >= 0.3."""
    ref = db.collection(f'tenants/{tenant_id}/memory_items')
    return (
        ref
        .where('domains', 'array_contains', primary_domain)
        .where('currentScore', '>=', 0.3)
        .order_by('currentScore', direction='DESCENDING')
        .limit(limit)
        .get()
    )


def retrieve_tier2(db, tenant_id, methods, limit=5):
    """Cross-domain insights via shared methods."""
    if not methods:
        return []
    ref = db.collection(f'tenants/{tenant_id}/memory_items')
    return (
        ref
        .where('methods', 'array_contains_any', methods[:10])
        .where('layer', '==', 'insight')
        .where('currentScore', '>=', 0.5)
        .order_by('currentScore', direction='DESCENDING')
        .limit(limit)
        .get()
    )


def retrieve_tier3(db, tenant_id, agent_id, limit=5):
    """Recent interactions from this agent (last 7 days)."""
    ref = db.collection(f'tenants/{tenant_id}/memory_items')
    cutoff = datetime.now(timezone.utc) - timedelta(days=7)
    return (
        ref
        .where('sourceAgent', '==', agent_id)
        .where('layer', '==', 'interaction')
        .where('createdAt', '>=', cutoff)
        .order_by('createdAt', direction='DESCENDING')
        .limit(limit)
        .get()
    )


# ── Formatting ─────────────────────────────────────────────────────

def format_injection(items_by_tier, primary_domain):
    """Format items for system prompt injection."""
    lines = ['## Active Memory\n']

    # Tier 1: Domain knowledge
    tier1 = items_by_tier.get(1, [])
    if tier1:
        lines.append(f'### Domain Knowledge ({primary_domain})')
        for item in tier1:
            score = f"{item['_composite']:.2f}"
            tags = ', '.join(
                [f"domain:{d}" for d in item.get('domains', [])] +
                [f"method:{m}" for m in item.get('methods', [])]
            )
            age = _format_age(item.get('createdAt'))
            lines.append(f"- [{score}] {item['content']} [{tags}] ({age})")
        lines.append('')

    # Tier 2: Cross-domain insights
    tier2 = items_by_tier.get(2, [])
    if tier2:
        lines.append('### Cross-Domain Insights')
        for item in tier2:
            score = f"{item['_composite']:.2f}"
            tags = ', '.join(
                [f"domain:{d}" for d in item.get('domains', [])] +
                [f"method:{m}" for m in item.get('methods', [])]
            )
            age = _format_age(item.get('createdAt'))
            lines.append(f"- [{score}] {item['content']} [{tags}] ({age})")
        lines.append('')

    # Tier 3: Recent context
    tier3 = items_by_tier.get(3, [])
    if tier3:
        lines.append('### Recent Context')
        for item in tier3:
            ts = _format_timestamp(item.get('createdAt'))
            lines.append(f"- [{ts}] {item['content']}")

    return '\n'.join(lines)


def _format_age(created_at):
    if created_at is None:
        return '?'
    delta = datetime.now(timezone.utc) - created_at
    days = delta.days
    if days == 0:
        return 'today'
    if days < 7:
        return f'{days}d ago'
    return f'{days // 7}w ago'


def _format_timestamp(created_at):
    if created_at is None:
        return '??'
    return created_at.strftime('%m-%d %H:%M')


# ── Main ───────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description='Retrieve agent memory for session startup')
    parser.add_argument('--agent', required=True, help='Agent ID (e.g., trader-agent)')
    parser.add_argument('--domain', required=True, help='Primary domain (e.g., markets-trading)')
    parser.add_argument('--methods', default='', help='Comma-separated method IDs')
    parser.add_argument('--tenant', default='axiom-workspace-5eebd', help='Tenant ID')
    parser.add_argument('--max-items', type=int, default=20, help='Max items to return')
    parser.add_argument('--format', choices=['injection', 'raw', 'json'], default='injection')
    args = parser.parse_args()

    methods = [m.strip() for m in args.methods.split(',') if m.strip()]
    db = _ensure_db()
    now = datetime.now(timezone.utc)

    # Retrieve all tiers
    tier1_docs = retrieve_tier1(db, args.tenant, args.domain)
    tier2_docs = retrieve_tier2(db, args.tenant, methods)
    tier3_docs = retrieve_tier3(db, args.tenant, args.agent)

    # Deduplicate and score
    seen = set()
    items_by_tier = {1: [], 2: [], 3: []}

    for tier_num, docs in [(1, tier1_docs), (2, tier2_docs), (3, tier3_docs)]:
        for doc in docs:
            if doc.id in seen:
                continue
            seen.add(doc.id)
            data = doc.to_dict()
            data['_id'] = doc.id
            data['_composite'] = composite_score(data, [args.domain], methods, now)
            items_by_tier[tier_num].append(data)

    # Sort each tier by composite score
    for tier in items_by_tier.values():
        tier.sort(key=lambda x: x['_composite'], reverse=True)

    # Cap total items
    total = sum(len(v) for v in items_by_tier.values())
    if total > args.max_items:
        # Proportional cap: 60% domain, 25% cross-domain, 15% recent
        items_by_tier[1] = items_by_tier[1][:int(args.max_items * 0.6)]
        items_by_tier[2] = items_by_tier[2][:int(args.max_items * 0.25)]
        items_by_tier[3] = items_by_tier[3][:int(args.max_items * 0.15)]

    if args.format == 'json':
        # Strip non-serializable fields
        output = {}
        for tier, items in items_by_tier.items():
            output[f'tier{tier}'] = [
                {k: v for k, v in item.items() if k != 'createdAt' or v is None}
                for item in items
            ]
        print(json.dumps(output, indent=2, default=str))
    elif args.format == 'raw':
        for tier, items in items_by_tier.items():
            print(f'\n=== Tier {tier} ({len(items)} items) ===')
            for item in items:
                print(f"  [{item['_composite']:.2f}] {item['content']}")
    else:
        print(format_injection(items_by_tier, args.domain))

    # Check if decay is overdue
    state_doc = db.document(f'tenants/{args.tenant}/memory_decay_state/current').get()
    if state_doc.exists:
        data = state_doc.to_dict()
        last_run = data.get('lastRun')
        if last_run:
            hours_since = (now - last_run).total_seconds() / 3600
            if hours_since > 26:
                print(
                    f'\n[WARNING] Decay overdue by {hours_since:.0f}h. '
                    'Run: python -c "from scripts.memory_flush import trigger_decay; trigger_decay()"',
                    file=sys.stderr,
                )


if __name__ == '__main__':
    main()
