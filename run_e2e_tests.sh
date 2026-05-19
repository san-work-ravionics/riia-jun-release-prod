#!/usr/bin/env bash
# Run all three e2e scenario suites.
# Results are written to test-execution/ during the run, then conftest.py
# moves each file to test-results/e2e/<suite>/<timestamp>-<suite>.xml on completion.
# Must be run from riia-jun-release/ with the API server running on port 8000.
# Each suite runs independently — a failure in one does NOT stop the others.

mkdir -p test-execution

EXIT=0

echo "=== RITA scenarios ==="
pytest tests/e2e/test_rita_scenarios.py --junitxml=test-execution/e2e-rita.xml -v || EXIT=1

echo "=== FnO scenarios ==="
pytest tests/e2e/test_fno_scenarios.py --junitxml=test-execution/e2e-fno.xml -v || EXIT=1

echo "=== Ops scenarios ==="
pytest tests/e2e/test_ops_scenarios.py --junitxml=test-execution/e2e-ops.xml -v || EXIT=1

echo "=== Done. Results archived to test-results/e2e/ ==="
exit $EXIT
