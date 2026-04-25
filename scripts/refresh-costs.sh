#!/bin/bash
set -euo pipefail

# refresh-costs.sh — Queries BigQuery billing data and writes state/costs.json
# Run manually or via cron to keep the Cloud Costs dashboard current.
#
# Requires: bq CLI authenticated with access to silexr-billing project
# Usage: ./scripts/refresh-costs.sh

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
JARVIS_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
STATE_FILE="$JARVIS_DIR/dashboard/state/costs.json"
TMP_DIR=$(mktemp -d)
trap 'rm -rf "$TMP_DIR"' EXIT

echo "Fetching billing data from BigQuery..."

# Wildcard scans pick up any new billing-export tables automatically.
# When a new billing account (e.g. Jarvis 01EA42-C7164E-236F6E) configures
# its export to silexr-billing.billing_export, the new table appears as
# gcp_billing_export_v1_* and is included in these queries with no code change.

# ── Query 1: Totals by app (this month) ──
bq query --project_id=silexr-billing --use_legacy_sql=false --format=json --quiet \
"WITH all_costs AS (
  SELECT project.id AS project, cost,
    IFNULL((SELECT SUM(c.amount) FROM UNNEST(credits) c), 0) AS credit
  FROM \`silexr-billing.billing_export.gcp_billing_export_v1_*\`
  WHERE invoice.month = FORMAT_DATE('%Y%m', CURRENT_DATE())
  UNION ALL
  SELECT project.id AS project, cost,
    IFNULL((SELECT SUM(c.amount) FROM UNNEST(credits) c), 0) AS credit
  FROM \`<spindine-dev-firebase-project-id>.billing_export.gcp_billing_export_v1_*\`
  WHERE invoice.month = FORMAT_DATE('%Y%m', CURRENT_DATE())
)
SELECT
  CASE
    WHEN project LIKE 'glam%' THEN 'Styln'
    WHEN project IN ('<spindine-dev-firebase-project-id>', '<spindine-prod-firebase-project-id>') THEN 'Spin & Dine'
    WHEN project LIKE 'quantre%' OR project LIKE 'axiom%'
      OR project LIKE 'cosmic%' OR project LIKE 're-investor%' THEN 'QuantRE/Axiom'
    WHEN project IN ('<firebase-project-id>', 'jarvis-dashboard-silex') THEN 'Jarvis'
    WHEN project = 'silexr-billing' THEN 'Admin'
    ELSE project
  END AS app,
  project,
  ROUND(SUM(cost), 2) AS cost,
  ROUND(SUM(credit), 2) AS credits,
  ROUND(SUM(cost) + SUM(credit), 2) AS net_cost
FROM all_costs
GROUP BY 1, 2
ORDER BY net_cost DESC" > "$TMP_DIR/breakdown.json" 2>/dev/null

# ── Query 2: Monthly trend (last 6 months) ──
bq query --project_id=silexr-billing --use_legacy_sql=false --format=json --quiet \
"WITH combined AS (
  SELECT invoice.month AS inv_month, project.id AS project, cost
  FROM \`silexr-billing.billing_export.gcp_billing_export_v1_*\`
  WHERE invoice.month >= FORMAT_DATE('%Y%m', DATE_SUB(CURRENT_DATE(), INTERVAL 6 MONTH))
  UNION ALL
  SELECT invoice.month AS inv_month, project.id AS project, cost
  FROM \`<spindine-dev-firebase-project-id>.billing_export.gcp_billing_export_v1_*\`
  WHERE invoice.month >= FORMAT_DATE('%Y%m', DATE_SUB(CURRENT_DATE(), INTERVAL 6 MONTH))
)
SELECT
  inv_month AS month,
  CASE
    WHEN project LIKE 'glam%' THEN 'Styln'
    WHEN project IN ('<spindine-dev-firebase-project-id>', '<spindine-prod-firebase-project-id>') THEN 'Spin & Dine'
    WHEN project LIKE 'quantre%' OR project LIKE 'axiom%'
      OR project LIKE 'cosmic%' OR project LIKE 're-investor%' THEN 'QuantRE/Axiom'
    WHEN project IN ('<firebase-project-id>', 'jarvis-dashboard-silex') THEN 'Jarvis'
    WHEN project = 'silexr-billing' THEN 'Admin'
    ELSE project
  END AS app,
  ROUND(SUM(cost), 2) AS cost
FROM combined
GROUP BY 1, 2
ORDER BY 1 DESC, cost DESC" > "$TMP_DIR/trend.json" 2>/dev/null

echo "Building costs.json..."

# ── Assemble into state/costs.json using jq ──
jq -n \
  --arg generated "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
  --slurpfile breakdown "$TMP_DIR/breakdown.json" \
  --slurpfile trend "$TMP_DIR/trend.json" \
'
# Compute totals from breakdown
($breakdown[0] // []) as $rows |
{
  generated: $generated,
  totals: (
    ($rows | map(select(.app == "Styln")) | map(.net_cost | tonumber) | add // 0) as $styln |
    ($rows | map(select(.app == "Spin & Dine")) | map(.net_cost | tonumber) | add // 0) as $sd |
    ($rows | map(select(.app == "QuantRE/Axiom")) | map(.net_cost | tonumber) | add // 0) as $qr |
    ($rows | map(select(.app == "Jarvis")) | map(.net_cost | tonumber) | add // 0) as $jv |
    {
      "Styln": ($styln * 100 | round / 100),
      "Spin & Dine": ($sd * 100 | round / 100),
      "QuantRE/Axiom": ($qr * 100 | round / 100),
      "Jarvis": ($jv * 100 | round / 100),
      "Total": (($styln + $sd + $qr + $jv) * 100 | round / 100)
    }
  ),
  breakdown: [
    ($breakdown[0] // [])[] |
    select(.app != "Admin") |
    {
      app: .app,
      project: .project,
      service: (.service // "General"),
      cost: (.cost | tonumber),
      credits: (.credits | tonumber),
      netCost: (.net_cost | tonumber)
    }
  ],
  trend: ($trend[0] // []) | [
    group_by(.month)[] |
    (.[0].month) as $m |
    {
      month: $m,
      Styln: ([.[] | select(.app == "Styln") | .cost | tonumber] | add // 0),
      "Spin & Dine": ([.[] | select(.app == "Spin & Dine") | .cost | tonumber] | add // 0),
      "QuantRE/Axiom": ([.[] | select(.app == "QuantRE/Axiom") | .cost | tonumber] | add // 0),
      Jarvis: ([.[] | select(.app == "Jarvis") | .cost | tonumber] | add // 0),
      total: ([.[] | select(.app != "Admin") | .cost | tonumber] | add // 0)
    }
  ] | sort_by(.month)
}
' > "$STATE_FILE"

echo "Written to $STATE_FILE"
echo "Totals:"
jq '.totals' "$STATE_FILE"
