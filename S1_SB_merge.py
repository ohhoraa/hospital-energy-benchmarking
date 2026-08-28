# -*- coding: utf-8 -*-
"""
S1_SB_merge. Single-building (SB) integration.

Scope : HIRA match_level == 'CASE102'
        one institution matched to one building register record
        -> Single Building (SB)

Merge order : building record + floor summary (pu_rat) + HIRA
              -> CPM -> energy -> weather
Primary key : mgm_bld_pk
Output      : '{date} df_SB_merge_before_preprocessing {hira}_{yb}_{ya}.xlsx'
              (the file-name rule lives in common.step_filename)

SB and MB are kept as separate scripts because they read different source
files, use different HIRA match levels, and MB additionally aggregates its
member building records. Only the shared helpers live in common.py.
"""

import os
import numpy as np
import pandas as pd

from common import (
    MODEL_TY_SB_SI, MODEL_TY_SB_MI, YKIHO, SCOPE_CFG, step_filename,
    add_totarea_abs_error,
    add_en_ty_and_flag, add_comp_ratio_flag,
)

SCOPE = 'SB'


# =============================================================================
# 0. Settings (injectable from run_all_merge.py)
#    If the name is already in globals() that value is used, so the script runs
#    both standalone and as part of the batch.
# =============================================================================
_BASE_DIR = os.path.dirname(os.path.abspath(__file__))

if 'data_dir_in' not in globals():
    data_dir_in = os.path.join(_BASE_DIR, 'data_raw')
if 'data_dir' not in globals():
    data_dir = os.path.join(_BASE_DIR, 'data_prepared')
os.makedirs(data_dir, exist_ok=True)

if 'date' not in globals():
    date = 260820
if 'hira' not in globals():
    hira = 202003

if 'year_b' not in globals():
    year_b = 2018
if 'year_a' not in globals():
    year_a = 2019

datanm_1 = step_filename(SCOPE, 'before_preprocessing', date, hira, year_b, year_a)


# =============================================================================
# 1. Raw sources (large, so run_all_merge.py caches and injects them)
# =============================================================================
if 'raw_bld_file' not in globals():
    raw_bld_file = 'bld_title_with_upper_delimiter_bar_euckr.txt'
if 'raw_purps_path' not in globals():
    raw_purps_path = os.path.join(data_dir, f'{date} pu_rat.txt')

# Building register, building records (all uses).
if 'raw_bld' not in globals():
    raw_bld = pd.read_csv(os.path.join(data_dir_in, raw_bld_file),
                          delimiter='|', encoding='cp949')

# Floor summary aggregation produced by pu_rat.py.
#   pu_rat = medical-use floor area / (total floor area - parking) * 100
#   Parking is excluded on the basis of the registered use being a car park or
#   a garage, regardless of the floor position.
if 'raw_purps' not in globals():
    # The file carries a header, so columns are selected by name.
    raw_purps = pd.read_csv(raw_purps_path, delimiter='|', encoding='utf-8-sig')
    _need = ['mgm_bld_pk', 'flr_tot_area', 'flr_hos_area',
             'flr_parking_area', 'flr_net_area', 'flr_main_purps_rat']
    _miss = [c for c in _need if c not in raw_purps.columns]
    if _miss:
        raise KeyError(
            f'Columns missing from the pu_rat output: {_miss}\n'
            f'  actual columns: {list(raw_purps.columns)}\n'
            f'  -> re-run pu_rat.py (RUN_PU_RAT = True in run_all_merge.py).'
        )
    raw_purps = raw_purps[_need]


# =============================================================================
# 2. Building records
# =============================================================================
df_bld = raw_bld.copy()

col_bld = [
    'mgm_upper_bld_pk', 'mgm_bld_pk', 'regstr_gb_cd',
    'sigungu_cd', 'bjdong_cd',
    'plat_area', 'arch_area', 'bc_rat', 'totarea', 'vl_rat_estm_totarea', 'vl_rat',
    'main_purps_cd',
    'grnd_flr_cnt', 'ugrnd_flr_cnt',
    'useapr_day',
]
df_bld = df_bld.loc[:, col_bld]

# Attach the floor summary aggregation.
df_bld = pd.merge(
    df_bld,
    raw_purps[['mgm_bld_pk', 'flr_main_purps_rat', 'flr_hos_area',
               'flr_tot_area', 'flr_net_area', 'flr_parking_area']],
    on='mgm_bld_pk', how='left',
)


# =============================================================================
# 3. HIRA / CPM / energy / weather
# =============================================================================
fac = pd.read_csv(os.path.join(data_dir, f'after_hira_{hira}.csv'))
pk_ind = fac[fac['match_level'] == SCOPE_CFG[SCOPE]['match_level']]   # CASE102

energy_pair = pd.read_csv(
    os.path.join(data_dir, f'after_building-energy_{year_b}_{year_a}.csv'),
    encoding='utf-8-sig')
cpm_pair = pd.read_csv(
    os.path.join(data_dir, f'after_building-cpm_{year_b}_{year_a}.csv'),
    encoding='utf-8-sig')

weather = pd.read_csv(os.path.join(data_dir, 'after_weather.csv'),
                      encoding='utf-8-sig')
weather = weather.filter(items=[
    'sigungu_cd', 'bjdong_cd', 'kma_obsrvn_cd', 'kma_obsrvn_nm',
    f'cdd_{year_b}', f'cdd_{year_a}', f'hdd_{year_b}', f'hdd_{year_a}',
])

# SB matches a single building record, so no long reshape is needed.
pk_ind_long = pk_ind.rename(columns={
    'match_mgm_bld_pks': 'mgm_bld_pk',
    'match_mgm_upper_bld_pks': 'mgm_upper_bld_pk',
})


def merge_bld(base_df, df_cpm, df_en, df_w, on_key):
    """Merge CPM -> energy -> weather and report the counts at each step.

    CPM and energy are inner joins (an institution without both cannot be
    analysed); weather is a left join, since it matches on region and is always
    available.
    """
    print('\n--- merge ---')

    df = pd.merge(base_df, df_cpm.drop(columns='sido_cd', errors='ignore'),
                  on=on_key, how='inner')
    print(f'after CPM      mgm_bld_pk: {df["mgm_bld_pk"].nunique()} / '
          f'{YKIHO}: {df[YKIHO].nunique()}')

    df = pd.merge(df, df_en, on=on_key, how='inner')
    print(f'after energy   mgm_bld_pk: {df["mgm_bld_pk"].nunique()} / '
          f'{YKIHO}: {df[YKIHO].nunique()}')

    df = pd.merge(df, df_w, on=['sigungu_cd', 'bjdong_cd'], how='left')
    print(f'after weather  mgm_bld_pk: {df["mgm_bld_pk"].nunique()} / '
          f'{YKIHO}: {df[YKIHO].nunique()}')
    return df


# Building records + HIRA
merge0 = pd.merge(
    df_bld,
    pk_ind_long.drop(columns='mgm_upper_bld_pk').drop_duplicates(subset=[YKIHO]),
    on='mgm_bld_pk', how='inner',
)
print(f'mgm_bld_pk {merge0["mgm_bld_pk"].nunique()} / '
      f'{YKIHO} {merge0[YKIHO].nunique()}')

df_merge0 = merge_bld(merge0, cpm_pair, energy_pair, weather, on_key='mgm_bld_pk')


# =============================================================================
# 4. Derived: HIRA
# =============================================================================
# Institutions per building record -> basis for SB-SI / SB-MI.
hos_per_pk = df_merge0.groupby('mgm_bld_pk')[YKIHO].nunique()
df_merge0['hos_per_pk'] = df_merge0['mgm_bld_pk'].map(hos_per_pk)

# Building-institution configuration.
df_merge0['model_ty'] = np.where(df_merge0['hos_per_pk'] == 1,
                                 MODEL_TY_SB_SI,
                                 MODEL_TY_SB_MI)


# =============================================================================
# 5. Derived: building register
# =============================================================================
# Absolute relative error between gfa and gfa_r (S2 removes rows >= 0.99).
df_merge0 = add_totarea_abs_error(df_merge0)

# Floor-count variable names.
#   SB holds a single record, so the maximum equals the raw value. Using the
#   same names as the MB aggregation lets S2 be a single script.
df_merge0 = df_merge0.rename(columns={
    'grnd_flr_cnt': 'grnd_flr_max',
    'ugrnd_flr_cnt': 'ugrnd_flr_max',
})


# =============================================================================
# 6. Derived: energy
# =============================================================================
# Energy-source combination and its two-year agreement flag.
df_merge0 = add_en_ty_and_flag(df_merge0, pk_col='mgm_bld_pk',
                               year_b=year_b, year_a=year_a)
# Two-year consumption ratio and its outlier flag.
df_merge0 = add_comp_ratio_flag(df_merge0, year_b=year_b, year_a=year_a)


# =============================================================================
# 7. Save
# =============================================================================
df_merge0.to_excel(os.path.join(data_dir, datanm_1), index=False)
print(f'\n[save] {datanm_1}')
print(df_merge0['model_ty'].value_counts().to_string())
