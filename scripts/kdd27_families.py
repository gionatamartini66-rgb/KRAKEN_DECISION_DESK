"""KDD-27 — independent source-family adapters over the existing KDD producers.

All frequencies here are UNAPPROVED G0 experimental candidates. Importing or
configuring the registry never installs Android jobs. Coverage, TTL and
producer budgets remain separate: a prior sample can be historical, not fresh.
No adapter buys, sells, sends an order or publishes a GPT dossier.
"""
from __future__ import annotations
import datetime as dt
import time
from collections import OrderedDict

UTC = dt.timezone.utc
# name, seconds profile A, seconds B, consumer TTL, max producer calls,
# source dependencies. This is NOT an exchange/provider rate-limit assertion.
_FAMILIES = (
 ("wallet_spot",3600,1800,1800,1,()),
 ("market_catalog",3600,1800,1800,2,()),
 ("scanner",21600,10800,3600,24,("market_catalog",)),
 ("portfolio_4tf",21600,10800,7200,80,("market_catalog","wallet_spot")),
 ("spot_book",7200,3600,300,4,("scanner",)),
 ("spot_trades",7200,3600,300,4,("scanner",)),
 ("binance_spot",7200,3600,900,6,("market_catalog","wallet_spot")),
 ("futures_public",7200,3600,900,2,()),
 ("fundamentals",43200,21600,86400,9,("market_catalog","wallet_spot","portfolio_4tf")),
 ("primary_events",43200,21600,86400,8,("fundamentals",)),
 ("network_defi",43200,21600,86400,15,("wallet_spot",)),
 ("macro_context",43200,21600,86400,1,()),
 ("decision_review",21600,10800,86400,8,()),
)
SPECS = OrderedDict((name,dict(
    name=name,intervals={"A":a,"B":b},ttl_s=ttl,
    producer_budget_calls=calls,dependencies=dependencies,
    approved=False,
)) for name,a,b,ttl,calls,dependencies in _FAMILIES)


class MissingSource(RuntimeError):
    """Required source absent/stale; never fabricate a zero observation."""


class ProducerBudget(RuntimeError):
    """Actual per-family request ceiling. This is not a provider quota."""


def stamped(value):
    try:
        t=dt.datetime.fromisoformat(value)
        if t.tzinfo is None:
            return None
        return t.astimezone(UTC)
    except (ValueError, TypeError, OverflowError):
        return None


def source(store, family, now, *, require_fresh=True):
    if family not in SPECS:
        raise ValueError("Unknown family")
    previous=store.latest(family)
    if previous is None:
        raise MissingSource("FONTE_ASSENTE:"+family)
    observed=stamped(previous["observed_at"])
    age=(now-observed).total_seconds() if observed is not None else float("inf")
    if age < -120 or (require_fresh and age > SPECS[family]["ttl_s"]):
        raise MissingSource("FONTE_SCADUTA:"+family)
    if previous.get("state") not in (None,"OSSERVATO"):
        raise MissingSource("FONTE_NON_OSSERVATA:"+family)
    return previous["payload"]


class BoundCalls:
    """Counts calls regardless of response, and stops before exceeding the G0 ceiling."""
    def __init__(self, supplier, ceiling):
        self.supplier=supplier
        self.ceiling=ceiling
        self.calls=0
    def __call__(self,*args,**kwargs):
        if self.calls >= self.ceiling:
            raise ProducerBudget("FAMILY_CALL_CEILING")
        self.calls+=1
        return self.supplier(*args,**kwargs)


def _clock(now):
    return now.astimezone(UTC)


def collect(store, family, now=None, *, overrides=None):
    """Real source producer; accepts bounded in-memory fixture hooks in CI.

    Missing dependencies produce explicit NON_ACQUISITO records with zero API
    calls. Reuse from SQLite is verified at the time of consumption.
    """
    if family not in SPECS:
        raise ValueError("Unknown source family")
    now = _clock(now or dt.datetime.now(UTC))
    overrides=overrides or {}
    import decision_desk as desk
    import mercati_spot as multi
    spec=SPECS[family]
    deps={}
    try:
        for dep in spec["dependencies"]:
            deps[dep]=source(store,dep,now)
    except MissingSource as exc:
        return {"state":"NON_ACQUISITO", "observed_at":now.isoformat(),
                "payload":{"stato":"NON_ACQUISITO","motivo":str(exc),
                           "family":family,"osservato_utc":None},
                "metrics":{"source_calls":0,"max_calls":spec["producer_budget_calls"],
                           "missing_dependency":str(exc)},
                "cursor":None}
    count=BoundCalls(overrides.get("kraken",desk.kraken),spec["producer_budget_calls"])
    result={}
    cursor=None
    if family=="wallet_spot":
        status=(overrides["saldo"]() if "saldo" in overrides
                else desk.aggiorna_saldo_sola_lettura())
        wallet=desk.load("portafoglio.json",{"posizioni":[]})
        result={"saldo_refresh":status,"wallet":wallet,
                "wallet_sha256":desk.fotografia_portafoglio_sha256(wallet)}
        if status.get("stato") != "RIUSCITO":
            result["stato"]="NON_DISPONIBILE"
    elif family=="market_catalog":
        pairs=count("AssetPairs")
        tickers=count("Ticker")
        if not isinstance(pairs,dict) or not isinstance(tickers,dict):
            raise ValueError("Invalid Kraken catalog/ticker")
        result={"pairs":pairs,"tickers":tickers}
    elif family=="scanner":
        import ricerca_setup
        catalog=deps["market_catalog"]
        conf=desk.load("config.json",{}).get("scanner",{})
        markets,rates=multi.assemble(catalog["pairs"],catalog["tickers"],
           min_vol=desk.num(conf.get("volume_24h_min_eur",500000)),
           max_spread=desk.num(conf.get("spread_massimo_pct",0.8)))
        old=store.latest("scanner")
        previous=(old["payload"].get("ricerca") if old else None)
        chosen,report,_=ricerca_setup.scan(markets,conf,count,now.timestamp(),
                                  max_requests=spec["producer_budget_calls"],
                                  previous=previous)
        result={"shortlist":chosen,"ricerca":report,
                "copertura":report.get("copertura_progressiva_pct"),
                "universo_ammissibile":report.get("universo_ammissibile")}
        cursor=report
    elif family=="portfolio_4tf":
        import patrimonio_4tf
        catalog=deps["market_catalog"]
        portfolio=deps["wallet_spot"]["wallet"]
        result=patrimonio_4tf.collect(
            portfolio, {"rilevazione_utc":now.isoformat()},
            asset_pairs=catalog["pairs"],fetch=count,
            now=now,max_queries=spec["producer_budget_calls"])
    elif family in ("spot_book","spot_trades"):
        rows=(deps["scanner"].get("shortlist") or [])[:4]
        observations=[]
        if family=="spot_trades":
            import flusso_spot
            for row in rows:
                if not row.get("pair") or not row.get("pair_key"):
                    continue
                if count.calls>=count.ceiling:
                    break
                outcome=flusso_spot.fetch(row["pair"],row["pair_key"],
                                          now=now.timestamp(),fetcher=count)
                observations.append(outcome)
        else:
            for row in rows:
                if not row.get("pair_key") or not row.get("pair"):
                    continue
                try:
                    raw=count("Depth",pair=row["pair_key"],count=10)
                    observations.append({"pair":row["pair"],"data":raw,
                                         "stato":"OSSERVATO"})
                except (OSError,ValueError,RuntimeError,TypeError) as exc:
                    observations.append({"pair":row["pair"],"stato":"NON_DISPONIBILE",
                                         "motivo":type(exc).__name__})
        result={"coppie":observations,"campione_scanner":len(rows),
                "copertura":len(observations)}
    elif family=="binance_spot":
        import binance_reference
        cat=deps["market_catalog"]
        wallet=deps["wallet_spot"]["wallet"]
        tokens=sorted({row["token"] for row in wallet.get("posizioni",[])
                       if isinstance(row,dict) and isinstance(row.get("token"),str)})
        result=binance_reference.collect(tokens,cat["pairs"],cat["tickers"],
                                         shortlist=())
        # Provider function has its own bounded 2-call default here (no shortlist).
        count.calls=2 if result.get("status")!="NO_PAIR" else 1
    elif family=="futures_public":
        import kdd_futures_flow
        result=kdd_futures_flow.collect(now,request=(
            overrides.get("futures_request",desk.request)))
        count.calls=2
    elif family=="fundamentals":
        import dossier_trade
        cat=deps["market_catalog"]
        wallet=deps["wallet_spot"]["wallet"]
        four=deps["portfolio_4tf"]
        prev=store.latest("fundamentals")
        prior=prev["payload"] if prev else None
        previous_scanner=store.latest("scanner")
        scan=previous_scanner["payload"].get("shortlist",[]) if previous_scanner else []
        candidates=[{"token":row.get("token"),"coppia_analisi":row.get("pair"),
                     "kraken_pair_key":row.get("pair_key")} for row in scan[:4]]
        result=dossier_trade.economic_evidence(
            {"rilevazione_utc":now.isoformat(),"feed":[]},wallet,four,candidates,
            now,asset_pairs=cat["pairs"],previous=prior)
        count.calls=result.get("richieste_effettuate",0)
        if count.calls>count.ceiling:
            raise ProducerBudget("ECONOMICS_BUDGET_DISCORDANTE")
        cursor={k:result.get(k) for k in (
            "prossimo_token_identita","prossimo_id_fondamentali",
            "prossimo_id_batch_fondamentali","prossimo_repository_release")}
    elif family=="primary_events":
        import kdd_economic_sources
        items=deps["fundamentals"]
        old=store.latest("primary_events")
        previous=old["payload"] if old else None
        http=overrides.get("public_fetch",lambda url:desk.request(url,timeout=10))
        result=kdd_economic_sources.collect(
           now,items,previous,http,network_allowed=True,
           rpc_fetch=overrides.get("rpc_fetch"),collect_project_issues=True,
           collect_kraken_status=True)
        count.calls=result.get("richieste_effettuate",0)
        if count.calls>count.ceiling:
            raise ProducerBudget("PRIMARY_BUDGET_DISCORDANTE")
        cursor=result.get("cursori")
    elif family=="network_defi":
        import kdd_network_defi
        wallet=deps["wallet_spot"]["wallet"]
        owned=[{"token":row.get("token")} for row in wallet.get("posizioni",[])
               if isinstance(row,dict)]
        previous=store.latest("network_defi")
        prior=previous["payload"] if previous else None
        econ=store.latest("fundamentals")
        economic=econ["payload"] if econ else None
        scan=store.latest("scanner")
        candidates=[{"token":row.get("token"),"coppia_analisi":row.get("pair")}
                    for row in (scan["payload"].get("shortlist",[]) if scan else [])]
        result=kdd_network_defi.collect(
            now,owned,candidates,fetch=overrides.get("onchain_fetch"),
            economics=economic,previous=prior)
        count.calls=(result.get("asset_reti") or {}).get(
                    "flussi_capitale",{}).get("richieste_effettuate",0)
        # Public native/DeFi queries are not all counted above. Preserve
        # missing call coverage rather than misrepresenting this as a total.
        cursor={k:(result.get("asset_reti") or {}).get(k)
                for k in ("prossima_rete_nativa","prossimo_contratto")}
    elif family=="macro_context":
        import dossier_trade
        result=dossier_trade.global_context()
        count.calls=1
    else:
        import verifica_piani
        import studio_delta
        result={"verifica_piano":verifica_piani.safe_check(),
                "studio_delta":studio_delta.safe_verify()}
        count.calls=(result["verifica_piano"].get("chiamate_kraken",0)
                     +result["studio_delta"].get("chiamate_kraken",0))
    return {"state": "OSSERVATO" if result.get("stato") not in (
                   "NON_DISPONIBILE","NON_ACQUISITO") else "NON_ACQUISITO",
            "observed_at":now.isoformat(),
            "payload":result,"cursor":cursor,
            "metrics":{"source_calls":count.calls,
                       "max_calls":spec["producer_budget_calls"],
                       "call_accounting":("INCOMPLETA_NETWORK_DEFI" if family=="network_defi"
                                          else "PRODUTTORE_PER_FAMIGLIA"),
                       "coverage":result.get("copertura"),
                       "ttl_s":spec["ttl_s"]}}
