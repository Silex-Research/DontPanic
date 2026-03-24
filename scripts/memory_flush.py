#!/usr/bin/env python3
"""
memory_flush.py — Parse memory extractions from agent session output and write to Firestore.

Called at session end or from agent heartbeat REPORT step.
Reuses AxiomWriter's Firestore client — no new writer needed.

Usage:
    # Parse extractions from a file
    python scripts/memory_flush.py --agent trader-agent --session-file /tmp/session_output.txt

    # Parse from stdin (pipe agent output)
    echo "<memory_extract>...</memory_extract>" | python scripts/memory_flush.py --agent trader-agent

    # Write a single item directly
    python scripts/memory_flush.py --agent trader-agent --direct \
        --content "0DTE put credit spreads best 10-11:30 ET when VIX 14-18" \
        --layer domain --domains markets-trading --methods temporal-analysis \
        --category fact --confidence 0.8

    # Trigger decay check
    python scripts/memory_flush.py --check-decay
"""

import argparse
import hashlib
import json
import os
import re
import sys
from datetime import datetime, timezone

from scripts.firestore_writer import _ensure_db

from google.cloud.firestore_v1 import SERVER_TIMESTAMP


# ── Extraction Parser ──────────────────────────────────────────────

EXTRACT_PATTERN = re.compile(
    r'<memory_extract>(.*?)</memory_extract>',
    re.DOTALL
)

FIELD_PATTERN = re.compile(r'^(\w+):\s*(.+)$', re.MULTILINE)


def parse_extractions(text: str) -> list[dict]:
    """Parse <memory_extract> blocks from agent output."""
    items = []
    for match in EXTRACT_PATTERN.finditer(text):
        block = match.group(1).strip()
        fields = {}
        for field_match in FIELD_PATTERN.finditer(block):
            key = field_match.group(1).strip()
            value = field_match.group(2).strip()
            fields[key] = value

        if 'content' not in fields:
            continue

        # Parse list fields
        domains = [d.strip() for d in fields.get('domains', '').split(',') if d.strip()]
        methods = [m.strip() for m in fields.get('methods', '').split(',') if m.strip()]

        try:
            confidence = float(fields.get('confidence', '0.5'))
        except ValueError:
            confidence = 0.5

        items.append({
            'content': fields['content'][:500],
            'layer': fields.get('layer', 'domain'),
            'domains': domains or ['meta-cognition'],
            'methods': methods or ['first-principles'],
            'category': fields.get('category', 'fact'),
            'confidence': min(1.0, max(0.0, confidence)),
        })

    return items


# ── Score Calculation ──────────────────────────────────────────────

LAYER_TTL_DAYS = {
    'insight': None,
    'domain': 180,
    'interaction': 30,
}


def calculate_base_score(item: dict) -> float:
    """Mirror the Cloud Function scoring logic."""
    score = 0.5
    if item['layer'] == 'insight':
        score += 0.3
    elif item['layer'] == 'domain':
        score += 0.15
    if len(item.get('domains', [])) > 1:
        score += 0.1
    if len(item.get('methods', [])) > 1:
        score += 0.05
    score *= item.get('confidence', 0.5)
    return min(1.0, max(0.0, score))


def content_hash(content: str) -> str:
    """SHA-256 hash for dedup."""
    return hashlib.sha256(content.strip().lower().encode()).hexdigest()


# ── Write to Firestore ─────────────────────────────────────────────

def write_memory_item(db, tenant_id: str, agent_id: str, session_id: str, item: dict) -> dict:
    """Write a single memory item, handling dedup."""
    ref = db.collection(f'tenants/{tenant_id}/memory_items')
    c_hash = content_hash(item['content'])

    # Dedup check
    existing = ref.where('contentHash', '==', c_hash).limit(1).get()
    if existing:
        doc = existing[0]
        doc.reference.update({
            'accessCount': doc.to_dict().get('accessCount', 0) + 1,
            'lastAccessed': SERVER_TIMESTAMP,
        })
        return {'action': 'dedup_bumped', 'id': doc.id}

    base_score = calculate_base_score(item)
    ttl_days = LAYER_TTL_DAYS.get(item['layer'])
    expires_at = None
    if ttl_days:
        from datetime import timedelta
        expires_at = datetime.now(timezone.utc) + timedelta(days=ttl_days)

    doc_data = {
        'content': item['content'].strip(),
        'contentHash': c_hash,
        'layer': item['layer'],
        'domains': item['domains'],
        'methods': item['methods'],
        'category': item['category'],
        'sourceAgent': agent_id,
        'sourceSession': session_id,
        'baseScore': base_score,
        'currentScore': base_score,
        'confidence': item['confidence'],
        'accessCount': 0,
        'lastAccessed': None,
        'createdAt': SERVER_TIMESTAMP,
        'expiresAt': expires_at,
        'supersededBy': None,
    }

    _, doc_ref = ref.add(doc_data)
    return {'action': 'created', 'id': doc_ref.id, 'baseScore': base_score}


# ── Session Log ────────────────────────────────────────────────────

def write_session_log(agent_id: str, session_id: str, items: list[dict], results: list[dict]):
    """Write session summary to memory/agents/{agent}/sessions/."""
    session_dir = f'memory/agents/{agent_id}/sessions'
    os.makedirs(session_dir, exist_ok=True)

    timestamp = datetime.now().strftime('%Y-%m-%d-%H%M')
    filename = f'{session_dir}/{timestamp}.md'

    lines = [
        f'# Session {session_id}',
        f'Date: {datetime.now().strftime("%Y-%m-%d %H:%M")}',
        f'Agent: {agent_id}',
        f'Items extracted: {len(items)}',
        '',
    ]

    for item, result in zip(items, results):
        status = result.get('action', 'unknown')
        lines.append(f'- [{status}] ({item["layer"]}) {item["content"][:80]}')

    with open(filename, 'w') as f:
        f.write('\n'.join(lines) + '\n')

    return filename


# ── Decay Check ────────────────────────────────────────────────────

def trigger_decay(tenant_id: str = '<axiom-firebase-project-id>'):
    """Check if decay is overdue and print warning."""
    db = _ensure_db()
    doc = db.document(f'tenants/{tenant_id}/memory_decay_state/current').get()

    if not doc.exists:
        print('[INFO] No decay state found — decay has never run.')
        print('       Deploy Cloud Functions and wait for scheduled run, or trigger manually.')
        return

    data = doc.to_dict()
    last_run = data.get('lastRun')
    if last_run:
        hours = (datetime.now(timezone.utc) - last_run).total_seconds() / 3600
        print(f'[INFO] Last decay: {last_run.isoformat()} ({hours:.1f}h ago)')
        if hours > 26:
            print('[WARNING] Decay is overdue. Trigger via Cloud Function endpoint.')
    else:
        print('[INFO] Decay state exists but lastRun is null.')


# ── Main ───────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description='Flush agent memory extractions to Firestore')
    parser.add_argument('--agent', help='Agent ID (e.g., trader-agent)')
    parser.add_argument('--tenant', default='<axiom-firebase-project-id>', help='Tenant ID')
    parser.add_argument('--session-file', help='Path to session output file')
    parser.add_argument('--session-id', help='Session identifier')
    parser.add_argument('--check-decay', action='store_true', help='Check if decay is overdue')

    # Direct write mode
    parser.add_argument('--direct', action='store_true', help='Write a single item directly')
    parser.add_argument('--content', help='Memory content (direct mode)')
    parser.add_argument('--layer', default='domain', help='Memory layer')
    parser.add_argument('--domains', default='', help='Comma-separated domain IDs')
    parser.add_argument('--methods', default='', help='Comma-separated method IDs')
    parser.add_argument('--category', default='fact', help='Memory category')
    parser.add_argument('--confidence', type=float, default=0.7, help='Confidence 0.0-1.0')

    args = parser.parse_args()

    if args.check_decay:
        trigger_decay(args.tenant)
        return

    if not args.agent:
        parser.error('--agent is required unless using --check-decay')

    session_id = args.session_id or datetime.now().strftime('%Y%m%d-%H%M%S')
    db = _ensure_db()

    if args.direct:
        # Direct write mode
        if not args.content:
            parser.error('--content is required in direct mode')

        domains = [d.strip() for d in args.domains.split(',') if d.strip()]
        methods = [m.strip() for m in args.methods.split(',') if m.strip()]

        item = {
            'content': args.content[:500],
            'layer': args.layer,
            'domains': domains or ['meta-cognition'],
            'methods': methods or ['first-principles'],
            'category': args.category,
            'confidence': args.confidence,
        }

        result = write_memory_item(db, args.tenant, args.agent, session_id, item)
        print(f'[{result["action"]}] {result.get("id", "?")}')
        if result.get('baseScore'):
            print(f'  Score: {result["baseScore"]:.2f}')
        return

    # Parse mode: read from file or stdin
    if args.session_file:
        with open(args.session_file) as f:
            text = f.read()
    else:
        text = sys.stdin.read()

    items = parse_extractions(text)

    if not items:
        print('[INFO] No <memory_extract> blocks found in input.')
        return

    print(f'[INFO] Found {len(items)} memory extractions')

    results = []
    for item in items:
        result = write_memory_item(db, args.tenant, args.agent, session_id, item)
        results.append(result)
        print(f'  [{result["action"]}] {item["content"][:60]}...')

    # Write session log
    log_file = write_session_log(args.agent, session_id, items, results)
    print(f'\n[INFO] Session log: {log_file}')

    # Clear working memory
    db.document(f'tenants/{args.tenant}/memory_working/{args.agent}').delete()
    print(f'[INFO] Cleared working memory for {args.agent}')


if __name__ == '__main__':
    main()
