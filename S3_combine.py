# -*- coding: utf-8 -*-
"""
S3. Combination and release view.

Part A. Concatenate the scopes : SB + MB row-wise, per sub-period and stage
                                 -> '{date} final_{step} {hira}_{yb}_{ya}.xlsx'
Part B. Join the sub-periods   : 2018_2019 inner join 2020_2021 on the
                                 institution key
                                 -> '{date} final_{step} {hira}_all.xlsx'
Part C. Release view           : from after_outlier, the released CSV with the
                                 released variable names, plus its column
                                 dictionary -> data_output/

Parts A and B write to data_prepared/; Part C writes to data_output/.

Variable naming
---------------
Parts A and B do not rename anything: the pipeline keeps the source column
names throughout (totarea_adj, vl_rat_estm_totarea and so on). The released
names (gfa, gfa_r, ...) are applied only in the Part C release view.

totarea_adj is created during S2 screening, so it does not exist in the
before_preprocessing files. Part C uses after_outlier only.
"""

import os
import re
import pandas as pd

from common import YKIHO, SCOPES, STEPS, step_filename, final_filename

try:
    import counter
    _USE_COUNTER = True
except ImportError:
    _USE_COUNTER = False


# =============================================================================
# 0. Settings (injectable from run_all_merge.py)
# =============================================================================
_BASE_DIR = os.path.dirname(os.path.abspath(__file__))

if 'data_dir' not in globals():
    data_dir = os.path.join(_BASE_DIR, 'data_prepared')
if 'output_dir' not in globals():
    output_dir = os.path.join(_BASE_DIR, 'data_output')
os.makedirs(output_dir, exist_ok=True)
if 'date' not in globals():
    date = 260820
if 'hira' not in globals():
    hira = 202003

if 'year_pairs' not in globals():
    year_pairs = [(2018, 2019), (2020, 2021)]

# Optional outputs. The stage-to-stage files (final_*) are always written.
if 'save_release_csv' not in globals():
    save_release_csv = True
if 'save_column_dict' not in globals():
    save_column_dict = True


# =============================================================================
# 1. Column dictionary
# =============================================================================
def build_column_dictionary(dataframe):
    """Return a column dictionary for the released file.

    Columns: idx / name / description (blank) / dtype / max length /
             nullable / null count / distinct count / sample / note (blank).
    Descriptions and notes are filled in by hand for the data repository.
    """
    rows = []
    for i, col in enumerate(dataframe.columns):
        s = dataframe[col]
        non_null = s.dropna()
        max_len = int(non_null.astype(str).str.len().max()) if len(non_null) else 0
        rows.append({
            'idx': i,
            'column': col,
            'description': '',
            'dtype': str(s.dtype),
            'max_length': max_len,
            'nullable': 'Y' if s.isnull().any() else 'N',
            'null_count': int(s.isnull().sum()),
            'distinct_count': int(s.nunique(dropna=True)),
            'sample': s.iloc[0] if len(s) else None,
            'note': '',
        })
    return pd.DataFrame(rows, columns=[
        'idx', 'column', 'description', 'dtype', 'max_length',
        'nullable', 'null_count', 'distinct_count', 'sample', 'note',
    ])


def save_column_dictionary(dataframe, save_path):
    build_column_dictionary(dataframe).to_excel(save_path, index=False)
    print(f'[save] {os.path.basename(save_path)}')
    return save_path


# =============================================================================
# 2. Part A - concatenate the scopes
# =============================================================================
print(f'\n{"=" * 70}\n[S3] Part A: SB + MB concatenation\n{"=" * 70}')

for year_b, year_a in year_pairs:
    pair = f'{year_b}_{year_a}'

    for step in STEPS:
        frames = []
        missing = []
        for scope in SCOPES:
            fp = os.path.join(data_dir, step_filename(scope, step, date, hira,
                                                      year_b, year_a))
            if not os.path.exists(fp):
                missing.append(os.path.basename(fp))
                continue
            frames.append(pd.read_excel(fp))

        if missing:
            print(f'[skip] {pair} / {step}: missing input -> {missing}')
            continue

        merged = pd.concat(frames, axis=0, ignore_index=True)
        out_nm = final_filename(step, date, hira, pair)
        merged.to_excel(os.path.join(data_dir, out_nm), index=False)
        print(f'  {pair} / {step:<22} -> {len(merged):,} rows  ({out_nm})')

        if _USE_COUNTER and step == 'after_outlier':
            counter.log_merge_step(
                label=f'SB+MB concatenation ({pair})',
                total_inst=merged[YKIHO].nunique(dropna=True),
                note='row-wise concatenation of the two scopes',
            )


# =============================================================================
# 3. Part B - join the sub-periods
# =============================================================================
print(f'\n{"=" * 70}\n[S3] Part B: sub-period inner join\n{"=" * 70}')


# Columns whose values differ between sub-periods although their names carry no
# year. The change-point model outputs are suffixed by energy source only
# (ns_11, r2_0, ...) and the fitting period (date_s, date_e) differs by
# sub-period, so a sub-period suffix is added before the join to keep both.
# Every other unsuffixed column (register and HIRA attributes, totarea_adj,
# flr_*) has the same value in both sub-periods and is de-duplicated.
CPM_BASES = ('cpm_ty', 'b0', 'b1', 'b2', 'b3', 'b4',
             'ns', 'cvrmse', 'rmse', 'nmbe', 'r2', 'r2_l', 'r2_r')
_CPM_RE = re.compile(r'^(' + '|'.join(CPM_BASES) + r')_\d+$')


def pair_specific_cols(df):
    """Columns that need a sub-period suffix (CPM values and fitting period)."""
    return [c for c in df.columns
            if _CPM_RE.match(str(c)) or str(c) in ('date_s', 'date_e')]


def add_pair_suffix(df, pair):
    """Append _{year_b}_{year_a} to the CPM columns."""
    cols = pair_specific_cols(df)
    return df.rename(columns={c: f'{c}_{pair}' for c in cols}), len(cols)


def merge_year_pairs(df1, df2, pair1, pair2, key=YKIHO):
    """Inner join the two sub-period frames on the institution key.

    1) Suffix the CPM columns so that both sub-periods are preserved.
    2) Drop the remaining duplicated names from df2, which would otherwise
       produce _x/_y suffixes. Those columns are sub-period invariant, so df1
       is kept as the representative.
    """
    d1, n1 = add_pair_suffix(df1, pair1)
    d2, n2 = add_pair_suffix(df2, pair2)
    if n1 or n2:
        print(f'    sub-period suffix applied to {n1}/{n2} CPM columns '
              f'({pair1} / {pair2})')

    common_cols = [c for c in d1.columns if c in d2.columns and c != key]
    return pd.merge(d1, d2.drop(columns=common_cols), how='inner', on=key)


for step in STEPS:
    fps = [os.path.join(data_dir, final_filename(step, date, hira, f'{b}_{a}'))
           for b, a in year_pairs]
    if not all(os.path.exists(fp) for fp in fps):
        print(f'[skip] {step}: sub-period files missing, no _all file written')
        continue

    df1, df2 = (pd.read_excel(fp) for fp in fps)
    _p1, _p2 = (f'{b}_{a}' for b, a in year_pairs)
    merged = merge_year_pairs(df1, df2, _p1, _p2)

    out_nm = final_filename(step, date, hira, 'all')
    merged.to_excel(os.path.join(data_dir, out_nm), index=False)
    print(f'  {step:<22} {len(df1):,} n {len(df2):,} -> {len(merged):,} rows  '
          f'({out_nm})')

    if _USE_COUNTER and step == 'after_outlier':
        counter.log_merge_step(
            label='2018-2019 inner join 2020-2021',
            total_inst=merged[YKIHO].nunique(dropna=True),
            note='inner join on the institution key',
        )


# =============================================================================
# 4. Part C - release view
# =============================================================================
# RELEASE_COLS : pipeline column name -> released column name.
#   - Renamed for the release: gfa, gfa_r, pu_rat, footprint_area, fa_rat,
#     open_ymd, doctor_cnt.
#   - Everything else keeps its source name.
#   - cl_cd_nm is not released: it is the Korean-language institution type
#     name and maps one to one onto hos_ty_eng, so it carries no extra
#     information.
#   - Identifiers, addresses, coordinates and matching metadata are not
#     released, so that institutions cannot be identified.
print(f'\n{"=" * 70}\n[S3] Part C: release view\n{"=" * 70}')

RELEASE_COLS = {
    # -- building configuration / register
    'model_ty': 'model_ty',
    'plat_area': 'plat_area',
    'arch_area': 'footprint_area',
    'bc_rat': 'bc_rat',
    'vl_rat': 'fa_rat',
    'totarea_adj': 'gfa',                  # corrected gross floor area
    'vl_rat_estm_totarea': 'gfa_r',        # gross floor area for the floor-area ratio
    'grnd_flr_max': 'grnd_flr_max',
    'ugrnd_flr_max': 'ugrnd_flr_max',

    # -- from the floor summary records
    'flr_main_purps_rat': 'pu_rat',
    'flr_hos_area': 'flr_hos_area',
    'flr_net_area': 'flr_net_area',        # pu_rat denominator

    # -- HIRA
    'hos_ty_eng': 'hos_ty_eng',            # institution type (GH/H/CH/KH/TH)
    'estb_dd': 'open_ymd',                 # opening date
    'dept_cnt': 'dept_cnt',
    'bed_cnt': 'bed_cnt',
    'tot_dr_cnt': 'doctor_cnt',            # total number of doctors
    'ct_cnt': 'ct_cnt',
    'mri_cnt': 'mri_cnt',
    'diet_cnt': 'diet_cnt',
    'cook_cnt': 'cook_cnt',
}

# -- 14 energy variables x 4 years (names unchanged)
_EN_KINDS = ['sum', 'elec', 'gas', 'heat', 'clg', 'htg', 'base']
for _p in ('site', 'pri'):
    for _k in _EN_KINDS:
        for _y in (2018, 2019, 2020, 2021):
            RELEASE_COLS[f'{_p}_{_k}_{_y}'] = f'{_p}_{_k}_{_y}'

# -- 2 degree-day variables x 4 years
for _k in ('hdd', 'cdd'):
    for _y in (2018, 2019, 2020, 2021):
        RELEASE_COLS[f'{_k}_{_y}'] = f'{_k}_{_y}'

# Number of variable types in the released file.
RELEASE_N_TYPES_EXPECTED = 37

_n_nonenergy = sum(
    1 for k in RELEASE_COLS
    if not any(k.startswith(p) for p in ('site_', 'pri_', 'hdd_', 'cdd_'))
)
_n_types = _n_nonenergy + len(_EN_KINDS) * 2 + 2
print(f'[release] columns = {len(RELEASE_COLS)} (year suffixes included)')
print(f'[release] variable types = {_n_types} '
      f'(non-energy {_n_nonenergy} + energy {len(_EN_KINDS) * 2} + degree days 2)')
if _n_types != RELEASE_N_TYPES_EXPECTED:
    print(f'  WARNING: {_n_types - RELEASE_N_TYPES_EXPECTED:+d} against the '
          f'expected {RELEASE_N_TYPES_EXPECTED} - check RELEASE_COLS.')
else:
    print(f'  variable types confirmed ({_n_types})')


def build_release_view(df):
    """Keep the RELEASE_COLS columns and rename them to the released names."""
    missing = [c for c in RELEASE_COLS if c not in df.columns]
    if missing:
        print(f'[release] {len(missing)} column(s) absent from the input and '
              f'therefore omitted: {missing}')
    keep = [c for c in RELEASE_COLS if c in df.columns]
    return df[keep].rename(columns={k: RELEASE_COLS[k] for k in keep})


_fps = [os.path.join(data_dir, final_filename('after_outlier', date, hira,
                                              f'{b}_{a}'))
        for b, a in year_pairs]

if not all(os.path.exists(fp) for fp in _fps):
    print('[skip] Part C: after_outlier sub-period files missing')
else:
    df_1819, df_2021 = (pd.read_excel(fp) for fp in _fps)

    print(f'\n[release] {year_pairs[0][0]}_{year_pairs[0][1]} : '
          f'{df_1819[YKIHO].nunique():,} institutions / {len(df_1819):,} rows')
    print(f'[release] {year_pairs[1][0]}_{year_pairs[1][1]} : '
          f'{df_2021[YKIHO].nunique():,} institutions / {len(df_2021):,} rows')

    # Inner join: only institutions observed in both sub-periods, which is the
    # population of the released dataset.
    _p1, _p2 = (f'{b}_{a}' for b, a in year_pairs)
    merged_inner = merge_year_pairs(df_1819, df_2021, _p1, _p2)
    merged_inner['estb_dd'] = pd.to_datetime(merged_inner['estb_dd'],
                                             errors='coerce')
    print(f'[release] inner join -> {len(merged_inner):,} rows')

    df_release = build_release_view(merged_inner)
    n_rel = len(df_release)
    print(f'[release] {n_rel:,} rows, {df_release.shape[1]} cols')

    if save_release_csv:
        rel_csv = os.path.join(output_dir,
                               f'hospital_energy_benchmarking_{n_rel}.csv')
        df_release.to_csv(rel_csv, index=False, encoding='utf-8-sig')
        print(f'[save] {os.path.basename(rel_csv)}')
    else:
        print('[skip] release CSV (SAVE_RELEASE_CSV = False)')

    if save_column_dict:
        save_column_dictionary(
            df_release,
            os.path.join(output_dir, f'column_dictionary_{n_rel}.xlsx'))
    else:
        print('[skip] column dictionary (SAVE_COLUMN_DICT = False)')

    print(f'\n{"=" * 70}')
    print(f'[check] final N = {n_rel:,}')
    print(f'{"=" * 70}')
