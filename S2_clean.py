# -*- coding: utf-8 -*-
"""
S2. Filtering and screening (shared by SB and MB).

The script branches on `scope` ('SB' | 'MB') only; everything else is common.

Two quality-control steps
-------------------------
filtering  = "not comparable"
screening  = "value cannot be trusted"

The number-of-doctors condition is a matter of selecting comparable
institutions, so it belongs to filtering.

Per-scope differences (common.SCOPE_CFG)
----------------------------------------
              SB                     MB
key           mgm_bld_pk             mgm_upper_bld_pk
floor area    totarea_adj (raw)      totarea_adj (after the master vs member
                                     cross-check)
model_ty      SB-SI                  MB-SI
file prefix   df_SB_merge            df_MB_merge

Input  : '{date} df_{scope}_merge_before_preprocessing {hira}_{yb}_{ya}.xlsx'
Output : '{date} df_{scope}_merge_after_outlier {hira}_{yb}_{ya}.xlsx'
"""

import os
import numpy as np
import pandas as pd

from common import (
    MAIN_PURPS_CDS, YKIHO, SCOPE_CFG, step_filename,
    make_counter,
    clean_bc_rat, grnd_flr_invalid, totarea_adj,
    load_manual_exclusions, drop_manual_exclusions,
)

try:
    import counter
    _USE_COUNTER = True
except ImportError:
    _USE_COUNTER = False


# =============================================================================
# 0. Settings (injectable from run_all_merge.py)
# =============================================================================
_BASE_DIR = os.path.dirname(os.path.abspath(__file__))

if 'scope' not in globals():
    scope = 'SB'           # 'SB' | 'MB'

if 'data_dir' not in globals():
    data_dir = os.path.join(_BASE_DIR, 'data_prepared')
if 'date' not in globals():
    date = 260820
if 'hira' not in globals():
    hira = 202003
if 'year_b' not in globals():
    year_b = 2018
if 'year_a' not in globals():
    year_a = 2019

if 'exclusion_csv' not in globals():
    exclusion_csv = os.path.join(_BASE_DIR, 'manual_exclusions.csv')

cfg = SCOPE_CFG[scope]
PK = cfg['pk_col']            # key used for counting
MODEL_TY = cfg['model_ty']    # the single-institution configuration retained

print(f'\n{"=" * 70}\n[S2] scope={scope}  {year_b}_{year_a}\n{"=" * 70}')


def _fn(step):
    """File name for this scope and sub-period."""
    return step_filename(scope, step, date, hira, year_b, year_a)


# Prints both counts (building key and institution) at every step.
print_counts = make_counter(PK)

# Count-table context. counter.log() returns silently without it, which would
# discard every filtering and screening count.
if _USE_COUNTER:
    counter.set_context(scope=scope, year_pair=f'{year_b}_{year_a}')

# S1 output.
df_merge0 = pd.read_excel(os.path.join(data_dir, _fn('before_preprocessing')))

# Institutions to remove in the manual inspection. Both types are removed here;
# they are kept apart so that the log says which finding removed what.
mat_err_list, dist_err_list = load_manual_exclusions(exclusion_csv)


# %% ==========================================================================
# 1. FILTERING
# =============================================================================
def filter_stepwise(df, year_b, year_a):
    """Retain the institutions that can be compared on a common basis.

    The order below is the reporting order: the final count does not depend
    on it, but the intermediate counts do, and they are what the table2 sheet
    of preprocessing_counts.xlsx reports. counter.TABLE2_SPEC lists the same
    steps in the same order and must be kept in step with this function.

    Not counted as filtering steps (baseline)
      - main_purps_cd in {'09000','9000'} : buildings registered for medical use
      - model_ty == single-institution    : the configurations in scope

    Filters
      1) estb_dd < 2018-01-01           data limitation
      2) flr_main_purps_rat >= 75       operational (medical primary use)
      3) regstr_gb_cd == 1              operational (no privately owned units)
      4) site_sum > 20,000 in both years operational (annual energy lower bound)
      5) 30 <= bed_cnt <= 1000          analytic (comparable bed capacity)
      6) tot_dr_cnt > 1                 analytic (number of doctors)
      7) vl_rat_estm_totarea > 1000     analytic (floor area lower bound)
    """
    df_out = df.copy()

    print('[initial]')
    print_counts(df_out, 'after integration')

    # ------------------------------------------------------------- baseline
    print(f'\n### {scope} baseline (not a filtering step) ###')

    # Medical use. The source mixes zero-padded and non-padded codes, so the
    # comparison is made on strings.
    df_out = df_out[df_out['main_purps_cd'].astype(str).isin(MAIN_PURPS_CDS)]
    print_counts(df_out, '--- principal use code retained')

    df_out = df_out[df_out['model_ty'] == MODEL_TY]
    # The console prints the actual value (SB-SI / MB-SI) while the count table
    # keys on a normalised step, so one step stays on one row.
    print_counts(df_out, f'--- model_ty == {MODEL_TY} retained',
                 step='model_ty == single-institution (*-SI) retained')

    # ------------------------------------------- 1) temporal inconsistency
    print('\n### data-limitation filter ###')
    # The building register and the billing records cover the whole study
    # period, but the HIRA snapshot is dated March 2020, so an institution that
    # opened during the period has mismatched reference dates.
    df_out = df_out.copy()
    df_out['estb_dd'] = pd.to_datetime(df_out['estb_dd'], errors='coerce')
    df_out = df_out[df_out['estb_dd'] < pd.Timestamp('2018-01-01')]
    print_counts(df_out, '--- opened on or before 1 January 2018')

    # ------------------------------------------- 2)~3) building register
    print(f'\n### {scope} operational filters (register) ###')

    # pu_rat >= 75%: most of the building energy can be attributed to medical
    # use. The 25% bound follows the ENERGY STAR scoring rule.
    df_out = df_out[df_out['flr_main_purps_rat'] >= 75]
    print_counts(df_out, '--- pu_rat >= 75 retained')

    # regstr_gb_cd 1 = general register, i.e. no privately owned units. With
    # sections owned by outside parties the attribution of energy is unclear.
    df_out = df_out[df_out['regstr_gb_cd'] == 1]
    print_counts(df_out, '--- no privately owned units')

    # ---------------------------------------------------------- 4) energy
    print('\n### operational filter: annual energy ###')
    # Above 20,000 kWh in both years. Below that the building is effectively
    # not in operation, or only part of its metering is captured.
    col_b, col_a = f'site_sum_{year_b}', f'site_sum_{year_a}'
    df_out = df_out[(df_out[col_b] > 20000) & (df_out[col_a] > 20000)]
    print_counts(df_out, '--- annual total energy > 20000 kWh')

    # ------------------------------------------------------------ 5) beds
    print('\n### analytic filters ###')
    # At least 30 beds is the statutory minimum for most inpatient types; at
    # most 1,000 excludes the very largest institutions, which operate at a
    # different scale. Both bounds are one step, so they are applied together.
    df_out = df_out[df_out['bed_cnt'].between(30, 1000)]
    print_counts(df_out, '--- 30 <= bed_cnt <= 1000')

    # --------------------------------------------------------- 6) doctors
    #
    # Basis: Enforcement Rule of the Medical Service Act, Article 38 and
    # Appendix 5 (staffing of medical institutions)
    #   - general hospital / hospital : doctors =
    #       ceil((annual average daily inpatients + outpatients / 3) / 20)
    #   - long-term care hospital     : 2 doctors up to 80 average daily
    #       inpatients, then 1 more per additional 40 (Korean medicine doctors
    #       count towards this)
    #   - Korean medicine and dental hospitals : only one doctor per additional
    #       medical department, so zero is lawful
    # Basis: Enforcement Rule of the Mental Health Act, Appendix 4
    #   - psychiatric hospital : 1 psychiatric specialist per 60 inpatients
    #
    # Inverting the staffing formula, a single doctor is lawful only if
    #     (annual average daily inpatients + outpatients / 3) <= 20,
    # which, even taking outpatients as zero, requires a bed occupancy below
    # 20 / bed_cnt. At the median bed count of this dataset that is an
    # implausibly low occupancy, so "more than one doctor" is a far weaker bound
    # than the statutory requirement: it removes records that contradict the
    # staffing rule without excluding lawfully operating institutions.
    df_out = df_out[df_out['tot_dr_cnt'] > 1]
    print_counts(df_out, '--- tot_dr_cnt > 1')

    # ------------------------------------------------------- 7) floor area
    # Single condition on gfa_r.
    df_out = df_out[df_out['vl_rat_estm_totarea'] > 1000]
    print_counts(df_out, '--- gfa_r > 1000 m2')

    print(f'\n[done] rows after filtering = {len(df_out):,}')
    return df_out


df_merge = filter_stepwise(df_merge0, year_b=year_b, year_a=year_a)


# %% ==========================================================================
# 2. SCREENING
# =============================================================================
# Order: in-range -> out-of-range -> relative comparisons
df = df_merge.copy()

if _USE_COUNTER:
    counter.current_section = 'screening'

print('\n##### screening: building register #####')

# Building coverage ratio: above 100% recompute from footprint / lot area, and
# drop the row if it still exceeds 100%.
df = clean_bc_rat(df)
print_counts(df, '--- bc_rat <= 100 after correction')

# Above-ground floor count: drop when <= 0 or missing.
#   SB holds a single record, so the maximum equals the raw value. For MB an
#   institution is dropped only when every member record is invalid, which is
#   the appropriate judgement at the master-record level. A master record with
#   no member records at all yields grnd_flr_max = 0 and is reported separately,
#   because that is a matching gap rather than a floor-count error.
_n_before = df[PK].nunique()
_bad = grnd_flr_invalid(df['grnd_flr_max'])
if _bad.any():
    print(f'    [check] invalid above-ground floor count: {_bad.sum()} rows '
          f'({df.loc[_bad, PK].nunique()} records)')
    if 'bld_total_cnt' in df.columns:
        print(f'    [check] of which master records with no member records: '
              f'{(df.loc[_bad, "bld_total_cnt"] == 0).sum()}')
df = df[~_bad]
print_counts(df, '--- grnd_flr_max > 0')
print(f'    [check] records removed by the floor-count check = '
      f'{_n_before - df[PK].nunique()}')

# Relative comparison: gfa versus gfa_r.
#   The two differ only by the below-ground and parking areas, so a large
#   discrepancy (a misplaced decimal point, for instance) means they are
#   counting different things.
df = df[df['totarea_abs_error'] < 0.99]
print_counts(df, '--- |gfa - gfa_r| / gfa < 0.99')

# Corrected gross floor area. The rule lives in common.totarea_adj so that
# paper_figure.py applies exactly the same one to the institutions it adds back
# for marking.
df['totarea_adj'] = totarea_adj(df)

print('\n##### screening: HIRA #####')

# Out-of-range: gross floor area per bed (area_bed >= 9.45 m2/bed).
#   Basis: Enforcement Rule of the Medical Service Act, Appendix 4, minimum
#   6.3 m2 net per bed in a multi-bed room, converted to a gross basis with a
#   gross-to-net factor of 1.5. Long-term care hospitals are exempt because
#   that category includes psychiatric hospitals, whose inpatient-room area is
#   governed by the Mental Health Act rule instead.
df = df[
    (df['hos_ty_eng'] == 'CH') |
    ((df['hos_ty_eng'] != 'CH') & ((df['totarea_adj'] / df['bed_cnt']) >= 9.45))
]
print_counts(df, '--- area_bed >= 9.45 (except CH)')

# In-range: the number of clinical departments must be present.
df = df[df['dept_cnt'].notna()]
print_counts(df, '--- dept_cnt present')


print('\n##### screening: energy #####')

# Relative comparison: two-year consumption ratio outside 0.2 - 5.
df = df[df[f'flag_comp_5_{year_b}_{year_a}'] == 0]
print_counts(df, '--- two-year consumption ratio within 0.2-5')

# Relative comparison: the set of energy sources must be the same in both years.
df = df[df[f'flag_en_ty_{year_b}_{year_a}'] == 0]
print_counts(df, '--- identical energy-source composition')

# In-range: electricity must be positive. Every hospital uses electricity, so a
# zero means the metering is incomplete.
_elec_cols = [f'{p}_elec_{y}' for p in ('site', 'pri') for y in (year_b, year_a)]
_keep = np.ones(len(df), dtype=bool)
for c in _elec_cols:
    _keep &= (df[c] > 0).to_numpy() & df[c].notna().to_numpy()
df = df[_keep]
print_counts(df, '--- site_elec > 0')

# In-range: gas and district heating may be zero or missing (the source is
# simply not used), but not negative.
_gh_cols = [f'{p}_{k}_{y}' for p in ('site', 'pri') for k in ('gas', 'heat')
            for y in (year_b, year_a)]
_neg = np.zeros(len(df), dtype=bool)
for c in _gh_cols:
    _neg |= (df[c] < 0).to_numpy()
df = df[~_neg]
print_counts(df, '--- site_gas / site_heat >= 0')

# In-range: the disaggregated cooling, heating and baseload components cannot
# be negative.
cols_sum_zero = [
    f'site_{k}_{e}_{y}'
    for k in ('clg', 'htg', 'base')
    for e in ('e', 'g', 'h')
    for y in (year_b, year_a)
]
df = df[~(df[cols_sum_zero] < 0).any(axis=1)]
print_counts(df, '--- disaggregated components >= 0')


print('\n##### screening: change-point model #####')
# In-range: electricity needs all 24 monthly records across the two years for
# the fit to be trusted.
df = df[df['ns_11'] == 24]
print_counts(df, '--- ns_elec == 24')

# Gas and district heating are seasonal, so 12 records are required rather than 24.
df = df[~(df[['ns_0', 'ns_12', 'ns_13']] < 12).any(axis=1)]
print_counts(df, '--- ns_gas / ns_heat >= 12')

# In-range: a coefficient of determination of zero means the fit failed.
df = df[~(df[['r2_0', 'r2_11', 'r2_12', 'r2_13']] == 0).any(axis=1)]
print_counts(df, '--- CPM R2 > 0')


# %% ==========================================================================
# 3. Manual inspection and save
# =============================================================================
df_screened = df.copy()

if _USE_COUNTER:
    counter.current_section = 'manual_exclusion'

_list_ty_map = {y: 'mat_err' for y in mat_err_list}
_list_ty_map.update({y: 'dist_err' for y in dist_err_list})

df_final = drop_manual_exclusions(df_screened, mat_err_list + dist_err_list,
                                  print_counts=print_counts,
                                  list_ty_map=_list_ty_map)

df_final.to_excel(os.path.join(data_dir, _fn('after_outlier')), index=False)
print(f"[save] {_fn('after_outlier')}")

print(f'\n[S2 done] scope={scope} {year_b}_{year_a} -> '
      f'{PK} {df_final[PK].nunique()} / {YKIHO} {df_final[YKIHO].nunique()}')
