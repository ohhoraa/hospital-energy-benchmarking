# -*- coding: utf-8 -*-
"""
S1_MB_merge. Multiple-building (MB) integration.

Scope : HIRA match_level == 'CASE101'
        one institution matched to one master building record, which in turn
        covers several member building records -> Multiple Buildings (MB)

Merge order : master building record + HIRA -> CPM -> energy -> weather,
              plus the member building records aggregated to the master record
Primary key : mgm_upper_bld_pk
Output      : '{date} df_MB_merge_before_preprocessing {hira}_{yb}_{ya}.xlsx'

See the header of S1_SB_merge.py for why the two scopes are separate scripts.

The floor summary aggregation is computed per building record by pu_rat.py, so
the master-record value is obtained by summing the member areas and then
recomputing the ratio - not by averaging the ratios.
"""

import os
import numpy as np
import pandas as pd

from common import (
    MODEL_TY_MB_SI, MODEL_TY_MB_MI, YKIHO,
    SCOPE_CFG, step_filename,
    add_totarea_abs_error, add_ct_mri_cnt,
    add_en_ty_and_flag, add_comp_ratio_flag,
)

SCOPE = 'MB'


# =============================================================================
# 0. Settings (injectable from run_all_merge.py)
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
# 1. Raw sources
# =============================================================================
if 'raw_bld_file' not in globals():
    raw_bld_file = 'bld_title_with_upper_delimiter_bar_euckr.txt'
if 'raw_up_bld_file' not in globals():
    raw_up_bld_file = 'bld_recap_title_delimiter_bar_euckr.txt'
if 'raw_purps_path' not in globals():
    raw_purps_path = os.path.join(data_dir, f'{date} pu_rat.txt')

if 'raw_bld' not in globals():
    raw_bld = pd.read_csv(os.path.join(data_dir_in, raw_bld_file),
                          delimiter='|', encoding='cp949')
if 'raw_up_bld' not in globals():
    raw_up_bld = pd.read_csv(os.path.join(data_dir_in, raw_up_bld_file),
                             delimiter='|', encoding='cp949')

if 'raw_purps' not in globals():
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
# 2. Master building records
# =============================================================================
df_up_bld = raw_up_bld.copy()
# The source names this key mgm_bld_pk, exactly as the building records do, so
# it must be renamed to keep the two apart on merging.
df_up_bld = df_up_bld.rename(columns={'mgm_bld_pk': 'mgm_upper_bld_pk'})

col_up_bld = [
    'mgm_upper_bld_pk', 'regstr_gb_cd',
    'sigungu_cd', 'bjdong_cd',
    'plat_area', 'arch_area', 'bc_rat', 'totarea', 'vl_rat_estm_totarea', 'vl_rat',
    'main_purps_cd',
    'main_bld_cnt', 'useapr_day',
]
df_up_bld = df_up_bld.loc[:, col_up_bld]


# =============================================================================
# 3. Member building records (for aggregation)
# =============================================================================
df_bld = raw_bld.copy()
col_bld = [
    'mgm_upper_bld_pk', 'mgm_bld_pk', 'regstr_gb_cd',
    'totarea', 'main_purps_cd',
    'grnd_flr_cnt', 'ugrnd_flr_cnt',
]
df_bld = df_bld.loc[:, col_bld]

df_bld = pd.merge(
    df_bld,
    raw_purps[['mgm_bld_pk', 'flr_main_purps_rat', 'flr_hos_area',
               'flr_tot_area', 'flr_net_area', 'flr_parking_area']],
    on='mgm_bld_pk', how='left',
)


# =============================================================================
# 4. HIRA / CPM / energy / weather
# =============================================================================
fac = pd.read_csv(os.path.join(data_dir, f'after_hira_{hira}.csv'))
pk_cmp = fac[fac['match_level'] == SCOPE_CFG[SCOPE]['match_level']]   # CASE101

energy_pair = pd.read_csv(
    os.path.join(data_dir, f'after_master-energy_{year_b}_{year_a}.csv'),
    encoding='utf-8-sig')
cpm_pair = pd.read_csv(
    os.path.join(data_dir, f'after_master-cpm_{year_b}_{year_a}.csv'),
    encoding='utf-8-sig')

weather = pd.read_csv(os.path.join(data_dir, 'after_weather.csv'),
                      encoding='utf-8-sig')
weather = weather.filter(items=[
    'sigungu_cd', 'bjdong_cd', 'kma_obsrvn_cd', 'kma_obsrvn_nm',
    f'cdd_{year_b}', f'cdd_{year_a}', f'hdd_{year_b}', f'hdd_{year_a}',
])

# For MB the matching table lists several building keys per institution,
# separated by commas, so the column is exploded into rows.
pk_cmp_long = (
    pk_cmp
    .assign(match_mgm_bld_pks=pk_cmp['match_mgm_bld_pks'].str.split(','))
    .explode('match_mgm_bld_pks')
    .assign(match_mgm_bld_pks=lambda x: x['match_mgm_bld_pks'].str.strip())
    .rename(columns={'match_mgm_bld_pks': 'mgm_bld_pk',
                     'match_mgm_upper_bld_pks': 'mgm_upper_bld_pk'})
    .reset_index(drop=True)
)


def merge_upbld(base_df, df_cpm, df_en, df_w, on_key):
    """Merge CPM -> energy -> weather and report the counts at each step."""
    print('\n--- merge ---')

    df = pd.merge(base_df, df_cpm.drop(columns='sido_cd', errors='ignore'),
                  on=on_key, how='inner')
    print(f'after CPM      mgm_upper_bld_pk: {df["mgm_upper_bld_pk"].nunique()} / '
          f'{YKIHO}: {df[YKIHO].nunique()}')

    df = pd.merge(df, df_en, on=on_key, how='inner')
    print(f'after energy   mgm_upper_bld_pk: {df["mgm_upper_bld_pk"].nunique()} / '
          f'{YKIHO}: {df[YKIHO].nunique()}')

    df = pd.merge(df, df_w, on=['sigungu_cd', 'bjdong_cd'], how='left')
    print(f'after weather  mgm_upper_bld_pk: {df["mgm_upper_bld_pk"].nunique()} / '
          f'{YKIHO}: {df[YKIHO].nunique()}')
    return df


# Restrict the master records to those matched by HIRA.
cmp_upbld = df_up_bld[df_up_bld['mgm_upper_bld_pk'].isin(pk_cmp_long['mgm_upper_bld_pk'])]

merge0 = pd.merge(
    cmp_upbld,
    pk_cmp_long.drop(columns='mgm_bld_pk').drop_duplicates(subset=[YKIHO]),
    on='mgm_upper_bld_pk', how='inner',
)
print(f'mgm_upper_bld_pk {merge0["mgm_upper_bld_pk"].nunique()} / '
      f'{YKIHO} {merge0[YKIHO].nunique()}')

df_merge0 = merge_upbld(merge0, cpm_pair, energy_pair, weather,
                        on_key='mgm_upper_bld_pk')


# =============================================================================
# 5. Derived: HIRA
# =============================================================================
hos_per_uppk = df_merge0.groupby('mgm_upper_bld_pk')[YKIHO].nunique()
df_merge0['hos_per_uppk'] = df_merge0['mgm_upper_bld_pk'].map(hos_per_uppk)

df_merge0 = add_ct_mri_cnt(df_merge0)

df_merge0['model_ty'] = np.where(df_merge0['hos_per_uppk'] == 1,
                                 MODEL_TY_MB_SI,
                                 MODEL_TY_MB_MI)


# =============================================================================
# 6. Derived: building register (aggregation of the member records)
# =============================================================================
# Summed floor area of the member records. S2 compares it with the master-record
# value to set totarea_adj.
bld_area_total = df_bld.groupby('mgm_upper_bld_pk')['totarea'].sum()
df_merge0['bld_area_total'] = (df_merge0['mgm_upper_bld_pk']
                               .map(bld_area_total).fillna(0).astype(int))

# Absolute relative error between gfa and gfa_r (master-record values).
df_merge0 = add_totarea_abs_error(df_merge0)

# Floor summary aggregation: sum the member areas, then recompute the ratio.
_g = df_bld.groupby('mgm_upper_bld_pk')
flr_tot_area = _g['flr_tot_area'].sum()            # incl. parking
flr_net_area = _g['flr_net_area'].sum()            # pu_rat denominator
flr_parking_area = _g['flr_parking_area'].sum()    # parking
flr_hos_area = _g['flr_hos_area'].sum()            # medical use
flr_main_purps_rat = ((flr_hos_area / flr_net_area) * 100).fillna(0)

df_merge0['flr_tot_area'] = df_merge0['mgm_upper_bld_pk'].map(flr_tot_area)
df_merge0['flr_net_area'] = df_merge0['mgm_upper_bld_pk'].map(flr_net_area)
df_merge0['flr_parking_area'] = df_merge0['mgm_upper_bld_pk'].map(flr_parking_area)
df_merge0['flr_hos_area'] = df_merge0['mgm_upper_bld_pk'].map(flr_hos_area)
df_merge0['flr_main_purps_rat'] = df_merge0['mgm_upper_bld_pk'].map(flr_main_purps_rat)

# Number of member building records. Used by the above-ground floor check in S2
# to distinguish a genuine floor-count error from a master record with no
# member records at all.
bld_total_cnt = df_bld.groupby('mgm_upper_bld_pk')['mgm_bld_pk'].count()
df_merge0['bld_total_cnt'] = (df_merge0['mgm_upper_bld_pk']
                              .map(bld_total_cnt).fillna(0).astype(int))

# Floor counts: the maximum over the member records, i.e. the tallest block.
# S2 applies the above-ground floor check to this value.
for out_col, src_col in (('grnd_flr_max', 'grnd_flr_cnt'),
                         ('ugrnd_flr_max', 'ugrnd_flr_cnt')):
    s = df_bld.groupby('mgm_upper_bld_pk')[src_col].max()
    df_merge0[out_col] = (df_merge0['mgm_upper_bld_pk']
                          .map(s).fillna(0).astype(int))


# =============================================================================
# 7. Derived: energy
# =============================================================================
df_merge0 = add_en_ty_and_flag(df_merge0, pk_col='mgm_upper_bld_pk',
                               year_b=year_b, year_a=year_a)
df_merge0 = add_comp_ratio_flag(df_merge0, year_b=year_b, year_a=year_a)


# =============================================================================
# 8. Save
# =============================================================================
df_merge0.to_excel(os.path.join(data_dir, datanm_1), index=False)
print(f'\n[save] {datanm_1}')
print(df_merge0['model_ty'].value_counts().to_string())
