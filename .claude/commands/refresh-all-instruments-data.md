---
description: Refresh all instruments' price data from yfinance and update the DB cache
---

This command refreshes OHLCV data for all 11 RITA instruments by fetching delta rows from yfinance.

Steps:
1. Check the server is running: use the Bash tool to run `curl -s http://localhost:8000/health` and confirm it returns ok.
2. Call the refresh endpoint: use the Bash tool to run:
   `curl -s -X POST http://localhost:8000/api/v1/instrument/refresh-all | python -m json.tool`
3. Parse and display the results as a formatted table showing: Instrument | Gap Days | Raw Rows Added | DB Rows Inserted | Status
4. Report the total: "{refreshed} instruments refreshed, {already_current} already current"
5. If any instrument shows status "error", display the error message and suggest re-running.
