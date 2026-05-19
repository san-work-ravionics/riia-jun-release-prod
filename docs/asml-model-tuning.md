# ASML Model — Sharpe Analysis & Tuning Recommendations

---

## Run 2 — current baseline (2026-04-23)

Fixes applied: price-invariant ATR/MACD normalisation + timesteps 200k → 300k.

| Metric | Value |
|---|---|
| Timesteps | 300,000 |
| Total Return | 57.8% |
| CAGR | 117.9% |
| Sharpe Ratio | **2.95** |
| Max Drawdown | **-6.1%** |
| Win Rate | 35.6% |

The model **significantly outperforms** the passive buy-and-hold benchmark (Run 1 B&H Sharpe ~1.30).
MDD improved from -50.76% → -6.1%, confirming the agent now detects and responds to elevated volatility.
Low win rate (35.6%) is expected for a trend-following RL agent — winning trades are larger in magnitude.

---

## Run 1 — original baseline (2026-04-16)

| Metric | Value |
|---|---|
| Timesteps | 50,000 |
| Validation Sharpe | 0.936 |
| Validation MDD | -50.76% |
| Validation period | 2021-05-14 → 2026-04-02 |
| Val buy-and-hold Sharpe (naive) | ~1.30 |

The model **underperformed passive buy-and-hold** in the validation period.

---

## Root cause 1 — Observation normalisation collapse (most critical)

ASML's price went from $0.06 → $207 across the full dataset (a **3,450x** move).
ATR and MACD are absolute-price quantities. The normalisation constants are computed
once on training data (2001–2021) and then frozen:

| Feature | Train value | Val value | Ratio | Effect in validation |
|---|---|---|---|---|
| `atr_mean` (train) | 0.066 | 3.000 (mean) | **45x** | `atr_14/atr_mean` clips at `3.0` for the entire val period — **constant signal** |
| `macd_std` (train) | 0.098 | 2.531 (std) | **26x** | Clip boundary = 0.294; val MACD max = 9.77 — **mostly clipped at ±3** |

The observation space bounds are `[-3.0, 3.0]`. In validation, the ATR and MACD features
are **always at their ceiling**. The agent receives no volatility or momentum signal —
just noise at the boundary.

RSI, `bb_pct_b`, `daily_return`, and `ema_ratio` are percentage/ratio-based and are unaffected.

---

## Root cause 2 — Insufficient timesteps

50,000 timesteps over a 4,900-row training set with 252-day episodes gives roughly
**198 episodes**. That is barely enough to explore the action space, let alone converge
on a policy. The recommended minimum for ASML is 300,000.

---

## Root cause 3 — Extreme validation regime with saturated observations

| Year | Return |
|---|---|
| 2021 | +106% |
| 2022 | -51% |
| 2023 | +246% |
| 2024 | +179% |
| 2025 | +35% |
| 2026 | -6% (partial) |

The -51% in 2022 drives the -50.76% MDD. Because ATR was saturated at the observation
ceiling throughout 2022, the agent had no way to detect elevated volatility and reduce
allocation defensively.

---

## Recommendations

### Fix 1 — Make ATR and MACD price-scale invariant (highest impact)

Replace absolute normalisation with percentage-of-price equivalents in
`RIIATradingEnv._get_obs()` and `run_episode()` in `trading_env.py`:

```python
# BEFORE — breaks as price grows
float(np.clip(row["atr_14"] / self._atr_mean, 0, 3))

# AFTER — stable across all price levels
float(np.clip(row["atr_14"] / row["Close"] * 100, 0, 3))  # ATR as % of price
```

```python
# BEFORE
float(np.clip(row["macd"] / (self._macd_std * 3), -3, 3))

# AFTER
float(np.clip((row["macd"] / row["Close"]) * 1000, -3, 3))  # MACD in bps of price
```

> This change applies to all 4 instruments. QA must validate observation distributions
> for NIFTY and BANKNIFTY before committing (they have smaller price ranges, so the
> impact is less severe but the fix is still correct).

### Fix 2 — Rolling normalisation (alternative / complementary to Fix 1)

Instead of computing `atr_mean` and `macd_std` once at env init, use a rolling
252-day window so normalisation adapts as price levels change:

```python
self._atr_mean_series  = df["atr_14"].rolling(252).mean().bfill()
self._macd_std_series  = df["macd"].rolling(252).std().bfill()
```

Access per-row at step time instead of using scalar constants.

### Fix 3 — Increase timesteps

Update `config/instruments/asml.yaml`:

```yaml
training:
  timesteps: 300000   # was 200000; actual run used only 50k — both are insufficient
```

### Fix 4 — Trim training window to 2010+

The 2001–2009 period (ASML at $0.06–$0.50) is so different from the current
$100–$200 regime that those rows add noise even after the normalisation fixes.
A `start_year: 2010` filter in the instrument config (honoured by the data loader)
would cut training rows from ~4,900 → ~2,900 while improving regime relevance.

```yaml
# config/instruments/asml.yaml
data:
  start_year: 2010
```

---

## Fix status

| Priority | Action | File | Status |
|---|---|---|---|
| 1 | Replace `atr_14/atr_mean` with `atr_14/Close*100` | `trading_env.py` | ✅ Done (2026-04-23) |
| 1 | Replace `macd/(macd_std*3)` with `(macd/Close)*1000` | `trading_env.py` | ✅ Done (2026-04-23) |
| 2 | Set `timesteps: 300000` | `config/instruments/asml.yaml` | ✅ Done (2026-04-23) |
| 3 | Add `start_year: 2010` filter | `asml.yaml` + `data_loader.py` | ⏳ Deferred — not needed given Run 2 results |

---

## Next retune triggers

Retune when any of the following occur:
- New EUV generation ships (order cycle regime shift)
- Sharpe drops below 1.5 over a rolling 6-month window
- MDD exceeds -15% in live operation
- New data extends beyond 2026 (recheck normalisation ranges)
