Ops

1. Test results are overwriting existing test results
2. Draft data still shows till 31 Dec

1. Docker check


 pytest tests/unit/ --junitxml=test-results/unit/latest.xml
 
 pytest tests/e2e/test_rita_scenarios.py --junitxml=test-results/e2e/rita/latest.xml -v
 pytest tests/e2e/test_fno_scenarios.py  --junitxml=test-results/e2e/fno/latest.xml  -v
 pytest tests/unit/        --junitxml=test-results/unit/latest.xml        -v
 pytest tests/integration/ --junitxml=test-results/integration/latest.xml -v
 
  pytest tests/unit/ --junitxml=test-execution/unit.xml
  