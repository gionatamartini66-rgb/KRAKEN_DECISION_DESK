"""KDD-18 G2: operational cursors survive stale evidence, without stale data."""
import copy
import datetime as dt
import unittest

import kdd_economic_sources as src
import test_kdd_economic_sources as fixture

UTC=dt.timezone.utc
T=dt.datetime(2026,11,19,9,0,tzinfo=UTC)
TOKENS=("BTC","ETH","SOL","ADA","ARB","STRK","SUI")
FIELDS=(
    "prossimo_progetto","prossima_emissione","prossima_issue",
    "prossimo_security","prossimo_indicatore","prossimo_schedule",
    "prossima_fonte_esterna","prossimo_kraken_status"
)


def roster(tokens=TOKENS):
    return fixture.PrimaryFollowupTests(
        "test_real_strk_primary_document_reports_maximum_quantified_dated_not_executed"
    ).items(tokens=tokens)


def cycle(items, prior=None, now=T, network=True):
    requests=[]
    rpcs=[]
    def deny(url):
        requests.append(url)
        raise OSError("ISOLATED_PUBLIC_SOURCE_UNAVAILABLE")
    def deny_rpc(url,query):
        rpcs.append(url)
        raise OSError("ISOLATED_SOLANA_RPC_UNAVAILABLE")
    result=src.collect(
        now,items,prior or {},deny,rpc_fetch=deny_rpc,
        network_allowed=network,collect_project_issues=True,
        collect_kraken_status=True,skipped_reason="FUORI_REFRESH")
    if network:
        assert result["richieste_pubbliche"]==len(requests)+len(rpcs)
    assert result["richieste_pubbliche"]<=8
    src.at_read(result,items,now)
    return result,requests,rpcs


class RotationContinuityG2(unittest.TestCase):
    def test_eight_close_and_eight_31_day_cycles_cover_every_eligible_source(self):
        signatures={}
        for label,increment in (("close",dt.timedelta(minutes=2)),
                                ("month",dt.timedelta(days=31))):
            old={}
            points=[]
            coverage={"governance":set(),"issue":set(),"security":set(),
                      "schedule":set(),"external":set(),"macro":set(),
                      "emission":set()}
            items=roster()
            for i in range(8):
                timestamp=T+i*increment
                result,urls,rpcs=cycle(items,old,timestamp)
                evidence=result
                points.append(tuple(evidence[name] for name in FIELDS))
                for url in urls:
                    if "/pulls?" in url:
                        coverage["governance"].add(url)
                    elif "/issues?" in url:
                        coverage["issue"].add(url)
                    elif "/security-advisories?" in url:
                        coverage["security"].add(url)
                    elif url in (src.STRK_URL,src.ARB_VESTING_URL,
                                 src.SUI_CIRCULATION):
                        coverage["schedule"].add(url)
                    elif url in [x[1] for x in src.MACRO_RELEASE_FEEDS+
                                         src.FINANCIAL_FEEDS+src.KRAKEN_STATUS_FEEDS]:
                        coverage["external"].add(url)
                    else:
                        coverage["macro"].add(url)
                coverage["emission"].update(rpcs)
                self.assertEqual(result["richieste_pubbliche"],8)
                self.assertEqual(result["limite_richieste"],8)
                old=result
            signatures[label]=points
            self.assertEqual(len(coverage["governance"]),3,label)
            self.assertEqual(len(coverage["issue"]),4,label)
            self.assertEqual(len(coverage["security"]),4,label)
            self.assertEqual(len(coverage["schedule"]),3,label)
            self.assertEqual(len(coverage["external"]),7,label)
            self.assertEqual(len(coverage["emission"]),1,label)
            # 2 CFTC indicator IDs share one URL, hence 6 distinct endpoints.
            self.assertEqual(len(coverage["macro"]),6,label)
            self.assertEqual(
                {point[4] for point in points},
                {s[0] for s in src.MACRO_SERIES},label)
        self.assertEqual(signatures["close"],signatures["month"])

    def test_stale_timestamp_reuses_only_pointer_never_original_observations(self):
        items=roster(("STRK",))
        old,_,_=cycle(items,{},T)
        observed={"schema":src.SCHEMA,"acquisito_utc":T.isoformat(),
                  "prossimo_schedule":"starknet",
                  "calendari":[{"progetto_id":"starknet",
                       "stato":"DOCUMENTO_PRIMARIO_CON_MASSIMI_DATATI",
                       "acquisito_utc":T.isoformat(),
                       "eventi":[{"tipo":"UNLOCK_PROGRAMMATO",
                                  "quantita_massima_token":127000000}],
                       "sha256_documento":"a"*64}],
                  "indicatori_macro":[{"id":"USD_EUR","stato":"OSSERVATO",
                        "valore":123,"acquisito_utc":T.isoformat()}]}
        after,urls,rpcs=cycle(items,observed,T+dt.timedelta(days=31))
        self.assertIn(src.STRK_URL,urls)
        calendar=after["calendari"][0]
        self.assertEqual(calendar["stato"],"FONTE_NON_DISPONIBILE")
        self.assertEqual(calendar["eventi"],[])
        self.assertNotIn("sha256_documento",calendar)
        self.assertNotEqual(after["indicatori_macro"][0].get("valore"),123)
        self.assertEqual(src._prior(observed,T+dt.timedelta(days=31)),{})
        self.assertEqual(src._rotation_cursors(observed,T+dt.timedelta(days=31))
                         ["prossimo_schedule"],"starknet")

    def test_removed_project_uses_valid_successor_and_reenters_without_misattribution(self):
        items=roster()
        first,_,_=cycle(items,{},T)
        self.assertEqual(first["prossimo_schedule"],"starknet")
        reduced=roster(tuple(token for token in TOKENS if token!="STRK"))
        second,urls,_=cycle(reduced,first,T+dt.timedelta(days=31))
        self.assertIn(src.SUI_CIRCULATION,urls)
        self.assertNotIn(src.STRK_URL,urls)
        self.assertEqual(second["prossimo_schedule"],"arbitrum")
        self.assertTrue(all(x["progetto_id"]!="starknet" for x in second["calendari"]))
        third,urls,_=cycle(items,second,T+dt.timedelta(days=62))
        self.assertIn(src.ARB_VESTING_URL,urls)
        fourth,urls,_=cycle(items,third,T+dt.timedelta(days=93))
        self.assertIn(src.STRK_URL,urls)
        self.assertEqual(fourth["prossimo_schedule"],"sui")

    def test_invalid_schema_time_and_malformed_cursors_reset_safely(self):
        items=roster()
        first,_,_=cycle(items,{},T)
        baseline,urls,_=cycle(items,{},T+dt.timedelta(days=31))
        for change in (
            {"schema":"wrong"},
            {"acquisito_utc":"invalid"},
            {"acquisito_utc":(T+dt.timedelta(days=32,hours=2)).isoformat()},
        ):
            with self.subTest(change=change):
                damaged=dict(first,**change)
                row,urls,_=cycle(items,damaged,T+dt.timedelta(days=31))
                self.assertEqual(tuple(row[x] for x in FIELDS),
                                 tuple(baseline[x] for x in FIELDS))
                self.assertEqual(src._rotation_cursors(damaged,
                                 T+dt.timedelta(days=31)),{})
        for invalid in (None,123,[],{},"ZZZ?"):
            with self.subTest(invalid=repr(invalid)):
                bad=copy.deepcopy(first)
                for field in FIELDS:
                    bad[field]=invalid
                got,_,_=cycle(items,bad,T+dt.timedelta(days=31))
                self.assertEqual(tuple(got[x] for x in FIELDS),
                                 tuple(baseline[x] for x in FIELDS))

    def test_external_historic_alias_restored_but_primary_valid_wins(self):
        items=roster()
        first,_,_=cycle(items,{},T)
        legacy=copy.deepcopy(first)
        legacy.pop("prossima_fonte_esterna",None)
        for change in (None,"BAD-ID"):
            case=copy.deepcopy(legacy)
            if change is not None:
                case["prossima_fonte_esterna"]=change
            result,urls,_=cycle(items,case,T+dt.timedelta(days=31))
            self.assertTrue(any("scheduled-maintenances.json" in url
                                for url in urls))
            self.assertEqual(result["prossimo_kraken_status"],
                             result["prossima_fonte_esterna"])
        both=copy.deepcopy(first)
        both["prossimo_kraken_status"]="INCIDENTI"
        result,urls,_=cycle(items,both,T+dt.timedelta(days=31))
        self.assertTrue(any("scheduled-maintenances.json" in u for u in urls))
        self.assertFalse(any("incidents.json" in u for u in urls))

    def test_network_disabled_keeps_all_cursors_and_uses_zero_calls(self):
        items=roster()
        first,_,_=cycle(items,{},T)
        paused,urls,rpcs=cycle(items,first,T+dt.timedelta(days=31),network=False)
        self.assertEqual(urls,[])
        self.assertEqual(rpcs,[])
        self.assertEqual(paused["richieste_pubbliche"],0)
        self.assertEqual(tuple(paused[x] for x in FIELDS),
                         tuple(first[x] for x in FIELDS))
        resumed,urls,rpcs=cycle(items,paused,T+dt.timedelta(days=62),network=True)
        self.assertEqual(resumed["richieste_pubbliche"],8)
        self.assertNotEqual(resumed["prossimo_schedule"],first["prossimo_schedule"])
        self.assertTrue(all("FONTE_NON_DISPONIBILE" in (row.get("stato") or "")
                            or row["progetto_id"]!="starknet"
                            for row in resumed["calendari"]))

    def test_refresh_failures_advance_cursors_no_false_verified_sources(self):
        items=roster()
        before,_,_=cycle(items,{},T)
        after,urls,rpcs=cycle(items,before,T+dt.timedelta(days=31))
        self.assertEqual(len(urls)+len(rpcs),8)
        for field in FIELDS:
            if field=="prossima_emissione":
                self.assertEqual(before[field],after[field])
            else:
                self.assertNotEqual(before[field],after[field])
        self.assertTrue(all(row.get("stato")!="DOCUMENTO_PRIMARIO_CON_MASSIMI_DATATI"
                            for row in after["calendari"]))
        src.at_read(after,items,T+dt.timedelta(days=31))


if __name__=="__main__":
    unittest.main()
