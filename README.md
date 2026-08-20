# A nationwide building energy benchmarking dataset for medical institutions in South Korea

Python code that builds the dataset. It integrates four South Korean
administrative datasets — the building registry, energy billing records, medical
institution information and meteorological observations — into an
institution-level panel for 2018–2021.

## Requirements

Python 3.9 or later.

```
pandas
numpy
openpyxl        # reading and writing .xlsx
matplotlib
seaborn
scipy
```

```
pip install pandas numpy openpyxl matplotlib seaborn scipy
```

## Layout

```
<repo>/
├─ README.md
├─ run_all_merge.py        run the whole pipeline
├─ common.py               shared constants, helpers and file-name rules
├─ counter.py              step-by-step record counts
├─ pu_rat.py               floor summary records -> primary use area ratio
├─ S0_data_prep.py         raw sources -> prepared CSVs
├─ S1_SB_merge.py          single-building integration
├─ S1_MB_merge.py          multiple-building integration
├─ S2_clean.py             filtering and screening
├─ S3_combine.py           combination and release view
├─ paper_figure.py         filtering and manual-check figures
├─ eda_validation.py       technical validation figures
├─ manual_exclusions.csv   the manual distribution check (see below)
│
├─ data_raw/               source data, as delivered (see below)
│                          `공통코드.xlsx` is included in this repository;
│                          the rest is not distributed
├─ data_prepared/          everything the stages hand to one another
│                          (S0 output, pu_rat.txt, df_SB/MB_*, final_*)
├─ data_output/            hospital_energy_benchmarking_{N}.csv
│                          column_dictionary_{N}.xlsx
│                          preprocessing_counts.xlsx
└─ figures/                figures (quality-control and validation)
```

`data_prepared/`, `data_output/` and `figures/` are created on the first run;
only `data_raw/` has to be populated by hand.

## Running it

Put the source files in `data_raw/`, then:

```
python run_all_merge.py
```

The run begins with a preflight check of `data_raw/`. It lists every source file
the enabled stages will read, marks each present or missing, and stops before
doing any work if anything is absent — so a missing file surfaces immediately
rather than hours in. Only the stages switched on are checked, so re-running a
later stage on its own does not demand sources it will never open.

`pu_rat.py` reads the full floor summary register (about 4 GB), so it is
switched off by default. Set `RUN_PU_RAT = True` for the first run; afterwards
its output (`data_prepared/{DATE} pu_rat.txt`) is reused and the flag can go
back to `False`.

The stage flags at the top of `run_all_merge.py` (`RUN_S0` … `RUN_S3`,
`RUN_COUNT_EXPORT`, `RUN_PAPER_FIGURE`, `RUN_EDA_VALIDATION`) let individual
stages be re-run
without repeating the earlier ones. The `SAVE_*` flags switch the optional
outputs on and off; the files the stages hand to one another
(`before_preprocessing`, `after_outlier`, `final_*`) are always written.

### Outputs

| File | Contents |
|---|---|
| `data_output/hospital_energy_benchmarking_{N}.csv` | the released dataset, N institutions x 85 columns (37 variable types) |
| `data_output/column_dictionary_{N}.xlsx` | column dictionary of the released file |
| `data_output/preprocessing_counts.xlsx` | `counts` sheet: institutions remaining after every filtering and screening step. `table2` sheet: the filtering steps only, in the order they are applied, as institution totals |
| `data_prepared/{DATE} pu_rat.txt` | primary use area ratio per building record |
| `data_prepared/{DATE} pu_rat_log.txt` | pu_rat run log |
| `figures/fig4_filtering_energy_vs_gfa.png` | annual energy against gross floor area, showing the bed and annual-energy bounds |
| `figures/fig5_manual_check_bed_eui_by_type.png` | bed-based EUI against gross floor area by institution type, with the manually excluded institutions marked |
| `figures/fig6_interannual_consistency.png` | site EUI of consecutive years, with a trend line and R2 |
| `figures/fig7_survey_comparison.png` | EUI distribution by institution type against the medians of an independent national survey |
| `figures/fig8_external_benchmarks.png` | EUI distribution of general and tertiary general hospitals against the national benchmark values of other countries |

`data_prepared/` also holds the stage-to-stage `.xlsx` files
(`df_SB_merge_*`, `df_MB_merge_*`, `final_*`) and the S0 CSVs.

## Source data

The source data cannot be redistributed here, with one exception noted in the
table. The versions used in this study were provided directly by the
responsible authorities at the start of the project, and for three of the four
sources those versions are no longer obtainable from the public portals. The
table below lists what `data_raw/` must contain and where each source comes from.

The structure and the column composition of the three building registry files
(building records, master building records, floor summary records) are
documented in detail at
<https://github.com/WooilJeong/PublicDataReader/blob/main/assets/docs/portal/BuildingLedger.md>.
That page is the most convenient reference for what each field means. Note that
the variable names declared in this code do not always match the names used
there.

| File in `data_raw/` | Source |
|---|---|
| `bld_title_with_upper_delimiter_bar_euckr.txt` | Building registry, building records — National Building Energy Integrated Database (Ministry of Land, Infrastructure and Transport / Korea Real Estate Agency) |
| `bld_recap_title_delimiter_bar_euckr.txt` | Building registry, master building records — same source |
| `bld_flr_ouln_delimiter_bar_euckr.txt` | Building registry, floor summary records — same source |
| `전국-의료시설-{year}-표제부-사용량.csv` | Energy billing, building level, one file per year 2018–2021 — same source |
| `전국-의료시설-{year}-총괄표제부-사용량.csv` | Energy billing, master building level, one file per year — same source |
| `전국-의료시설-표제부-KICT_CPM.csv` | Change-point model results, building level |
| `전국-의료시설-총괄표제부-KICT_CPM.csv` | Change-point model results, master building level |
| `공통코드.xlsx` (sheet `에너지 단위`) | Metering-unit to kWh conversion table. **Included in this repository**, so it does not have to be obtained |
| `1. 병원정보서비스 2020.3.csv` | HIRA institutional information |
| `3. 의료기관별상세정보서비스(시설정보) 2020.3.csv` | HIRA facility information (bed counts) |
| `5. 의료기관별상세정보서비스(진료과목정보) 2020.3.csv` | HIRA medical departments |
| `7. 의료기관별상세정보서비스(의료장비정보) 2020.3.csv` | HIRA medical equipment |
| `8. 의료기관별상세정보서비스(식대가산정보) 2020.3.csv` | HIRA meal-service staffing |
| `전국-의료기관건축물대장매칭.csv` | Address-based matching of institutions to building registry records — available on the DataOn portal |
| `데이터넷3_SQI_건축물대장지역별_기상관측지점_매칭.csv` | Station-to-district matching — available on the DataOn portal |
| `데이터넷3_SQI_종관기상관측-월별냉난방도일.csv` | Monthly heating and cooling degree days per station — available on the DataOn portal |

The Korean file names are kept as delivered, so that the code matches the files
as they are received.

Two of the inputs are secondary datasets produced within the wider project and
are openly available on the DataOn portal: the station-based monthly degree-day
dataset with its station-to-district matching, and the address-based table
matching institution records to building registry records.

The change-point modelling tool used to calendarize and disaggregate the
monthly billing records is third-party software and is not part of this
repository. `S0_data_prep.py` reads its output, so the pipeline does not need
to re-run it.

## What the pipeline does

1. **pu_rat** — from the floor summary records, the share of floor area
   registered for medical use per building record.
   Medical use follows Table 1, Item 9 of the Enforcement Decree of the
   Building Act; the Item 3(d) Class I neighbourhood living facilities
   (clinic, dental clinic, Korean medicine clinic, midwifery clinic, postpartum
   care centre) are excluded from the numerator but remain in the denominator.
   Parking is excluded from the denominator wherever it is registered,
   regardless of the floor position. Uses are identified by registered name and
   registered code together, because the register mixes two code systems.
2. **S0** — calendarized monthly billing to annual site and primary energy;
   change-point model results reshaped by energy source; monthly degree days to
   annual values; the five HIRA sub-datasets merged into one record per
   institution.
3. **S1** — two-stage, address-based integration, separately for the
   single-building (SB) and multiple-building (MB) configurations. For MB the
   member building records are aggregated to the master record.
4. **S2** — the filters, then the screening criteria, then the institutions
   listed in `manual_exclusions.csv`.
5. **S3** — the two scopes concatenated, the two sub-periods joined on the
   institution, and the released view built from that.
6. **paper_figure** — two figures documenting the quality control: the
   annual-energy against floor-area scatter that the bed and energy bounds are
   read from, and the bed-based EUI scatter by institution type used for the
   manual distribution check. The first starts from
   `final_before_preprocessing` and applies the two baseline conditions, so it
   shows the population the filtering table starts from; the second uses the
   final dataset and adds the manually excluded institutions back so that they
   can be marked.
7. **eda_validation** — the interannual consistency and external benchmark
   comparison figures.

Every count printed along the way is accumulated in
`preprocessing_counts.xlsx`.

## Manual exclusion list

The last step of the quality control is a manual inspection, which removes a
small number of institutions that the automatic rules do not catch.
`manual_exclusions.csv` is where those institutions are declared:

| column | meaning |
|---|---|
| `ykiho` | institution identifier, as used throughout the pipeline |
| `list_ty` | what the inspection found: `mat_err` or `dist_err` (see below) |
| `reason_code` | reason category, e.g. `MATCH_ERR`, `PARTIAL_MATCH`, `HIRA_ERR`, `OPERATION_CHANGE`, `MIXED_USE`, `DIST_OUTLIER` |
| `reason_en` | one sentence describing the reason |
| `note_ko` | free-text note; not read by the code |

`list_ty` separates the two findings. Both are removed at the same step, but
they are read off different views and only one of them can be shown on the
distribution figure:

| `list_ty` | finding | marked on `fig5` |
|---|---|---|
| `mat_err` | matching error — the institution is linked to a building that belongs to a different facility, or to only part of its own, so its floor area and its energy do not describe the same thing | no |
| `dist_err` | distribution error — the matching is sound, but the institution sits where no operating institution can sit in the joint distributions, so the underlying record is taken to be wrong | yes |

`paper_figure.py` marks the `dist_err` entries (PO1, PO2, ...) because that
figure is the view they were found on. The `mat_err` entries carry no meaning on
those axes, so they are left out of the figure.

```
ykiho,list_ty,reason_code,reason_en,note_ko
<institution identifier>,mat_err,MATCH_ERR,Address matching linked the institution to a building that belongs to a different facility.,
<institution identifier>,dist_err,DIST_OUTLIER,Bed-based intensity is implausible for an operating institution.,
```

The file shipped here is a **template with one example row per type**. The
identifier is a pseudonymous key that can be resolved to a named institution
through public health-insurance data, so no real identifiers are distributed
with the code. Carry out the manual check on your own copy of the source data
and enter your own rows; with the template as supplied this step removes
nothing, and the resulting record count is correspondingly higher.

## Notes

- The released dataset carries no identifiers, addresses, coordinates or
  matching metadata, so institutions cannot be identified from it. Those
  columns exist in the intermediate files, which stay on the machine that runs
  the pipeline.
- Primary energy conversion factors (electricity 2.75, gas 1.1, district
  heating 0.728) are set in `common.PRI_FACTOR`, not in `공통코드.xlsx`; that
  file supplies only the metering-unit to kWh conversion.
- `DATE` in `run_all_merge.py` is stamped on every output file name. Raise it
  when re-running with a changed definition, otherwise the previous outputs are
  overwritten in place.
- The scripts are executed with `runpy` from `run_all_merge.py`, which injects
  the paths and the sub-period into each script's globals. Each script also
  runs standalone, falling back to the defaults at the top of its file.
