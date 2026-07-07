#!/usr/bin/env python3
# -*- coding: ascii -*-
"""
update_dashboard.py
===================
Genera data.json del dashboard SKEW_TS_CALL_BATMAN_LT y hace push a GitHub Pages.

Lee SKEW_CALL_PCTL_GRID.parquet (regenerado a diario por el Step 2b del
MASTER_DAILY_PIPELINE V2) y publica en
https://manumartinb.github.io/SKEW_TS_CALL_BATMAN_LT/

Metric publicada (serie diaria canonica, basket fijo de los 3 pares DTE
dominantes del universo Batman LT; reproducible solo desde el grid):

    SKEW_TS_DAILY(d) = mean( skew_25d_vs50[d,400] - skew_25d_vs50[d,250],
                             skew_25d_vs50[d,400] - skew_25d_vs50[d,300],
                             skew_25d_vs50[d,400] - skew_25d_vs50[d,200] )
    pct(d) = expanding rank asof (min_periods=250) * 100   [sin lookahead]

Zonas (umbrales calibrados en la CazaEdge venta-cara Gen3 2026-07-06):
    ROJA <= 20 | NEUTRA | VERDE >= 80 | TURBO >= 95

Auth push: remote SSH (git@github.com:manumartinb/SKEW_TS_CALL_BATMAN_LT.git).
Disenado para ser invocado por V2.[PERMA] MASTER_DAILY_PIPELINE.py DESPUES del
Step 2b (rebuild del grid) y gateado a su exito. Exit codes: 0 ok / 1 error.
Doc canonico: ESTRATEGIAS/SKEW_TS_CALL_RAW_Formula_(Batman).md
"""
from __future__ import annotations

import json
import subprocess
import sys
import traceback
from datetime import datetime
from pathlib import Path
from typing import List
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

# ---------------- CONFIG ----------------
SOURCE_PARQUET = Path(
    r"C:\Users\Administrator\Desktop\BULK OPTIONSTRAT\ESTRATEGIAS\Skew\ENRICHED\SKEW_CALL_PCTL_GRID.parquet"
)
DASHBOARD_DIR = Path(
    r"C:\Users\Administrator\Desktop\BULK OPTIONSTRAT\ESTRATEGIAS\Skew\dashboards\SKEW_TS_CALL_BATMAN_LT_DASHBOARD"
)
DATA_JSON = DASHBOARD_DIR / "data.json"

GH_REPO = "manumartinb/SKEW_TS_CALL_BATMAN_LT"
GH_USER_NAME = "manumartinb"
GH_USER_EMAIL = "manuelmartinbarranco@gmail.com"
BRANCH = "main"

TZ = ZoneInfo("Europe/Madrid")

VALUE_COL = "skew_25d_vs50"
BACK_TARGET = 400
FRONT_TARGETS = (250, 300, 200)  # basket fijo (pares dominantes universo LT)
MIN_PERIODS = 250                 # warmup del percentil expanding asof

# Zonas (calibradas CazaEdge Gen3; ver seccion umbrales del Formula doc)
ROJA_MAX = 20.0
VERDE_MIN = 80.0
TURBO_MIN = 95.0


# ---------------- HELPERS ----------------
def zone_label(v: float) -> str:
    if pd.isna(v):
        return "INDETERMINADO"
    if v >= TURBO_MIN:
        return "TURBO"
    if v >= VERDE_MIN:
        return "VERDE"
    if v <= ROJA_MAX:
        return "ROJA"
    return "NEUTRA"


def _round_or_none(v, prec: int = 2):
    if pd.isna(v):
        return None
    return round(float(v), prec)


def build_data_payload() -> dict:
    if not SOURCE_PARQUET.exists():
        raise FileNotFoundError(f"Source parquet not found: {SOURCE_PARQUET}")

    df = pd.read_parquet(SOURCE_PARQUET, columns=["trade_date", "dte_target", VALUE_COL])
    df["trade_date"] = pd.to_datetime(df["trade_date"], errors="coerce").dt.strftime("%Y-%m-%d")
    df["dte_target"] = pd.to_numeric(df["dte_target"], errors="coerce")
    df[VALUE_COL] = pd.to_numeric(df[VALUE_COL], errors="coerce")
    df = df.dropna(subset=["trade_date", "dte_target"])
    df = df.drop_duplicates(["trade_date", "dte_target"], keep="last")

    wide = df.pivot_table(index="trade_date", columns="dte_target",
                          values=VALUE_COL, aggfunc="last").sort_index()
    need = [BACK_TARGET, *FRONT_TARGETS]
    missing = [t for t in need if t not in wide.columns]
    if missing:
        raise RuntimeError(f"dte_targets ausentes en el grid: {missing}")

    diffs = pd.DataFrame({
        f"d{ft}": wide[BACK_TARGET] - wide[ft] for ft in FRONT_TARGETS
    })
    # exigir las 3 diffs no-NaN (dias sin dte=400 se dropean)
    raw = diffs.dropna().mean(axis=1)
    if raw.empty:
        raise RuntimeError("Serie SKEW_TS_DAILY vacia tras dropna")

    pct = raw.expanding(min_periods=MIN_PERIODS).rank(pct=True) * 100.0
    out = pd.DataFrame({"raw": raw, "pct": pct}).dropna(subset=["pct"])
    if out.empty:
        raise RuntimeError(f"Serie sin puntos tras warmup min_periods={MIN_PERIODS}")

    last_date = str(out.index[-1])
    last_pct = float(out["pct"].iloc[-1])
    last_raw = float(out["raw"].iloc[-1])

    return {
        "generated_at": datetime.now(TZ).strftime("%Y-%m-%d %H:%M %Z"),
        "source": SOURCE_PARQUET.name,
        "basket": {
            "back": BACK_TARGET,
            "fronts": list(FRONT_TARGETS),
            "value_col": VALUE_COL,
            "min_periods": MIN_PERIODS,
        },
        "n_days": int(len(out)),
        "thresholds": {"roja_max": ROJA_MAX, "verde_min": VERDE_MIN, "turbo_min": TURBO_MIN},
        "latest": {
            "date": last_date,
            "pct": round(last_pct, 2),
            "raw": _round_or_none(last_raw, 6),
            "zone": zone_label(last_pct),
        },
        "dates": out.index.tolist(),
        "pct": [_round_or_none(v) for v in out["pct"]],
        "raw": [_round_or_none(v, 6) for v in out["raw"]],
    }


def _payload_data_changed(new_payload: dict) -> bool:
    if not DATA_JSON.exists():
        return True
    try:
        old = json.loads(DATA_JSON.read_text(encoding="utf-8"))
    except Exception:
        return True
    keys_to_compare = ("dates", "pct", "raw", "latest", "n_days")
    for k in keys_to_compare:
        if old.get(k) != new_payload.get(k):
            return True
    return False


def write_data_json(payload: dict) -> None:
    DATA_JSON.write_text(
        json.dumps(payload, separators=(",", ":"), ensure_ascii=False),
        encoding="utf-8",
    )


def _git(args: List[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(DASHBOARD_DIR), *args],
        capture_output=True,
        text=True,
        check=False,
    )


def push_to_github() -> int:
    # GUARD (leccion 2026-07-07): si esta carpeta no es su PROPIO repo git,
    # los comandos `git -C` caerian al repo padre ESTRATEGIAS (gigante) y
    # `add -A` lo stagearia entero. Nunca operar sin .git local.
    if not (DASHBOARD_DIR / ".git").exists():
        print(f"[X] {DASHBOARD_DIR} no es un repo git propio (falta .git); push abortado")
        return 1
    _git(["config", "user.name", GH_USER_NAME])
    _git(["config", "user.email", GH_USER_EMAIL])
    _git(["add", "-A"])

    status = _git(["status", "--porcelain"])
    if not status.stdout.strip():
        print("[INFO] no changes to commit, nothing to push")
        return 0

    today = datetime.now(TZ).strftime("%Y-%m-%d %H:%M")
    commit = _git(["commit", "-m", f"daily update {today}"])
    if commit.returncode != 0:
        print(f"[X] commit failed: {commit.stderr.strip()}")
        return 1

    push = subprocess.run(
        ["git", "-C", str(DASHBOARD_DIR), "push", "origin", BRANCH],
        capture_output=True,
        text=True,
    )
    if push.returncode != 0:
        print(f"[X] push failed: {push.stderr.strip()}")
        return 1

    print("[OK] pushed to https://manumartinb.github.io/SKEW_TS_CALL_BATMAN_LT/")
    return 0


# ---------------- MAIN ----------------
def main() -> int:
    try:
        if not DASHBOARD_DIR.exists():
            print(f"[X] dashboard dir not found: {DASHBOARD_DIR}")
            return 1

        payload = build_data_payload()
        changed = _payload_data_changed(payload)
        write_data_json(payload)

        latest = payload["latest"]
        print(
            f"[INFO] data.json {'updated' if changed else 'identical (timestamp refreshed)'} | "
            f"latest_date={latest['date']} pct={latest['pct']:.1f} raw={latest['raw']} zone={latest['zone']} | "
            f"n_days={payload['n_days']}"
        )

        if not changed:
            return 0

        return push_to_github()

    except Exception as exc:
        print(f"[X] update_dashboard failed: {exc}")
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
