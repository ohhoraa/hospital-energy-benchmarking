# A nationwide building energy benchmarking dataset for medical institutions in South Korea

[![tests](https://github.com/ohhoraa/hospital-energy-benchmarking/actions/workflows/test.yml/badge.svg?branch=main)](https://github.com/ohhoraa/hospital-energy-benchmarking/actions/workflows/test.yml)
[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.22139783.svg)](https://doi.org/10.5281/zenodo.22139783)

Python code that builds an institution-level panel (2018–2021) of South Korean
inpatient medical institutions from three administrative datasets (building
registry, energy consumption, medical institution information) and two DataNet
tables (address-based matching table, station-based degree-day table).

## Requirements

Python 3.10 or later (required by the CPM tool). The released dataset was
generated with Python 3.10.16, pandas 2.2.3, NumPy 1.26.4, SciPy 1.15.3 and
openpyxl 3.1.5.

```
pip install pandas numpy scipy openpyxl matplotlib seaborn
```

The first run downloads the CPM tool (BE-sig) into `third_party/`, which needs
internet access.

## Running it

```
python run_all_merge.py
```

`data_raw/` holds a two-institution sample, so the command runs as is
(`final N = 2`). The run starts with a check that every required source file is
present. Flags at the top of `run_all_merge.py` switch individual stages
(`RUN_*`) and optional outputs (`SAVE_*`) on and off.

## Pipeline

| Step | Script | Input | Output |
|---|---|---|---|
| 1 | `pu_rat.py` | floor summary records | primary-use area ratio per building record |
| 2 | `S0_data_prep.py` | calendarized monthly billing (converted to kWh), HIRA sub-datasets, degree-day table | annual energy, monthly series for the CPMs, one record per institution |
| 3 | `S1_SB_merge.py`, `S1_MB_merge.py` → `cpm_besig.py` | step 2, matching table | integrated tables per configuration, with CPMs fitted and disaggregated |
| 4 | `S2_clean.py` | step 3, `manual_exclusions.csv` | filtered and screened tables |
| 5 | `S3_combine.py` | step 4 | `energy_benchmarking_{N}.csv`, `cpm_results_{N}.csv` |
| 6 | `paper_figure.py`, `eda_validation.py` | step 5 | quality-control and validation figures |

## Change-point models

With `CPM = True` (default; used for the released dataset) the models are fitted
with the CPM tool [5]:

- commit `75c841c0b5f75640679c7ed3db62ef5cce47602b`
- candidate models 1p, 3p_h, 3p_c and 5p; 2p and 4p excluded, as in the DataNet
  project [2]
- multistart optimizer with 10 starting points (seed 0); the model with the
  lowest RMSE (n − p degrees of freedom) is selected
- default parameter bounds: baseload between the minimum and maximum monthly
  consumption, slopes ≥ 0, change-point temperatures between 0 and 25 ℃, and
  for 5p the heating change-point temperature not exceeding the cooling
  change-point temperature
- monthly mean outdoor temperature shipped with the CPM tool, from the same ASOS
  station as the degree days

The baseload, heating and cooling components split the model prediction [1], so
they differ slightly from the measured total. `CPM = False` reads the CPM
results supplied with the source data instead.

`cpm_results_{N}.csv` names the parameters by meaning; the parameter mapping to
the CPM tool's `b0` … `b4`:

| column | 1p | 3p_h | 3p_c | 5p |
|---|---|---|---|---|
| `base` | b0 | b0 | b0 | b0 |
| `htg_slope` | – | b1 | – | b1 |
| `htg_cp` | – | b2 | – | b3 |
| `clg_slope` | – | – | b1 | b2 |
| `clg_cp` | – | – | b2 | b4 |

## Outputs

| File | Contents |
|---|---|
| `data_output/energy_benchmarking_{N}.csv` | the released dataset |
| `data_output/cpm_results_{N}.csv` | model type, parameters and fit statistics per institution (`idx`), subperiod and energy source |
| `data_output/preprocessing_counts.xlsx` | institutions remaining after each filtering and screening step |
| `data_output/column_statistics_{N}.xlsx` | statistics of every released column |
| `figures/` | figures 4–8 of the paper |

Column definitions and table schemas of both CSV files are in `document/`
(`column_dictionary.xlsx`, `table_schema.json`, `cpm_results_schema.json`).

## Source data

The source datasets cannot be redistributed. The repository includes the
metering-unit conversion table (`공통코드.xlsx`) and a two-institution sample of
every source file (one SB-SI and one MB-SI institution) with synthetic monthly
energy values. Exact regeneration of the released dataset requires the versions
used in this study:

- **Building registry** (December 2022 release): Building HUB
  (<https://www.hub.go.kr/portal/opn/lps/idx-lgcpt-pvsn-srvc-list.do>), current
  snapshots only.
- **Energy consumption** (meter-level, calendarized, 2018–2021): available only
  with the approval of the Ministry of Land, Infrastructure and Transport under
  건축물 에너지·온실가스 정보체계 운영규정. Building HUB publishes only lot-level
  electricity and gas totals, which cannot substitute for these records.
- **Medical institution information** (March 2020 release): Public Data Portal
  (<https://www.data.go.kr/en/data/15051059/fileData.do>), current snapshots
  only.
- **DataNet tables**: DataON [3, 4], free registration.

With approval to use these data, the pipeline can be run on the current
releases; the result will differ from the released dataset.

| File in `data_raw/` | Source |
|---|---|
| `bld_title_with_upper_delimiter_bar_euckr.txt` | building registry, building records |
| `bld_recap_title_delimiter_bar_euckr.txt` | building registry, master building records |
| `bld_flr_ouln_delimiter_bar_euckr.txt` | building registry, floor summary records |
| `전국-의료시설-{year}-표제부-사용량.csv` | energy consumption, building records, 2018–2021 |
| `전국-의료시설-{year}-총괄표제부-사용량.csv` | energy consumption, master building records, 2018–2021 |
| `전국-의료시설-(총괄)표제부_CPM.csv` | supplied CPM results (only for `CPM = False`) |
| `공통코드.xlsx` | metering-unit to kWh conversion (included) |
| `1. 병원정보서비스 2020.3.csv`, `3.`, `5.`, `7.`, `8. 의료기관별상세정보서비스(…) 2020.3.csv` | HIRA institutional, facility, department, equipment and meal-service information |
| `전국-의료기관건축물대장매칭.csv` | address-based matching table [3] |
| `데이터넷3_SQI_건축물대장지역별_기상관측지점_매칭.csv`, `데이터넷3_SQI_종관기상관측-월별냉난방도일.csv` | station matching and degree-day table [4] |

## Manual exclusion list

`S2_clean.py` removes the institutions listed in `data_raw/manual_exclusions.csv`
by their institution ID (`ykiho`). The file in this repository lists the five
institutions removed from the released dataset without their IDs, with the
reason for exclusion and `hos_ty_eng`, `gfa`, `bed_cnt` and `site_sum`; it
documents the exclusions but does not reproduce them. For a new run, fill in the
format of `document/manual_exclusions_format.csv`, e.g.

```
ykiho,list_ty,reason_code,note
<institution ID>,mat_err,MATCH_ERR,Matched to a building of a different facility
<institution ID>,dist_err,DIST_OUTLIER,Bed-based intensity is atypical
```

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
   <https://github.com/brainwt/Building-Energy-Signature-aka-CPM>

## Funding

Korea Agency for Infrastructure Technology Advancement (KAIA) grant funded by
the Ministry of Land, Infrastructure and Transport (Grant RS-2023-00244769).

## Citation

> Oh, J. (2026). *Dataset construction pipeline for energy benchmarking of
> South Korean medical institutions* (v2.1.0) [Software]. Zenodo.
> https://doi.org/10.5281/zenodo.22139783

## License

MIT (code only; see `LICENSE`). The source datasets are not redistributed and
remain under their providers' terms.
