# A nationwide building energy benchmarking dataset for medical institutions in South Korea

[![tests](https://github.com/ohhoraa/hospital-energy-benchmarking/actions/workflows/test.yml/badge.svg?branch=main)](https://github.com/ohhoraa/hospital-energy-benchmarking/actions/workflows/test.yml)
[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.22139783.svg)](https://doi.org/10.5281/zenodo.22139783)

Python code that builds the dataset. It integrates four South Korean
administrative datasets — the building registry, energy billing records, medical
institution information and meteorological observations — into an
institution-level panel for 2018–2021.

## Requirements

Python 3.10 or later (required by BE-sig, the change-point model implementation
used with `CPM = True`).

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

With `CPM = True` (the default, see below) the first run downloads the
change-point model implementation, BE-sig, into `third_party/`, which needs
internet access.

## Layout

```
<repo>/
├─ README.md
├─ run_all_merge.py        run the whole pipeline
├─ common.py               shared constants, helpers and file-name rules
├─ cpm_besig.py            change-point models fitted with BE-sig (CPM = True)
├─ counter.py              step-by-step record counts
├─ pu_rat.py               floor summary records -> primary use area ratio
├─ S0_data_prep.py         raw sources -> prepared CSVs
├─ S1_SB_merge.py          single-building integration
├─ S1_MB_merge.py          multiple-building integration
├─ S2_clean.py             filtering and screening
├─ S3_combine.py           combination and release view
├─ paper_figure.py         filtering and manual-check figures
├─ eda_validation.py       technical validation figures
│
├─ data_raw/               source data, as delivered, and
│                          manual_exclusions.csv (see below)
│                          `공통코드.xlsx` is included in this repository;
│                          the rest is not distributed
├─ third_party/            BE-sig at the pinned commit, downloaded on the
│                          first run with CPM = True (not part of this
│                          repository)
├─ data_prepared/          everything the stages hand to one another
│                          (S0 output, pu_rat.txt, df_SB/MB_*, final_*)
├─ data_output/            hospital_energy_benchmarking_{N}.csv
│                          preprocessing_counts.xlsx
│                          column_statistics_{N}.xlsx
├─ figures/                figures (quality-control and validation)
└─ document/               included in this repository:
                           column_dictionary.xlsx and table_schema.json
                           (definitions of the released columns),
                           manual_exclusions_format.csv (template for the
                           manual inspection list, see below)
```

`data_prepared/`, `data_output/` and `figures/` are created on the first run;
only `data_raw/` has to be populated by hand, including the manual exclusion
list (see below).

## Running it

Put the source files in `data_raw/`, then:

```
python run_all_merge.py
```

The run begins with a preflight check of `data_raw/`. It lists every source file
the enabled stages will read, marks each present or missing, and stops before
doing any work if anything is absent.

`pu_rat.py` reads the full floor summary register (about 4 GB), so it is
switched off by default. Set `RUN_PU_RAT = True` for the first run; afterwards
its output (`data_prepared/{DATE} pu_rat.txt`) is reused and the flag can go
back to `False`.

### Change-point models: the `CPM` option

The change-point models (CPM) are used twice: their parameters screen the
energy series in S2 (`ns_*`, `r2_*`), and their split of the consumption gives
the baseload, heating and cooling variables (`site_base`, `site_htg`,
`site_clg` and the primary-energy counterparts). `CPM` at the top of
`run_all_merge.py` sets where they come from.

| `CPM` | change-point models | baseload / heating / cooling |
|---|---|---|
| `True` (default, the released dataset) | fitted in S1 with BE-sig | split of the fitted model's prediction (Kim et al. 2022); adds up to the prediction, so it differs slightly from the measured total |
| `False` | change-point parameters prepared separately | baseload, heating and cooling prepared separately (`use_qty_eb/ec/eh` in the billing source) |

BE-sig settings, fixed in `cpm_besig.py` so that the result is reproducible:

- code: <https://github.com/brainwt/Building-Energy-Signature-aka-CPM>, commit
  `75c841c0b5f75640679c7ed3db62ef5cce47602b`
- candidate models 1P, 3P heating, 3P cooling and 5P; 2P and 4P are excluded,
  as in the DataNet project (Kim et al. 2026)
- model selection by lowest RMSE; multistart optimiser with 10 starting points,
  seed 0
- monthly mean outdoor temperature shipped with BE-sig, from the station of
  the building's legal district (the same station the degree days use)

The stage flags at the top of `run_all_merge.py` (`RUN_S0` … `RUN_S3`,
`RUN_COUNT_EXPORT`, `RUN_PAPER_FIGURE`, `RUN_EDA_VALIDATION`) let individual
stages be re-run without repeating the earlier ones. The `SAVE_*` flags switch
the optional outputs on and off.

### Outputs

| File | Contents |
|---|---|
| `data_output/hospital_energy_benchmarking_{N}.csv` | the released dataset, N institutions x 85 columns (37 variable types) |
| `data_output/column_statistics_{N}.xlsx` | statistics of every column in this release: stored type, maximum length, missing values, distinct values and a sample value |
| `data_output/preprocessing_counts.xlsx` | `counts` sheet: institutions remaining after every filtering and screening step. `table2` sheet: the filtering steps only, in the order they are applied, as institution totals |
| `data_prepared/{DATE} pu_rat.txt` | primary use area ratio per building record |
| `data_prepared/{DATE} pu_rat_log.txt` | pu_rat run log |
| `figures/fig4_filtering_energy_vs_gfa.png` | annual energy against gross floor area, showing the bed and annual-energy bounds |
| `figures/fig5_manual_check_bed_eui_by_type.png` | bed-based EUI against gross floor area by institution type, with the manually excluded institutions marked |
| `figures/fig6_interannual_consistency.png` | site EUI of consecutive years, with a trend line and R2 |
| `figures/fig7_survey_comparison.png` | EUI distribution by institution type against the medians of an independent national survey |
| `figures/fig8_external_benchmarks.png` | EUI distribution of general and tertiary general hospitals against the national benchmark values of other countries |

`data_prepared/` also holds the stage-to-stage `.xlsx` files (`df_SB_merge_*`,
`df_MB_merge_*`, `final_*`) kept for checking.

## Source data

The full source data cannot be redistributed here. The repository ships only
the metering-unit conversion table and a two-institution sample of every source
file (see *Sample data* below). The versions used in this study were provided
directly by the responsible authorities at the start of the project. The table
below lists what `data_raw/` must contain and where each source comes from.

- **Building registry**: distributed through the Building HUB portal
  (<https://www.hub.go.kr/portal/opn/lps/idx-lgcpt-pvsn-srvc-list.do>), which
  provides bulk downloads of current snapshots only; the December 2022 release
  used here is no longer retained. The fields of the three registry files are
  documented at
  <https://github.com/WooilJeong/PublicDataReader/blob/main/assets/docs/portal/BuildingLedger.md>
  (the variable names in this code do not always match the names used there).
- **Energy billing**: the Building HUB portal (same address) publishes only
  lot-level monthly electricity and gas totals, not meter- or building-level
  records. The meter-level records used here are not publicly open; they can be
  obtained only by applying to the Ministry of Land, Infrastructure and
  Transport under 건축물 에너지·온실가스 정보체계 운영규정 and receiving its
  approval.
- **Medical institution information**: published by the Health Insurance
  Review and Assessment Service (HIRA) on the Public Data Portal
  (<https://www.data.go.kr/en/data/15051059/fileData.do>), current snapshots
  only; the March 2020 release used here has been superseded.
- **The two DataNet tables** (matching table and degree-day table): openly
  archived on DataON (references 3 and 4); downloading requires free
  registration.

| File in `data_raw/` | Source |
|---|---|
| `bld_title_with_upper_delimiter_bar_euckr.txt` | Building registry, building records — National Building Energy Integrated Database (Ministry of Land, Infrastructure and Transport / Korea Real Estate Agency) |
| `bld_recap_title_delimiter_bar_euckr.txt` | Building registry, master building records — same source |
| `bld_flr_ouln_delimiter_bar_euckr.txt` | Building registry, floor summary records — same source |
| `전국-의료시설-{year}-표제부-사용량.csv` | Energy billing, building level: monthly consumption after calendarization, one file per year 2018–2021 — same source |
| `전국-의료시설-{year}-총괄표제부-사용량.csv` | Energy billing, master building level: monthly consumption after calendarization, one file per year — same source |
| `전국-의료시설-표제부_CPM.csv` | Change-point model results, building level. Needed only when `CPM = False` |
| `전국-의료시설-총괄표제부_CPM.csv` | Change-point model results, master building level. Needed only when `CPM = False` |
| `공통코드.xlsx` (sheet `에너지 단위`) | Metering-unit to kWh conversion table. **Included in this repository**, so it does not have to be obtained |
| `1. 병원정보서비스 2020.3.csv` | HIRA institutional information |
| `3. 의료기관별상세정보서비스(시설정보) 2020.3.csv` | HIRA facility information (bed counts) |
| `5. 의료기관별상세정보서비스(진료과목정보) 2020.3.csv` | HIRA medical departments |
| `7. 의료기관별상세정보서비스(의료장비정보) 2020.3.csv` | HIRA medical equipment |
| `8. 의료기관별상세정보서비스(식대가산정보) 2020.3.csv` | HIRA meal-service staffing |
| `전국-의료기관건축물대장매칭.csv` | Address-based matching of institutions to building registry records — DataON, *DataNet: Address-Based Matching of Nationwide Medical Institution (Hospital) Data with Building Register Data*, v3.3.0, <https://doi.org/10.22711/idr/1536> |
| `데이터넷3_SQI_건축물대장지역별_기상관측지점_매칭.csv` | Matching of KMA weather stations (ASOS) to legal districts (beopjeong-dong) of the building registry — DataON, *DataNet: Building Registry Regional–ASOS (Synoptic Weather Observation) Station Matching and Monthly Heating/Cooling Degree-Day Dataset (Multiple Calculation Methods)*, v3.3.0, <https://doi.org/10.22711/idr/1537> |
| `데이터넷3_SQI_종관기상관측-월별냉난방도일.csv` | Monthly heating and cooling degree days per KMA weather station (ASOS) — same DataON dataset as the row above, <https://doi.org/10.22711/idr/1537> |

### Sample data

`data_raw/` holds a sample of every source file, so the pipeline can be run end
to end without the full sources. It covers two institutions drawn at random
from the released dataset: one single-building (SB-SI) and one multi-building
(MB-SI) institution. The monthly values in the energy billing files
(`전국-의료시설-{year}-*-사용량.csv`) are synthetic. The sample is meant only
for testing the pipeline.

To build the released dataset, replace the sample files with the full sources.

## What the pipeline does

1. **pu_rat** — from the floor summary records, the share of floor area
   registered for medical use per building record.
   Medical use follows Item 9 (medical facilities) of Attached Table 1 of the
   Enforcement Decree of the Building Act, the classification of buildings by
   use; the Item 3(d) Class I neighbourhood living facilities
   (clinic, dental clinic, Korean medicine clinic, midwifery clinic, postpartum
   care centre) are excluded from the numerator but remain in the denominator.
   Parking is excluded from the denominator wherever it is registered,
   regardless of the floor position. Uses are identified by registered name and
   registered code together, because the register mixes two code systems.
2. **S0** — calendarized monthly billing to annual site and primary energy;
   monthly degree days to annual values; the five HIRA sub-datasets merged into
   one record per institution.
3. **S1** — two-stage, address-based integration, separately for the
   single-building (SB) and multiple-building (MB) configurations. For MB the
   member building records are aggregated to the master record. With
   `CPM = True` the change-point models of the buildings left after the merge
   are fitted here, per sub-period, and the baseload, heating and cooling
   components are replaced with their split.
4. **S2** — the filters, then the screening criteria, then the institutions
   listed in `manual_exclusions.csv`.
5. **S3** — the two scopes concatenated, the two sub-periods joined on the
   institution, and the released view built from that.
6. **paper_figure** — figures for reviewing the filtering and screening steps.
7. **eda_validation** — the interannual consistency and external benchmark
   comparison figures.

## Manual exclusion list

The last step of the quality control is a manual inspection, which removes a
small number of institutions that the automatic rules do not catch. The
pipeline reads them from `data_raw/manual_exclusions.csv`.

That file is not distributed. What ships instead is
`document/manual_exclusions_format.csv`, which carries the header and one
example row per type. **Copy it to `data_raw/manual_exclusions.csv`, delete the
example rows, and enter your own.** The columns are:

| column | meaning |
|---|---|
| `ykiho` | institution identifier, as used throughout the pipeline |
| `list_ty` | what the inspection found: `mat_err` or `dist_err` (see below) |
| `reason_code` | reason category, e.g. `MATCH_ERR`, `PARTIAL_MATCH`, `HIRA_ERR`, `OPERATION_CHANGE`, `MIXED_USE`, `DIST_OUTLIER` |
| `note` | free-text description of the reason; not read by the code |

`list_ty` separates the two findings, both removed at the same step:

| `list_ty` | finding | marked on `fig5` |
|---|---|---|
| `mat_err` | matching error — the institution is linked to a building that belongs to a different facility, or to only part of its own, so its floor area and its energy do not describe the same thing | no |
| `dist_err` | distribution error — the matching is sound, but the institution sits where no operating institution can sit in the joint distributions, so the underlying record is taken to be wrong | yes |

```
ykiho,list_ty,reason_code,note
<institution identifier>,mat_err,MATCH_ERR,Address matching linked the institution to a building that belongs to a different facility.
<institution identifier>,dist_err,DIST_OUTLIER,Bed-based intensity is implausible for an operating institution.
```

Carry out the manual inspection on your own copy of the source data and enter
what it finds.

## Notes

- The released dataset carries no identifiers, addresses, coordinates or
  matching metadata, so institutions cannot be identified from it. Those
  columns exist in the intermediate files, which stay on the machine that runs
  the pipeline.
- Primary energy conversion factors (electricity 2.75, gas 1.1, district
  heating 0.728) are set in `common.PRI_FACTOR`.
- `공통코드.xlsx` supplies the metering-unit to kWh conversion.
- `DATE` in `run_all_merge.py` is stamped on every output file name; change it
  when the outputs of different runs should be kept apart.

## References

1. Kim, D.-W., Ahn, K.-U., Shin, H. & Lee, S.-E. Simplified weather-related
   building energy disaggregation and change-point regression: Heating and
   cooling energy use perspective. *Buildings* **12**, 1717 (2022).
   <https://doi.org/10.3390/buildings12101717>
2. Kim, H.-G. et al. DataNet: linking multi-faceted building energy datasets
   for effective performance analysis at scale. *Energy and Buildings*
   **369**, 117886 (2026). <https://doi.org/10.1016/j.enbuild.2026.117886>
3. Lee, K. & Lee, J. DataNet: Address-Based Matching of Nationwide Medical
   Institution (Hospital) Data with Building Register Data, v3.3.0. *DataON*
   (2026). <https://doi.org/10.22711/idr/1536>
4. Lee, K. & Lee, J. DataNet: Building Registry Regional–ASOS (Synoptic Weather
   Observation) Station Matching and Monthly Heating/Cooling Degree-Day Dataset
   (Multiple Calculation Methods), v3.3.0. *DataON* (2026).
   <https://doi.org/10.22711/idr/1537>
5. Kim, D.-W. brainwt/Building-Energy-Signature-aka-CPM (2025).
   <https://github.com/brainwt/Building-Energy-Signature-aka-CPM> (commit
   `75c841c` is used with `CPM = True`)
6. DataNet research project. <https://datanet.kro.kr/>

## Funding

This work is supported by the Korea Agency for Infrastructure Technology
Advancement (KAIA) grant funded by the Ministry of Land, Infrastructure and
Transport (Grant RS-2023-00244769, Development of a data framework for
integrating building energy datasets and applications to accelerate carbon
neutrality in the building sector).

## Citation

If you use this code, please cite the archived release:

> Oh, J. (2026). *Dataset construction pipeline for energy benchmarking of
> South Korean medical institutions* (v2.0.0) [Software]. Zenodo.
> https://doi.org/10.5281/zenodo.22139783

## License

The code in this repository is released under the MIT License; see `LICENSE`.

This covers the code only. The source datasets are not redistributed here (see
**Source data** above for what each one is and where it is obtained), and each
provider sets its own terms of use.
