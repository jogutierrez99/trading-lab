# ETH Donchian SHORT: operational readiness

Status: **ARCHITECTURE_REVIEW_REQUIRED**. Statistical decision separately remains
PROSPECTIVE_VALIDATION_REQUIRED. No Donchian forward profile or session was created.
No broker connection, orders, Telegram messages or existing session writes occur
in the review CLI. Its imports contain no forward runner or broker operation.

`ForwardConfig` currently admits legacy ETH RSI and RMM protocols and their explicit
strategy allowlists. RMM uses volatility targeting without protective SL/TP;
Donchian uses cost-aware stop-risk sizing with protective SL/TP. Reusing an RMM
profile, identity or shadow ledger would silently change the experiment. The new
research YAML is a preregistration, **not** a runnable ForwardConfig. Changing the
forward allowlist alone is insufficient. Architecture changes are deferred under
the requested scope; RMM, RSI, execution modes and existing order flags are preserved.

Required independent adapter and acceptance tests before observation:

1. Six frozen Donchian variants, ETH 1h only, version1.0.0; no winner selection.
   Separate hypothetical accounts per candidate AND cost scenario, capital10000.
   Immutable session config/code/parameters/feed identity and source hashes.
2. At least1000 confirmed continuous hourly bars, ascending UTC and valid OHLCV.
   Reuse the causal strategy/features; reject unconfirmed candles. After gaps, pause,
   audit/refill genuinely missing candles and rebuild warmup; never invent fills
   across missing data. Every incident goes into an integrity ledger. Degraded
   observation cannot count as validated evidence or silently reset the protocol.
3. Signal at candle close; entry reference is the following candle's actual OPEN,
   available afterward, not its close or the latest ticker. Short execution price
   =reference*(1-slippage-halfspread). A signal evaluated late cannot pretend to
   have entered an already missed open. Record it as missed, with no shadow trade.
4. SL=actual modeled entry+2*ATR known at signal; TP=entry-2*(SL-entry).
   Sizing includes entry and stop-exit fees/slippage/spread; risk budget1% of entry
   equity, position cap25% including entry fee, exposure100%, same quantity filters.
   Entry cap is distinct from later marked exposure. Gap losses can exceed1%.
5. BASE0.05/0.03/0.01% and ADVERSE0.10/0.06/0.02% fee/slippage/fullspread,
   percentage units; exit costs on both sides. Short exit=reference*(1+slippage+
   halfspread). Independent scenario ledgers: costs can change sizing/fills/trades.
   Earliest next-open market exits; gap protections before pending signal exits,
   stop before target when both touched intrabar. Intrabar time is unknown: preserve
   bar-open and timing flag, never invent an exact fill timestamp. End forced
   liquidation only for scheduled evidence snapshot, not arbitrary daily resets.
6. Durable unique key(session,candidate,scenario,symbol,timeframe,signal_close,
   action); transactional position/event persistence, idempotent replay and restart,
   exactly one shadow action per key. Costs, cash and equity must reconcile to the
   unchanged synthetic backend on fixed prerecorded fixtures. Hypothetical PnL must
   remain clearly distinct from exchange fills and account balances.
7. Dedicated `results/forward/eth_donchian_short_1h/` journal/locks/watch state,
   distinct from RMM and RSI. Separate session IDs, restore/recovery tests and
   concurrent-session isolation tests. No imports or calls to POST order paths;
   signal_only, trading_enabled=false, send_orders=false, allow_live_trading=false.
   Tests must prove unsupported mode/true flags fail and network stubs never receive
   order calls. The prospective capital is virtual research capital only.
8. Optional Telegram design: explicitly hypothetical SIGNAL, shadow ENTRY/EXIT
   with candidate/cost/session, data gaps/resumes, duplicate suppression, heartbeat,
   DD breach and session end. No send during implementation; isolated notification
   state and opt-in watcher after adapter acceptance. Never expose credentials.

OKX instrument semantics, public price mapping and feed basis differ from Binance
USD-M. Record contract multiplier, quote currency, instrument provenance, funding
schedule and any divergence; the proposed shadow model still excludes funding,
margin/liquidations/leverage. A real perpetual economic claim needs its own frozen
funding/margin protocol. Existing RMM SIGNAL_ONLY tests do not certify this adapter.

No valid Donchian start or shadow-query command exists yet. `run_forward.py` and
`shadow_pnl.py` exist for supported protocols; passing a fabricated Donchian profile
would not be a safe workaround. Await adapter implementation and specific QA.
