"""Verifica osservativa dei piani GPT con sole candele Kraken CHIUSE.
Non ricostruisce ordini, fill, PnL, conferme discrezionali né successo del trade.
"""
import datetime as dt
import hashlib
import json
import math
import re
from pathlib import Path
import decision_desk as desk
import piano_gpt

DIR=Path(__file__).resolve().parent
INTERVAL=900  # 15 minuti
MAX_BARS=720  # limite storico Kraken per OHLC
PLANS=DIR/'storico_piani'
LOG=DIR/'storico_verifiche.jsonl'


def utc_timestamp(value):
    return piano_gpt.parse_dt(value).timestamp()


def plan_hash(plan):
    payload=json.dumps(plan,ensure_ascii=False,sort_keys=True,separators=(',',':'))
    return hashlib.sha256(payload.encode('utf-8')).hexdigest()


def analyze(plan, bars, now):
    """Misura eventi DOPO la pubblicazione, senza assumere l'esecuzione di ordini."""
    piano_gpt.validate(plan)
    if not plan.get('livelli'):
        return {'stato':'SENZA_LIVELLI','giudizio':'Non esistono livelli numerici da verificare'}
    creation=utc_timestamp(plan['creato_utc'])
    expiry=utc_timestamp(plan['scade_utc'])
    cutoff=min(expiry,now)
    first=int(math.ceil(creation/INTERVAL)*INTERVAL)
    # L'ultima candela parziale non entra mai. Alla scadenza si escludono
    # anche i pezzi di candela che si chiudono dopo la scadenza.
    last=int(cutoff//INTERVAL)*INTERVAL-INTERVAL
    expected=list(range(first,last+1,INTERVAL)) if last>=first else []
    levels=plan['livelli']
    actual={}
    for row in bars:
        if len(row)<5:continue
        t=int(row[0])
        if t not in expected:continue
        high=float(row[2]); low=float(row[3]); close=float(row[4])
        if not all(math.isfinite(v) and v>0 for v in (low,high,close)) or low>high or not (low<=close<=high):
            continue
        actual[t]={'high':high,'low':low,'close':close}
    observed=[(t,actual[t]) for t in sorted(actual)]
    complete=bool(expected) and len(actual)==len(expected)
    if not observed:
        return {'stato':'NESSUN_DATO','giudizio':'Nessuna candela chiusa utile',
                'copertura_completa':False,'attese':len(expected),'ottenute':0}
    first_touch={}
    for name,level in levels.items():
        if name=='ingresso':
            hits=[t for t,b in observed if b['low']<=level<=b['high']]
        elif name=='stop':
            hits=[t for t,b in observed if b['low']<=level]
        elif name=='obiettivo1':
            hits=[t for t,b in observed if b['high']>=level]
        else:
            continue
        first_touch[name]=(dt.datetime.fromtimestamp(hits[0]+INTERVAL,dt.timezone.utc)
                          .isoformat() if hits else None)
    times={}
    for name,when in first_touch.items():
        times[name]=utc_timestamp(when) if when else None
    stop=times.get('stop');target=times.get('obiettivo1')
    if stop and target:
        order=('INVALIDAZIONE_PRIMA_DEL_TARGET' if stop<target else
               'TARGET_PRIMA_DELL_INVALIDAZIONE' if target<stop else
               'STESSA_CANDELA_ORDINE_IGNOTO')
    elif stop:order='SOLO_INVALIDAZIONE_OSSSERVATA'
    elif target:order='SOLO_TARGET_OSSERVATO'
    else:order='NESSUNO_DEI_DUE_OSSERVATO'
    # L'assenza di livelli non è dimostrabile se mancano barre.
    return {
      'stato':'COMPLETO' if complete and now>=expiry else 'PROVVISORIO',
      'copertura_completa':complete,
      'attese':len(expected),'ottenute':len(actual),
      'prima_candela_utc':dt.datetime.fromtimestamp(observed[0][0]+INTERVAL,dt.timezone.utc).isoformat(),
      'ultima_candela_utc':dt.datetime.fromtimestamp(observed[-1][0]+INTERVAL,dt.timezone.utc).isoformat(),
      'minimo_osservato':min(b['low'] for _,b in observed),
      'massimo_osservato':max(b['high'] for _,b in observed),
      'chiusura_ultima':observed[-1][1]['close'],
      'primo_contatto_livelli_utc':first_touch,
      'ordine_eventi':order,
      'giudizio':('Osservazione delle candele: le condizioni di ingresso '
                  '(conferma 15m, volumi, spread) NON sono state validate, '
                  'quindi non è possibile dedurre un trade eseguito o un profitto.'),
      'limiti':['Barre OHLC da 15 minuti: non mostrano il percorso dei prezzi dentro la candela.',
                'Nessuna verifica di conferme qualitative del piano, fill, commissioni o saldo reale.',
                'Se le barre storiche sono incomplete, non affermare che un livello non è stato raggiunto.']
    }


def latest_for_hash(digest):
    if not LOG.exists():return None
    rows=[]
    for line in LOG.read_text(encoding='utf-8').splitlines():
        try:
            item=json.loads(line)
            if item.get('hash_piano')==digest: rows.append(item)
        except (ValueError,TypeError):continue
    return rows[-1] if rows else None


def check(plan=None, now=None):
    if plan is None:plan=piano_gpt.load()
    if not plan or 'errore' in plan:
        return {'stato':'NON_DISPONIBILE','giudizio':'Nessun piano GPT valido'}
    piano_gpt.validate(plan)
    if now is None:now=desk.NOW().timestamp()
    digest=plan_hash(plan)
    prev=latest_for_hash(digest)
    # Dopo un intervallo completo e archiviato non fare richieste superflue.
    if prev and prev.get('stato')=='COMPLETO' and prev.get('copertura_completa'):
        return prev
    if not re.fullmatch(r'[A-Z0-9.]{2,20}/(?:EUR|USD|USDC)',plan['coppia']):
        raise ValueError('Coppia non ammessa per la verifica pubblica')
    response=desk.kraken('OHLC',pair=plan['coppia'].replace('/',''),interval=15)
    rows=next(v for k,v in response.items() if k!='last')
    result=analyze(plan,rows,now)
    result.update(hash_piano=digest,token=plan['token'],coppia=plan['coppia'],
                  piano_creato_utc=plan['creato_utc'],piano_scade_utc=plan['scade_utc'],
                  osservato_utc=dt.datetime.fromtimestamp(now,dt.timezone.utc).isoformat(),
                  fonte='Kraken OHLC pubblica 15 minuti')
    PLANS.mkdir(exist_ok=True)
    path=PLANS/(digest+'.json')
    if not path.exists():
        try:
            with path.open('x',encoding='utf-8') as f:
                json.dump(plan,f,ensure_ascii=False,indent=2)
                f.write('\n')
        except FileExistsError:pass
    # Archiviare osservazioni nuove. Non salvare duplicati di stessa ultima candela.
    if not prev or (prev.get('ultima_candela_utc'),prev.get('stato')) != (result.get('ultima_candela_utc'),result.get('stato')):
        with LOG.open('a',encoding='utf-8') as f:
            f.write(json.dumps(result,ensure_ascii=False)+'\n')
    return result


def safe_check():
    """Verifica il piano pubblicato E i precedenti ancora aperti, con budget API."""
    try:
        result=check_all()
        return result['corrente']
    except Exception as exc:
        err={'stato':'ERRORE_RILEVAZIONE','giudizio':type(exc).__name__+': '+str(exc)[:150],
             'osservato_utc':desk.NOW().isoformat(timespec='seconds')}
        desk.save('verifica_piano_corrente.json',err)
        desk.save('verifica_storico_stato.json',{'stato':'ERRORE','problemi':[err['giudizio']]})
        return err


def render_summary(result, plan):
    """Una breve lettura dell'esito osservato, senza confonderlo con un trade."""
    import html
    esc=lambda x:html.escape(str(x),quote=True)
    if not plan or not result or result.get('hash_piano') != plan_hash(plan):
        return ""
    if result.get('stato')=='SENZA_LIVELLI':
        return ("<section id='verifica-piano'><article>"
                "<h2>Verifica successiva</h2><p>Piano di osservazione: "
                "nessuna entrata autorizzata o livello operativo; "
                "non esiste un rendimento da attribuire al piano.</p></article></section>")
    event=result.get('ordine_eventi','')
    if event=='INVALIDAZIONE_PRIMA_DEL_TARGET':
        conclusion=("Il prezzo ha attraversato l'invalidazione prima di raggiungere "
                    "l'obiettivo. Il successivo rialzo NON rende riuscito il piano.")
    elif event=='STESSA_CANDELA_ORDINE_IGNOTO':
        conclusion=("Invalidazione e obiettivo nella stessa candela: "
                    "l'ordine temporale NON è ricostruibile.")
    elif event=='TARGET_PRIMA_DELL_INVALIDAZIONE':
        conclusion=("L'obiettivo è stato attraversato prima dell'invalidazione, "
                    "ma NON è dimostrata un'entrata valida o un profitto.")
    elif event=='SOLO_TARGET_OSSERVATO':
        conclusion=("Obiettivo osservato; non significa che il piano "
                    "avrebbe prodotto un trade eseguibile.")
    elif event=='SOLO_INVALIDAZIONE_OSSSERVATA':
        conclusion=("Invalidazione osservata; nessun profitto "
                    "o ordine reale deducibile.")
    else:
        conclusion="Sviluppo osservato sulle candele, senza conclusioni di trading."
    if not result.get('copertura_completa'):
        conclusion+=" ATTENZIONE: dati storici incompleti."
    when=result.get('primo_contatto_livelli_utc',{})
    return (
        "<section aria-label='Verifica del piano' id='verifica-piano'>"
        "<article style='border-left:4px solid #e6a04b;padding:12px'>"
        "<h2 style='font-size:1.05rem'>Che cosa è successo dopo il piano?</h2>"
        f"<p>{esc(conclusion)}</p>"
        "<details><summary>Vedi i fatti osservati</summary>"
        f"<p>Prima invalidazione (fine candela UTC): {esc(when.get('stop') or 'non osservata')}</p>"
        f"<p>Primo obiettivo (fine candela UTC): {esc(when.get('obiettivo1') or 'non osservato')}</p>"
        f"<p>Minimo/massimo nelle candele osservate: "
        f"{esc(result.get('minimo_osservato','?'))} / {esc(result.get('massimo_osservato','?'))}</p>"
        f"<p>Copertura 15m: {esc(result.get('ottenute','?'))}/"
        f"{esc(result.get('attese','?'))} barre · {esc(result.get('stato','?'))}.</p>"
        "<p>Nessun ordine eseguito o confermato. Le candele non permettono "
        "di verificare tutte le condizioni di ingresso, lo slippage o i costi.</p>"
        "</details></article></section>"
    )


def archivia_piano(plan):
    """Registra una fotografia immutabile prima che la prossima analisi la sostituisca."""
    if not plan or 'errore' in plan:
        return None
    piano_gpt.validate(plan)
    digest=plan_hash(plan)
    PLANS.mkdir(parents=True,exist_ok=True)
    filename=PLANS/(digest+'.json')
    if filename.exists():
        saved=json.loads(filename.read_text(encoding='utf-8'))
        if plan_hash(saved)!=digest:
            raise ValueError('Archivio piano alterato: '+digest[:12])
    else:
        # Modalita' x: un altro processo non puo' sovrascrivere un piano.
        with filename.open('x',encoding='utf-8') as out:
            json.dump(plan,out,ensure_ascii=False,indent=2)
            out.write('\n')
    return digest


def check_all(max_queries=4):
    """Segue piu' piani, senza fingere monitoraggio continuo.

    La prova e' aggiornata SOLO quando l'utente aggiorna il desk
    o quando questo modulo viene chiamato. Le verifiche definitive
    complete sono riusate senza nuove API.
    """
    if not isinstance(max_queries,int) or max_queries<0:
        raise ValueError('Budget API non valido')
    current=piano_gpt.load()
    digest_corrente=archivia_piano(current)
    files=sorted(PLANS.glob('*.json')) if PLANS.exists() else []
    plans=[]
    issues=[]
    for path in files:
        try:
            plan=json.loads(path.read_text(encoding='utf-8'))
            piano_gpt.validate(plan)
            if path.stem!=plan_hash(plan):
                raise ValueError('Nome file e piano non corrispondono')
            plans.append((path.stem,plan))
        except (ValueError,TypeError,KeyError) as exc:
            issues.append('Piano archivio illeggibile '+path.name[:20]+': '+type(exc).__name__)
    # Pianificare prima i piani in scadenza, poi il corrente, senza
    # far dipendere i vecchi piani dalla pubblicazione del nuovo.
    plans.sort(key=lambda item: (utc_timestamp(item[1]['scade_utc']),
                                 item[0]))
    results=[]
    current_result=None
    now=desk.NOW().timestamp()
    for digest,plan in plans:
        previous=latest_for_hash(digest)
        if not plan.get('livelli'):
            outcome={'stato':'SENZA_LIVELLI','hash_piano':digest,
                     'giudizio':'Decisione di osservazione, non verificabile come operazione'}
            row={'hash_piano':digest,'token':plan['token'],'coppia':plan['coppia'],
                 'creato_utc':plan['creato_utc'],'scade_utc':plan['scade_utc'],
                 'tracking':'PIANO_NON_OPERATIVO','stato':'SENZA_LIVELLI',
                 'ordine_eventi':None,'copertura_completa':False}
            results.append(row)
            if digest==digest_corrente:
                current_result=outcome
            continue
        complete=bool(previous and previous.get('stato')=='COMPLETO'
                      and previous.get('copertura_completa'))
        if complete:
            outcome=previous
            tracking='CONCLUSO'
        elif max_queries>0:
            # Si possono recuperare solo le ultime ~720 candele 15m
            # dall'API Kraken. Se la finestra e' andata perduta,
            # non fabbricare una storia dei prezzi.
            too_old=utc_timestamp(plan['creato_utc']) < now-(MAX_BARS-2)*INTERVAL
            if too_old:
                outcome={'stato':'DATI_STORICI_NON_RECUPERABILI',
                         'hash_piano':digest,
                         'giudizio':'Kraken non offre piu tutta la finestra OHLC 15m necessaria',
                         'copertura_completa':False}
                tracking='LACUNA'
            else:
                max_queries-=1
                try:
                    outcome=check(plan,now=now)
                    tracking='CONCLUSO' if (outcome.get('stato')=='COMPLETO'
                                            and outcome.get('copertura_completa')) else 'IN_OSSERVAZIONE'
                except Exception as exc:
                    issues.append(plan['token']+': verifica non riuscita ('+type(exc).__name__+')')
                    outcome=previous or {'stato':'ERRORE_RILEVAZIONE','hash_piano':digest}
                    tracking='DA_RIPRENDERE'
        else:
            outcome=previous or {'stato':'IN_ATTESA_VERIFICA','hash_piano':digest}
            tracking='DA_RIPRENDERE'
        row={'hash_piano':digest,'token':plan['token'],'coppia':plan['coppia'],
             'creato_utc':plan['creato_utc'],'scade_utc':plan['scade_utc'],
             'tracking':tracking,'stato':outcome.get('stato','NON_DISPONIBILE'),
             'ordine_eventi':outcome.get('ordine_eventi'),
             'copertura_completa':outcome.get('copertura_completa',False)}
        results.append(row)
        if digest==digest_corrente:
            current_result=outcome
    if current_result is None:
        current_result={'stato':'NON_DISPONIBILE','giudizio':'Nessun piano corrente registrato'}
    summary={
        'stato':('NESSUN_PIANO' if not results else
                 'PARZIALE' if issues or any(x['tracking'] not in ('CONCLUSO','PIANO_NON_OPERATIVO')
                                            for x in results)
                 else 'VERIFICATO'),
        'aggiornato_utc':desk.NOW().isoformat(timespec='seconds'),
        'piani_totali':len(results),
        'conclusi':sum(x['tracking']=='CONCLUSO' for x in results),
        'non_operativi':sum(x['tracking']=='PIANO_NON_OPERATIVO' for x in results),
        'da_riprendere':sum(x['tracking']=='DA_RIPRENDERE' for x in results),
        'lacune':sum(x['tracking']=='LACUNA' for x in results),
        'problemi':issues,
        'piani':results
    }
    desk.save('verifica_piano_corrente.json',current_result)
    desk.save('verifica_storico_stato.json',summary)
    return {'corrente':current_result,'storico':summary}


def render_archivio(summary, digest_corrente):
    """Soltanto uno storico richiudibile, senza percentuali di 'successo' fittizie."""
    import html
    esc=lambda v:html.escape(str(v),quote=True)
    if not summary or not isinstance(summary.get('piani'),list):
        return ''
    items=[x for x in summary['piani'] if x.get('hash_piano')!=digest_corrente]
    if not items:
        return ''
    def state(x):
        if x.get('tracking')=='CONCLUSO':
            if x.get('ordine_eventi')=='INVALIDAZIONE_PRIMA_DEL_TARGET':
                return 'Invalidazione vista prima del target'
            if x.get('ordine_eventi')=='TARGET_PRIMA_DELL_INVALIDAZIONE':
                return 'Target visto prima dell’invalidazione (nessun fill provato)'
            return 'Finestra osservata; nessun trade deducibile'
        if x.get('tracking')=='LACUNA':
            return 'Storico Kraken insufficiente: verifica non ricostruibile'
        return 'Verifica parziale o in corso'
    rows=''.join('<li><b>'+esc(item.get('coppia','?'))+'</b> · '
                 +esc(item.get('creato_utc','?'))+' · '+esc(state(item))+'</li>'
                 for item in items[:30])
    return ('<details><summary>Archivio: '+str(len(items))+
            ' piani precedenti conservati</summary><p>Gli esiti indicano '
            'soltanto livelli attraversati: non ordini, profitti o successi statistici.</p>'
            '<ul>'+rows+'</ul></details>')


if __name__=='__main__':
    print(json.dumps(safe_check(),indent=2,ensure_ascii=False))
