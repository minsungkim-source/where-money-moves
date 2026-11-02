"""Regression tests for the parsers. Each guard exists because a real file once looked like this.

  python -m unittest discover -s tests -v

BOT sheets are synthesised (the real zip is 9MB); SSO and DOPA use a real file each, trimmed to nothing.
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FIX = Path(__file__).resolve().parent / "fixtures"
sys.path.insert(0, str(ROOT / "etl"))

import etl          # noqa: E402
import my_dosm      # noqa: E402
import ph_psa       # noqa: E402
import summary      # noqa: E402
import th_dopa      # noqa: E402
import th_sso       # noqa: E402
import vn_gso       # noqa: E402

W = 16  # read_all asks openpyxl for 16 columns


def pad(*cells):
    return tuple(list(cells) + [None] * (W - len(cells)))


def bot_rows(layout=3, n=210, month="July 2026", mutate=None):
    """A BOT district sheet: title, as-of, unit, header, sub-header, Head Office, one province, n districts."""
    sub = ["Current", "Saving", "Time ", "Promissory Note", " NCD", "Total", "Overdraft", "Loan"]
    sub += ["Bills and Others", "Total"] if layout == 3 else ["Bills", "Others", "Total"]
    rows = [pad("Report on Deposits and Credits Classified by Districts*"), pad(f"Outstanding As of {month}"),
            pad(*([None] * 11 + ["Unit : Million Baht"])), pad("Provinces/Districts", "No.of branches", "Deposits"),
            pad(None, None, *sub)]

    def rec(name, br, dep_parts, cr_parts):
        return pad(name, br, *dep_parts, sum(dep_parts), *cr_parts, sum(v for v in cr_parts if isinstance(v, (int, float))))

    cr = (10, 100, 5) if layout == 3 else (10, 100, 3, 2)
    rows.append(rec("Head Office", 29, (1, 2, 3, 0, 0), cr))
    rows.append(pad("Bangkok ", "", "", "", "", "", "", ""))
    for i in range(n):
        rows.append(rec(f"District {i}", 5, (10, 20, 30, 0, 0), cr))
    if mutate:
        mutate(rows)
    rows.append(pad("Remark :   *  Especially Districts which have four commercial banks or more."))
    return rows


class BotSheet(unittest.TestCase):
    def test_both_layouts_parse(self):
        for layout in (3, 4):
            head, recs = etl.parse_sheet(bot_rows(layout), f"layout{layout}")
            self.assertEqual(len(recs), 210)
            self.assertEqual(recs[0]["deposits"], 60 * etl.MB)          # million baht → baht, once
            self.assertEqual(recs[0]["credits"], 115 * etl.MB)
            self.assertEqual(head["branches"], 29)                       # head office kept apart, not a district

    def test_unknown_subheader_stops(self):
        rows = bot_rows()
        rows[4] = pad(None, None, "Current", "Saving", "Time", "Promissory Note", "NCD", "Total", "Overdraft", "Loan", "Leasing", "Total")
        with self.assertRaises(etl.ParserDriftError):
            etl.parse_sheet(rows, "x")

    def test_shifted_column_is_caught_by_sum_check(self):
        def shift(rows):
            r = list(rows[10]); r[7] = r[7] + 999; rows[10] = tuple(r)   # total no longer equals its parts
        with self.assertRaises(etl.ParserDriftError):
            etl.parse_sheet(bot_rows(mutate=shift), "x")

    def test_masked_credit_parts_are_allowed(self):
        def mask(rows):                                                    # 'n.a.' = five or fewer debtors
            r = list(rows[10]); r[8] = "n.a."; r[10] = "n.a."; rows[10] = tuple(r)
        _, recs = etl.parse_sheet(bot_rows(mutate=mask), "x")
        self.assertEqual(recs[3]["credits"], 115 * etl.MB)

    def test_masked_parts_larger_than_total_still_stop(self):
        def bad(rows):
            r = list(rows[10]); r[8] = "n.a."; r[9] = 99999; rows[10] = tuple(r)
        with self.assertRaises(etl.ParserDriftError):
            etl.parse_sheet(bot_rows(mutate=bad), "x")

    def test_total_row_ends_the_table(self):                              # 2023-01..04 sheets carry a Total row
        def total(rows):
            rows.append(pad("Total", 4640, 1, 1, 1, 0, 0, 3, 1, 1, 1, 3))
            rows.append(pad("Ghost", 4, 1, 1, 1, 0, 0, 3, 1, 1, 1, 3))
        _, recs = etl.parse_sheet(bot_rows(mutate=total), "x")
        self.assertEqual(len(recs), 210)

    def test_too_few_districts_stops(self):
        with self.assertRaises(etl.ParserDriftError):
            etl.parse_sheet(bot_rows(n=120), "x")

    def test_period_from_label_or_sheet_name(self):
        self.assertEqual(etl._period_of("Outstanding As of July 2026", "Jul 26"), "2026-07")
        self.assertEqual(etl._period_of(None, "Jan 25"), "2025-01")       # 2025_S2's Jan sheet has no label
        self.assertEqual(etl._period_of("Outstanding As of Jun 2023", "Jun23"), "2023-06")


class Names(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        provs, dists, cls.aliases = etl.load_reference()
        cls.pidx = etl.build_province_index(provs)
        cls.by_prov = {}
        for d in dists:
            cls.by_prov.setdefault(d["parent_province_tis1099_code"], []).append(d)

    def test_bot_province_spellings(self):
        for raw, tis in (("Chiengmai", "50"), ("Trad", "23"), ("Pahtthalung", "93"), ("SongKla", "90"),
                         ("Phranakonsiayutthaya", "14"), ("Bangkok ", "10")):
            self.assertEqual(etl.match_province(raw, self.pidx), tis, raw)

    def test_district_fuzzy_and_aliases(self):
        cases = (("50", "Muang Chiangmai", "5001"), ("10", "Latphrao", "1038"), ("12", "#N/A", "1203"),
                 ("54", "Muang Phrea", "5401"), ("14", "Bangpain", "1406"))
        for prov, raw, want in cases:
            self.assertEqual(etl.match_district(prov, raw, self.by_prov, self.aliases)[0], want, raw)

    def test_ambiguous_district_is_refused(self):
        with self.assertRaises(LookupError):
            etl.match_district("50", "Mae", self.by_prov, {})


class Sso(unittest.TestCase):
    def setUp(self):
        provs, _, _ = etl.load_reference()
        self.pidx = etl.build_province_index(provs)
        self.body = (FIX / "sso-t11-2568.xlsx").read_bytes()

    def test_real_file(self):
        out = th_sso.parse(self.body, 2568, self.pidx)
        self.assertEqual(len(out), 77)
        self.assertEqual(out["10"]["insured"], 4167672)                  # Bangkok total, not its area offices
        self.assertEqual(sum(v["insured"] for v in out.values()), 12183749)

    def test_wrong_year_stops(self):
        with self.assertRaises(etl.ParserDriftError):
            th_sso.parse(self.body, 2569, self.pidx)


class Dopa(unittest.TestCase):
    def setUp(self):
        self.text = (FIX / "dopa-6712cc93.txt").read_text(encoding="utf-8")   # first rows of a real file

    def test_real_file_matches_the_catalog(self):
        # catalog.dopa.go.th (the previous source) gave Phatthalung 519,440 for December 2024
        self.assertEqual(th_dopa.parse(self.text, "2024/93"), 519440)

    def test_male_plus_female_must_equal_total(self):
        first, rest = self.text.split("\n", 1)
        cells = first.split("|")
        cells[-2] = str(int(cells[-2]) + 1)                                # grand total off by one
        with self.assertRaises(etl.ParserDriftError):
            th_dopa.parse("|".join(cells) + "\n" + rest, "x")

    def test_first_row_must_be_a_province(self):
        with self.assertRaises(etl.ParserDriftError):
            th_dopa.parse(self.text.split("\n", 1)[1], "x")

    def test_year_page_links(self):
        class Page:
            text = '<a href="../file/6812/6812cc10.txt">x</a><a href="../file/6812/6812cc96.txt">y</a><a href="../file/6712/6712cc10.txt">z</a>'
            def raise_for_status(self): pass
        class S:
            def get(self, *a, **k): return Page()
        links = th_dopa.links_for(S(), 2025)
        self.assertEqual(sorted(links), ["10", "96"])                       # other years' links ignored
        self.assertTrue(links["96"].endswith("/file/6812/6812cc96.txt"))

    def test_only_finished_decembers(self):
        from datetime import date
        self.assertEqual(th_dopa.december_years(date(2026, 10, 27))[-1], 2025)


def dopa_file(rows, total):
    """stat.bora layout: name|…|male|female|total| — only the total matters here."""
    return "\n".join([f"จังหวัดทดสอบ|0|0|{total}|"] + [f"{n}|0|0|{v}|" for n, v in rows]) + "\n"


class DopaDistricts(unittest.TestCase):
    refs = None

    @classmethod
    def setUpClass(cls):
        cls.refs = th_dopa.references()

    def test_phatthalung_matches_the_coded_catalog(self):
        text = (FIX / "dopa-6712cc93-rows.txt").read_text(encoding="utf-8")    # every row, name and totals only
        got, unplaced = th_dopa.districts(text, "93", self.refs, "fixture")
        self.assertEqual(unplaced, [])
        self.assertEqual((got["9304"], got["9309"]), (31324, 26475))    # DOPA catalog stat_t67, by tambon code
        self.assertEqual(sum(got.values()), th_dopa.parse(text, "fixture"))

    def test_a_masked_tambon_is_the_one_left_over(self):
        # Rai Mai municipality (Prachuap Khiri Khan) spans two districts; the file masks the second tambon's name
        text = dopa_file([("อำเภอสามร้อยยอด", 100), ("เทศบาลตำบลไร่ใหม่", 30), ("ตำบลไร่ใหม่", 20), ("ตำบล--", 10)], 130)
        got, unplaced = th_dopa.districts(text, "77", self.refs, "t")
        self.assertEqual(unplaced, [])
        self.assertEqual((got["7708"], got["7702"]), (120, 10))

    def test_rows_that_do_not_add_up_stop_the_run(self):
        with self.assertRaises(etl.ParserDriftError):
            th_dopa.districts(dopa_file([("อำเภอสามร้อยยอด", 100)], 101), "77", self.refs, "t")

    def test_unknown_office_stops_the_run(self):
        with self.assertRaises(etl.ParserDriftError):
            th_dopa.districts(dopa_file([("อำเภอไม่มีจริง", 100)], 100), "77", self.refs, "t")


class Vietnam(unittest.TestCase):
    def test_crosswalk_is_63_to_34_whole_provinces(self):
        cw = vn_gso.crosswalk()
        self.assertEqual(len(cw), 63)
        self.assertEqual(len({r["new_slug"] for r in cw}), 34)
        self.assertEqual(len({vn_gso.names(r)[0] for r in cw}), 63)            # no old province listed twice
        merged = {}
        for r in cw:
            merged.setdefault(r["new_slug"], []).append(r["gso_name"])
        self.assertEqual(sorted(merged["ho-chi-minh-city"]), sorted(["TP. Hồ Chí Minh", "Bình Dương", "Bà Rịa - Vũng Tàu"]))
        self.assertEqual(sum(1 for v in merged.values() if len(v) == 1), 11)   # 11 provinces were left as they were

    def test_names_fold_and_alternates(self):
        self.assertEqual(vn_gso.fold("Đắk Lắk"), "daklak")
        self.assertEqual(vn_gso.fold("Ðồng bằng"), "dongbang")                 # U+00D0 as well as U+0110
        hue = next(r for r in vn_gso.crosswalk() if r["new_slug"] == "hue")
        self.assertEqual(vn_gso.names(hue), ["hue", "thuathienhue"])
        self.assertEqual(vn_gso.label(hue), "Thừa Thiên Huế")
        hcm = next(r for r in vn_gso.crosswalk() if r["gso_name"].startswith("TP."))
        self.assertEqual(vn_gso.names(hcm), ["hochiminh"])


def my_raw(pop_scale=1.0, drop_state=None, district="Petaling", lfs_district="Petaling", gdp_total=None, hies_district=None):
    """Tiny OpenDOSM files: 16 states, each 100 people, 50 employed and RM 10 GDP, plus Supra RM 5."""
    st = [s for s in my_dosm.STATES if s != drop_state]
    ov = "both,overall,overall"
    pop = "state,date,sex,age,ethnicity,population\n" + "".join(
        f"{s},{y}-01-01,{ov},{100 * pop_scale if y == 2026 else 100}\n" for s in st for y in (2025, 2026))
    pop += "".join(f"{s},2026-01-01,male,overall,overall,50\n" for s in st)          # breakdown rows are ignored
    pop_my = "date,sex,age,ethnicity,population\n" + "".join(f"{y}-01-01,{ov},{1600}\n" for y in (2025, 2026))
    pop_d = "state,district,date,sex,age,ethnicity,population\n" + "".join(
        f"{s},{district if s == 'Selangor' else s},{y}-01-01,{ov},{100 * pop_scale if y == 2026 else 100}\n" for s in st for y in (2025, 2026))
    lfs = "date,state,lf,lf_employed,lf_unemployed,lf_outside,p_rate,u_rate\n" + "".join(
        f"{q},{s},52,50,2,20,70,3.8\n" for s in st for q in ("2025-04-01", "2026-04-01"))
    lfs_my = "date,lf,lf_employed\n" + "".join(f"{q},832,800\n" for q in ("2025-04-01", "2026-04-01"))
    lfs_d = "state,district,date,lf,lf_employed,lf_unemployed,lf_outside,p_rate,u_rate,ep_ratio\n" + f"Selangor,{lfs_district},2024-01-01,52,50,2,20,70,3.8,68\n"
    lfs_d += "Selangor,{},2023-01-01,,,,,,,\n".format(lfs_district)                     # blank = not published
    gdp = "series,date,state,sector,value\n" + "".join(f"abs,{y}-01-01,{s},p0,{5 if s == 'Supra' else 10}\nabs,{y}-01-01,{s},p5,6\n" for s in st + ["Supra"] for y in (2024, 2025))
    gdp_my = "series,date,sector,value\n" + "".join(f"abs,{y}-01-01,p0,{gdp_total or 165}\n" for y in (2024, 2025))
    hd = hies_district or district
    inc_d = "state,district,date,income_mean,income_median\n" + "".join(f"Selangor,{hd},{y}-01-01,9000,7000\n" for y in (2022, 2024))
    pov_d = "state,district,date,poverty_absolute,poverty_relative\n" + f"Selangor,{hd},2024-01-01,1.5,10\n"
    gini_d = "state,district,date,gini\n" + f"Selangor,{hd},2024-01-01,0.35\n"
    inc_s = "state,date,income_mean,income_median\n" + "".join(f"{s},2024-01-01,9000,7000\n" for s in st + ["Malaysia"])
    return {"pop_state": pop, "pop_my": pop_my, "pop_district": pop_d, "lfs_state": lfs, "lfs_my": lfs_my,
            "lfs_district": lfs_d, "gdp_state": gdp, "gdp_my": gdp_my,
            "inc_district": inc_d, "pov_district": pov_d, "gini_district": gini_d, "inc_state": inc_s}


class Malaysia(unittest.TestCase):
    def test_builds_16_states_and_skips_blank_district_values(self):
        out = my_dosm.build(my_raw())
        self.assertEqual(len(out["states"]), 16)
        sel = out["states"]["selangor"]
        self.assertEqual(sel["series"]["employed"], {"2025-Q2": 50.0, "2026-Q2": 50.0})
        self.assertEqual(sel["districts"][0]["employed"], {"2024": 50.0})
        self.assertEqual(out["supra_gdp"], {"2024": 5.0, "2025": 5.0})

    def test_states_must_add_up_to_the_nation(self):
        with self.assertRaises(etl.ParserDriftError):
            my_dosm.build(my_raw(pop_scale=1.1))               # 2026 states sum to 1,760 against a national 1,600

    def test_gdp_includes_supra_in_the_check(self):
        with self.assertRaises(etl.ParserDriftError):
            my_dosm.build(my_raw(gdp_total=160))              # 16 × 10 without Supra's 5

    def test_a_missing_state_stops_the_run(self):
        with self.assertRaises(etl.ParserDriftError):
            my_dosm.build(my_raw(drop_state="Perlis"))

    def test_district_spellings_are_aliased_or_stop(self):
        out = my_dosm.build(my_raw(district="Ulu Langat", lfs_district="Hulu Langat"))
        self.assertEqual(out["states"]["selangor"]["districts"][0]["name"], "Ulu Langat")
        with self.assertRaises(etl.ParserDriftError):
            my_dosm.build(my_raw(lfs_district="Nowhere"))

    def test_household_survey_spellings_fold_onto_the_district(self):
        out = my_dosm.build(my_raw(district="Seberang Perai Tengah", lfs_district="Seberang Perai Tengah", hies_district="S.P.Tengah"))
        d = out["states"]["selangor"]["districts"][0]
        self.assertEqual((d["income_median"], d["poverty"]), ({"2022": 7000.0, "2024": 7000.0}, {"2024": 1.5}))
        with self.assertRaises(etl.ParserDriftError):
            my_dosm.build(my_raw(hies_district="Nowhere"))

    def test_a_renamed_column_stops_the_run(self):
        raw = my_raw()
        raw["lfs_state"] = raw["lfs_state"].replace("lf_employed", "employed")
        with self.assertRaises(etl.ParserDriftError):
            my_dosm.build(raw)

    def test_quarters(self):
        self.assertEqual(my_dosm.quarter("2026-04-01"), "2026-Q2")
        with self.assertRaises(etl.ParserDriftError):
            my_dosm.quarter("2026-05-01")


def ph_fetched(region_total=30.0):
    """Two regions as PSA lays them out: Metro Manila (two cities) and Central Visayas (Cebu + Cebu City)."""
    places = [(0, "Philippines"), (1, "National Capital Region (NCR)"), (2, "City of Manila"), (2, "Quezon City"),
              (1, "Region VII (Central Visayas)"), (2, "Cebu"), (2, "City of Cebu")]
    gdp = {"Philippines": {"2024": 70.0, "2025": 77.0}, "National Capital Region (NCR)": {"2024": 40.0, "2025": 44.0},
           "City of Manila": {"2024": 15.0, "2025": 16.0}, "Quezon City": {"2024": 25.0, "2025": 28.0},
           "Region VII (Central Visayas)": {"2024": region_total, "2025": 33.0}, "Cebu": {"2024": 20.0, "2025": 22.0},
           "City of Cebu": {"2024": 10.0, "2025": 11.0}}
    pop = {k: {"value": v["2024"] * 1000} for k, v in gdp.items()}
    pop["Philippines"] = {"value": 70000.0}
    return {"gdp_real": (places, gdp), "gdp_nominal": (places, gdp), "pop2020": (places, pop), "pop2024": (places, pop)}


class Philippines(unittest.TestCase):
    def test_footnote_marks_come_off(self):
        self.assertEqual(ph_psa.clean("....Negros Occidental 4/*"), (2, "Negros Occidental"))
        self.assertEqual(ph_psa.clean("....Special Geographic Area 8**"), (2, "Special Geographic Area"))
        self.assertEqual(ph_psa.clean("....City of Isabela (Not a Province) **"), (2, "City of Isabela"))
        self.assertEqual(ph_psa.clean("PHILIPPINES /a")[1], "PHILIPPINES")
        self.assertEqual(ph_psa.clean("....Davao de Oro (Compostela Valley)")[1], "Davao de Oro (Compostela Valley)")

    def test_cities_join_the_province_around_them(self):
        self.assertEqual(ph_psa.unit_of("City of Lapu-Lapu", "regionviicentralvisayas"), "cebu")
        self.assertEqual(ph_psa.unit_of("Pateros", "nationalcapitalregionncr"), "metro-manila")
        self.assertEqual(ph_psa.unit_of("Maguindanao del Sur", "bangsamoroautonomousregioninmuslimmindanaobarmm"), "maguindanao")
        self.assertEqual(ph_psa.unit_of("Samar (Western Samar)", "regionviiieasternvisayas"), "samar")

    def test_units_add_up_and_keep_their_parts(self):
        out = ph_psa.build(ph_fetched())
        self.assertEqual(sorted(out["provinces"]), ["cebu", "metro-manila"])
        cebu = out["provinces"]["cebu"]
        self.assertEqual(cebu["series"]["gdp_real"], {"2024": 30.0, "2025": 33.0})
        self.assertEqual(sorted(cebu["parts"]), ["Cebu", "Cebu City"])
        self.assertEqual(cebu["region"], "Central Visayas")

    def test_places_must_add_up_to_their_region(self):
        with self.assertRaises(etl.ParserDriftError):
            ph_psa.build(ph_fetched(region_total=35.0))


class Words(unittest.TestCase):
    """The plain-English summaries on detail pages (build.py)."""

    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, str(ROOT))
        import build
        cls.b = build

    def r(self, ranks, values=None):
        r = {"name": "X", "rank": 2}
        for k, v in zip(("people", "jobs", "biz", "money"), ranks):
            r[k], r[k + "_rank"] = (values or {}).get(k, 0.01), v
        return r

    def test_ordinals(self):
        self.assertEqual([self.b.ordinal(n) for n in (1, 2, 3, 4, 11, 12, 13, 21, 22, 101, 111)],
                         ["1st", "2nd", "3rd", "4th", "11th", "12th", "13th", "21st", "22nd", "101st", "111th"])

    def test_top_quarter_is_not_called_worst(self):
        text = self.b.brief(self.r([5, 3, 3, 3]), "th", 77, "Thai provinces")
        self.assertIn("top quarter on every lens", text)
        self.assertNotIn("weakest is", text)

    def test_bottom_quarter(self):
        self.assertIn("bottom quarter on every lens", self.b.brief(self.r([60, 70, 75, 77]), "th", 77, "Thai provinces"))

    def test_mixed(self):
        text = self.b.brief(self.r([30, 75, 40, 50], {"jobs": -0.023}), "th", 77, "Thai provinces")
        self.assertIn("strongest lens is registered population growth", text)
        self.assertIn("weakest is formal job growth (−2.3%, 75th)", text)

    def test_meta_description_keeps_whole_sentences(self):
        text = "One short sentence. " + "A much longer second sentence " * 6 + "ends here."
        self.assertEqual(self.b.first_sentences(text, 60), "One short sentence.")


class Summary(unittest.TestCase):
    def test_yearly_staleness_window(self):
        from datetime import date
        from unittest import mock
        dopa = {"years": [2023, 2024]}
        with mock.patch.object(summary, "new", lambda n: dopa if n == "th_dopa.json" else None):
            self.assertEqual(summary.stale(date(2026, 3, 1)), [])           # Dec 2024 is the newest expected
            self.assertEqual(len(summary.stale(date(2026, 8, 1))), 1)       # Dec 2025 overdue from July 2026


    def test_timestamps_are_not_a_change(self):
        a = {"generated_at": "2026-10-01T00:00:00", "latest": "2026-07", "x": [{"generated_at": 1, "v": 2}]}
        b = json.loads(json.dumps(a)); b["generated_at"] = "2026-11-15T03:00:00"; b["x"][0]["generated_at"] = 9
        self.assertEqual(summary.strip_stamps(a), summary.strip_stamps(b))
        b["latest"] = "2026-08"
        self.assertNotEqual(summary.strip_stamps(a), summary.strip_stamps(b))


if __name__ == "__main__":
    unittest.main()
