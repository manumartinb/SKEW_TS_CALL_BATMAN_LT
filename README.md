# SKEW_TS_CALL_BATMAN_LT

Semaforo diario del canal SUPERFICIE para Batman LT: term structure del skew de
CALLs SPX (back - front), publicado como percentil expanding asof con zonas
ROJA / NEUTRA / VERDE / TURBO.

- Pagina: https://manumartinb.github.io/SKEW_TS_CALL_BATMAN_LT/
- Senal certificada en backtest Gen 3 (CazaEdge 2026-07-06); en FASE DE
  OBSERVACION LIVE desde 2026-07-07 (sin poder sobre sizing).
- Rol: gate/tilt de sizing day-level. NUNCA sort intradia. El guardian de
  stress (PUT_SKEW / TRIPLE_OR) manda por encima.
- data.json regenerado a diario por update_dashboard.py (invocado por el
  MASTER_DAILY_PIPELINE tras el rebuild del grid de superficie).
- Doc canonico interno: ESTRATEGIAS/SKEW_TS_CALL_RAW_Formula_(Batman).md
