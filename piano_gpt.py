"""Pubblicazione di un piano GPT scritto in chat; validazione, scadenza, HTML sicuro.
Nessun LLM sul telefono, nessuna API privata o ordine.
"""
import datetime as dt
import html
import math
from urllib.parse import urlparse
from pathlib import Path
import json

ROOT = Path(__file__).resolve().parent
REQUIRED_STRINGS = (
    "autore", "creato_utc", "snapshot_kraken_utc", "scade_utc",
    "token", "coppia", "mercato", "stato", "azione",
    "tesi", "condizione_ingresso", "condizione_invalidazione",
    "condizione_uscita", "revisione", "capitale", "alternativa", "contesto_portafoglio"
)


def parse_dt(v):
    result = dt.datetime.fromisoformat(v.replace("Z","+00:00"))
    if result.tzinfo is None: raise ValueError("Timestamp UTC richiesto")
    return result.astimezone(dt.timezone.utc)


def validate(plan):
    if not isinstance(plan,dict):raise ValueError("Piano non JSON oggetto")
    for name in REQUIRED_STRINGS:
        v=plan.get(name)
        if not isinstance(v,str) or not v.strip() or len(v)>2800:
            raise ValueError("Piano incompleto: "+name)
    creation=parse_dt(plan["creato_utc"])
    snap=parse_dt(plan["snapshot_kraken_utc"])
    expiry=parse_dt(plan["scade_utc"])
    if not (snap<=creation<=expiry and expiry<=creation+dt.timedelta(days=7)):
        raise ValueError("Timestamp del piano incoerenti")
    if (creation-snap)>dt.timedelta(hours=3):
        raise ValueError("Piano basato su rilevazione troppo vecchia")
    if plan.get("mercato")!="SPOT":raise ValueError("Solo spot in questa fase")
    for name in ("motivi","rischi","dati_mancanti","fonti"):
        v=plan.get(name)
        if not isinstance(v,list) or not (1<=len(v)<=12):
            raise ValueError("Elenco richiesto: "+name)
    for group in ("motivi","rischi","dati_mancanti"):
        if not all(isinstance(x,str) and 0<len(x)<=1400 for x in plan[group]):
            raise ValueError("Testo elenco non valido: "+group)
    for source in plan["fonti"]:
        if not isinstance(source,dict) or not isinstance(source.get("nome"),str):
            raise ValueError("Fonte senza nome")
        u=source.get("url","")
        if not isinstance(u,str) or len(u)>700 or not safe_url(u):
            raise ValueError("URL fonte non valido")
    if plan.get("livelli") is not None:
        z=plan["livelli"]
        if not isinstance(z,dict) or not all(k in z for k in ("ingresso","stop","obiettivo1")):
            raise ValueError("Livelli incompleti")
        entry, stop, target=(z[k] for k in ("ingresso","stop","obiettivo1"))
        if not all(type(v) in (float,int) and math.isfinite(v) and v>0
                   for v in (entry,stop,target)):
            raise ValueError("Livelli numerici invalidi")
        if not (stop<entry<target):
            raise ValueError("Per long spot: stop < ingresso < primo target")
    return plan


def safe_url(url):
    p=urlparse(url)
    return p.scheme=="https" and bool(p.netloc) and not p.username and not p.password


def load():
    path=ROOT/"piano_gpt.json"
    if not path.exists():return None
    try: return validate(json.loads(path.read_text(encoding="utf-8")))
    except (ValueError,TypeError,KeyError,OverflowError,AttributeError) as exc:
        return {"errore":"Piano GPT non valido: "+type(exc).__name__}


def render_box(plan, current_snapshot):
    esc=lambda s:html.escape(str(s),quote=True)
    if not plan:
        return ("<section aria-label='Analisi GPT' id='piano-gpt'><article>"
                "<h2>Analisi GPT — non ancora pubblicata</h2>"
                "<p>Il desk raccoglie dati; la proposta GPT viene costruita in chat "
                "e pubblicata qui, con ora e condizioni. Nessun segnale automatico.</p>"
                "</article></section>")
    if "errore" in plan:
        return "<article class='urgente'>"+esc(plan["errore"])+"</article>"
    stale_by_refresh=parse_dt(current_snapshot)>parse_dt(plan["snapshot_kraken_utc"])+dt.timedelta(minutes=2)
    cre=esc(plan["creato_utc"])
    expiry=esc(plan["scade_utc"])
    snap=esc(plan["snapshot_kraken_utc"])
    warnings="<p class='urgente'>È disponibile una rilevazione Kraken successiva: "             "questa analisi GPT NON è stata ricalcolata. Ricontrolla i livelli.</p>" if stale_by_refresh else ""
    def li(xs):return "".join("<li>"+esc(v)+"</li>" for v in xs)
    level_block=""
    if plan.get("livelli"):
        z=plan["livelli"]
        rr=(z["obiettivo1"]-z["ingresso"])/(z["ingresso"]-z["stop"])
        level_block=(f"<p><b>Livelli di riferimento ({esc(plan['coppia'])}):</b> "
                     f"ingresso {esc(z['ingresso'])}, stop {esc(z['stop'])}, "
                     f"primo obiettivo {esc(z['obiettivo1'])} "
                     f"(R/R lordo ~{rr:.2f}:1, costi da sottrarre). "
                     "Sono soglie condizionali, NON prezzi garantiti.</p>")
    links="".join("<li><a rel='noopener noreferrer' target='_blank' href='"+
                  esc(s['url'])+"'>"+esc(s["nome"])+"</a></li>" for s in plan["fonti"])
    return (
        "<section id='piano-gpt' aria-label='Analisi GPT' "
        f"data-created='{cre}' data-expiry='{expiry}' data-snapshot='{snap}'>"
        "<article style='border:2px solid #6ee7b7;background:#10332f'>"
        "<h2 style='margin:0;color:#a7f3d0'>PRIMA LETTURA · PIANO GPT</h2>"
        f"<p class='lead'><b>{esc(plan['azione'])}</b></p>"
        f"<p><b>{esc(plan['token'])} · {esc(plan['coppia'])} · {esc(plan['mercato'])}</b>"
        f" · {esc(plan['stato'])}</p>"
        +warnings+
        "<p id='piano-freschezza' class='urgente' role='status' "
        "style='background:#233d39;border-left:3px solid #fbbf24;padding:9px'>"
        "Controllo età del piano...</p>"
        +level_block+
        f"<p><b>Condizione:</b> {esc(plan.get('sintesi_ingresso','Leggere condizioni dettagliate sotto.'))}</p>"
        f"<p><b>Convenienza:</b> {esc(plan.get('sintesi_rischio','Da verificare prima dell’ingresso.'))}</p>"
        f"<p><b>Importo:</b> {esc(plan.get('sintesi_capitale','Non conosciuto.'))}</p>"
        f"<p><b>Riesame:</b> {esc(plan.get('sintesi_revisione','Vedere le condizioni sotto.'))}</p>"
        "<details><summary style='font-weight:700;cursor:pointer'>Apri motivazione e piano completo</summary>"
        f"<p><b>Tesi:</b> {esc(plan['tesi'])}</p>"
        f"<p><b>Ingresso:</b> {esc(plan['condizione_ingresso'])}</p>"
        f"<p><b>Invalidazione:</b> {esc(plan['condizione_invalidazione'])}</p>"
        f"<p><b>Uscita:</b> {esc(plan['condizione_uscita'])}</p>"
        f"<p><b>Capitale:</b> {esc(plan['capitale'])}</p>"
        f"<p><b>Portafoglio:</b> {esc(plan['contesto_portafoglio'])}</p>"
        f"<p><b>Quando rivedere:</b> {esc(plan['revisione'])}</p>"
        f"<p><b>Alternativa scartata:</b> {esc(plan['alternativa'])}</p>"
        "</details>"
        f"<p><small>Analisi: {esc(plan['autore'])} · creata UTC {cre} · "
        f"fotografia Kraken UTC {snap} · limite UTC {expiry}.</small></p>"
        "<details><summary>Motivi, rischi, lacune e fonti del piano</summary>"
        f"<h3>Elementi esaminati</h3><ul>{li(plan['motivi'])}</ul>"
        f"<h3>Rischi</h3><ul>{li(plan['rischi'])}</ul>"
        f"<h3>Dati mancanti</h3><ul>{li(plan['dati_mancanti'])}</ul>"
        f"<h3>Fonti</h3><ul>{links}</ul></details>"
        "<small>Supporto sperimentale, non ordine né esecuzione automatica. "
        "La decisione spetta all'utente.</small>"
        "</article></section>"
        "<script>(function(){const box=document.getElementById('piano-gpt');"
        "const target=document.getElementById('piano-freschezza');"
        "const expiration=new Date(box.dataset.expiry).getTime();"
        "const snapshot=new Date(box.dataset.snapshot).getTime();"
        "function update(){const now=Date.now();"
        "if (!Number.isFinite(expiration)||!Number.isFinite(snapshot)){"
        "target.textContent='Timestamp piano non interpretabile';return;}"
        "if(now>=expiration){target.textContent='PIANO SCADUTO: ripetere analisi GPT prima di valutare un ingresso';"
        "target.className='urgente';}"
        "else if(now-snapshot>1800000){target.textContent='PIANO SU PREZZI NON RECENTI (>30 min): ricontrollare in chat prima di operare';"
        "target.className='urgente';}"
        "else {target.textContent='Piano ancora nel periodo dichiarato; condizioni da verificare sul mercato.';"
        "target.className='neutro';}}update();setInterval(update,15000);"
        "document.addEventListener('visibilitychange',update);})();</script>"
    )
