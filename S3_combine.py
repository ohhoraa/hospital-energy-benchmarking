# -*- coding: utf-8 -*-
"""
S3. Combination and release view.

Part A. Concatenate the scopes : SB + MB row-wise, per subperiod and stage
                                 -> '{date} final_{step} {hira}_{yb}_{ya}.xlsx'
Part B. Join the subperiods    : 2018_2019 inner join 2020_2021 on the
                                 institution key
                                 -> '{date} final_{step} {hira}_all.xlsx'
Part C. Release view           : from after_outlier, the released CSV with the
                                 released variable names, the change-point
                                 model parameters and the column statistics
                                 -> data_output/

Parts A and B write to data_prepared/; Part C writes to data_output/.

Variable naming
---------------
Parts A and B do not rename anything: the pipeline keeps the source column
names throughout (totarea_adj, vl_rat_estm_totarea and so on). The released
names (gfa, gfa_r, ...) are applied only in the Part C release view.
"""

import os
import re
import numpy as np
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
if 'save_column_stats' not in globals():
    save_column_stats = True


# =============================================================================
# 1. Column statistics
# =============================================================================
# The column definitions are in document/ (column_dictionary.xlsx,
# table_schema.json).


def build_column_statistics(dataframe):
    """Statistics of each column in this release (they change with N)."""
    rows = []
    for i, col in enumerate(dataframe.columns):
        s = dataframe[col]
        non_null = s.dropna()
        rows.append({
            'position': i, 'column': col,
            'dtype': str(s.dtype),
            'max_length': (int(non_null.astype(str).str.len().max())
                           if len(non_null) else 0),
            'nullable': 'Y' if s.isnull().any() else 'N',
            'null_count': int(s.isnull().sum()),
            'distinct_count': int(s.nunique(dropna=True)),
            'sample': s.iloc[0] if len(s) else None,
        })
    return pd.DataFrame(rows)


# Change-point model parameters: cpm_results_{N}.csv, one row per
# institution x subperiod x energy source. Definitions in
# document/cpm_results_schema.json.
PARAM_COLS = ['idx', 'subperiod', 'source', 'cpm_ty',
              'base', 'htg_slope', 'htg_cp', 'clg_slope', 'clg_cp',
              'ns', 'rmse', 'cvrmse', 'nmbe', 'r2']

# Released parameter name -> BE-sig parameter, per model type.
CPM_MODELS = ('1p', '3p_h', '3p_c', '5p')
BESIG_MAP = {
    'base': {'1p': 'b0', '3p_h': 'b0', '3p_c': 'b0', '5p': 'b0'},
    'htg_slope': {'3p_h': 'b1', '5p': 'b1'},
    'htg_cp': {'3p_h': 'b2', '5p': 'b3'},
    'clg_slope': {'3p_c': 'b1', '5p': 'b2'},
    'clg_cp': {'3p_c': 'b2', '5p': 'b4'},
}


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
# 3. Part B - join the subperiods
# =============================================================================
print(f'\n{"=" * 70}\n[S3] Part B: subperiod inner join\n{"=" * 70}')


# CPM columns (ns_11, r2_13, ...) and the fitting period (date_s, date_e)
# differ by subperiod, so they get a subperiod suffix before the join.
CPM_BASES = ('cpm_ty', 'b0', 'b1', 'b2', 'b3', 'b4',
             'ns', 'cvrmse', 'rmse', 'nmbe', 'r2')
_CPM_RE = re.compile(r'^(' + '|'.join(CPM_BASES) + r')_\d+$')


def pair_specific_cols(df):
    """Columns that need a subperiod suffix (CPM values and fitting period)."""
    return [c for c in df.columns
            if _CPM_RE.match(str(c)) or str(c) in ('date_s', 'date_e')]


def add_pair_suffix(df, pair):
    """Append _{year_b}_{year_a} to the CPM columns."""
    cols = pair_specific_cols(df)
    return df.rename(columns={c: f'{c}_{pair}' for c in cols}), len(cols)


def merge_year_pairs(df1, df2, pair1, pair2, key=YKIHO):
    """Inner join the two subperiod frames on the institution key.

    1) Suffix the CPM columns so that both subperiods are preserved.
    2) Drop the remaining duplicated names from df2, which would otherwise
       produce _x/_y suffixes. Those columns are subperiod invariant, so df1
       is kept as the representative.
    """
    d1, n1 = add_pair_suffix(df1, pair1)
    d2, n2 = add_pair_suffix(df2, pair2)
    if n1 or n2:
        print(f'    subperiod suffix applied to {n1}/{n2} CPM columns '
              f'({pair1} / {pair2})')

    common_cols = [c for c in d1.columns if c in d2.columns and c != key]
    return pd.merge(d1, d2.drop(columns=common_cols), how='inner', on=key)


for step in STEPS:
    fps = [os.path.join(data_dir, final_filename(step, date, hira, f'{b}_{a}'))
           for b, a in year_pairs]
    if not all(os.path.exists(fp) for fp in fps):
        print(f'[skip] {step}: subperiod files missing, no _all file written')
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
#   - Identifiers, addresses, coordinates and matching metadata are not
#     released, so that institutions cannot be identified.
print(f'\n{"=" * 70}\n[S3] Part C: release view\n{"=" * 70}')

RELEASE_COLS = {
    # -- building configuration / registry
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

# Energy source codes of the change-point model columns.
SOURCE_CODES = {'11': 'elec', '12': 'gas', '13': 'heat'}

# Number of variable types in the released file (idx included).
RELEASE_N_TYPES_EXPECTED = 38

_n_nonenergy = sum(
    1 for k in RELEASE_COLS
    if not any(k.startswith(p) for p in ('site_', 'pri_', 'hdd_', 'cdd_'))
)
_n_types = 1 + _n_nonenergy + len(_EN_KINDS) * 2 + 2
print(f'[release] columns = {len(RELEASE_COLS) + 1} (idx and year suffixes included)')
print(f'[release] variable types = {_n_types} (idx 1 + non-energy '
      f'{_n_nonenergy} + energy {len(_EN_KINDS) * 2} + degree days 2)')
if _n_types != RELEASE_N_TYPES_EXPECTED:
    print(f'  WARNING: {_n_types - RELEASE_N_TYPES_EXPECTED:+d} against the '
          f'expected {RELEASE_N_TYPES_EXPECTED} - check RELEASE_COLS.')
else:
    print(f'  variable types confirmed ({_n_types})')


def build_release_view(df):
    """Keep the RELEASE_COLS columns, rename them to the released names and
    put idx in front."""
    missing = [c for c in RELEASE_COLS if c not in df.columns]
    if missing:
        print(f'[release] {len(missing)} column(s) absent from the input and '
              f'therefore omitted: {missing}')
    keep = [c for c in RELEASE_COLS if c in df.columns]
    out = df[keep].rename(columns={k: RELEASE_COLS[k] for k in keep})
    out.insert(0, 'idx', np.arange(1, len(out) + 1))
    return out


def build_cpm_results(df, idx):
    """Long table of the fitted models: one row per institution (idx) x
    subperiod x energy source with a model. Parameters are renamed from
    BE-sig's b0 ... b4 by meaning (BESIG_MAP)."""
    rows = []
    for b, a in year_pairs:
        for code, src in SOURCE_CODES.items():
            sfx = f'_{code}_{b}_{a}'
            if f'cpm_ty{sfx}' not in df.columns:
                continue
            sub = df[[c for c in df.columns if c.endswith(sfx)]].copy()
            sub.columns = [c[:-len(sfx)] for c in sub.columns]
            sub['idx'] = idx
            sub = sub[sub['cpm_ty'].notna()]
            for _, r in sub.iterrows():
                row = {'idx': r['idx'], 'subperiod': f'{b}-{a}', 'source': src,
                       'cpm_ty': r['cpm_ty']}
                for name, by_model in BESIG_MAP.items():
                    bk = by_model.get(r['cpm_ty'])
                    row[name] = r.get(bk) if bk else np.nan
                for f in ('ns', 'rmse', 'cvrmse', 'nmbe', 'r2'):
                    row[f] = r.get(f)
                rows.append(row)
    out = pd.DataFrame(rows, columns=PARAM_COLS)
    unknown = sorted(set(out['cpm_ty']) - set(CPM_MODELS))
    if unknown:
        print(f'[cpm parameters] WARNING: model type(s) {unknown} have no '
              f'parameter mapping; their parameters are left empty')
    out['ns'] = pd.to_numeric(out['ns'], errors='coerce').round().astype('Int64')
    src_order = {s: i for i, s in enumerate(SOURCE_CODES.values())}
    return (out.sort_values(['idx', 'subperiod', 'source'],
                            key=lambda c: c.map(src_order) if c.name == 'source'
                            else c)
               .reset_index(drop=True))


_fps = [os.path.join(data_dir, final_filename('after_outlier', date, hira,
                                              f'{b}_{a}'))
        for b, a in year_pairs]

if not all(os.path.exists(fp) for fp in _fps):
    print('[skip] Part C: after_outlier subperiod files missing')
else:
    df_1819, df_2021 = (pd.read_excel(fp) for fp in _fps)

    print(f'\n[release] {year_pairs[0][0]}_{year_pairs[0][1]} : '
          f'{df_1819[YKIHO].nunique():,} institutions / {len(df_1819):,} rows')
    print(f'[release] {year_pairs[1][0]}_{year_pairs[1][1]} : '
          f'{df_2021[YKIHO].nunique():,} institutions / {len(df_2021):,} rows')

    # Inner join: only institutions observed in both subperiods, which is the
    # population of the released dataset.
    _p1, _p2 = (f'{b}_{a}' for b, a in year_pairs)
    merged_inner = merge_year_pairs(df_1819, df_2021, _p1, _p2)
    merged_inner['estb_dd'] = pd.to_datetime(merged_inner['estb_dd'],
                                             format='%Y-%m-%d', errors='coerce')
    _n_bad = int(merged_inner['estb_dd'].isna().sum())
    if _n_bad:
        print(f'[release] open_ymd: {_n_bad} unparsable opening date(s)')
    print(f'[release] inner join -> {len(merged_inner):,} rows')

    # Release order: by institution key, so that idx is the same on every run.
    merged_inner = merged_inner.sort_values(YKIHO).reset_index(drop=True)
    df_release = build_release_view(merged_inner)
    df_param = build_cpm_results(merged_inner, df_release['idx'].values)

    #   An unrecorded lot area is 0 in the building register; it and the two
    #   ratios derived from it are released as missing.
    ZERO_AS_MISSING = ['plat_area', 'bc_rat', 'fa_rat']
    _zero = {c: (df_release[c] == 0) for c in ZERO_AS_MISSING
             if c in df_release.columns}
    for _c, _m in _zero.items():
        df_release.loc[_m, _c] = np.nan

    n_rel = len(df_release)
    print(f'[release] {n_rel:,} rows, {df_release.shape[1]} cols')

    if save_release_csv:
        rel_csv = os.path.join(output_dir,
                               f'energy_benchmarking_{n_rel}.csv')
        df_release.to_csv(rel_csv, index=False, encoding='utf-8-sig')
        par_csv = os.path.join(output_dir, f'cpm_results_{n_rel}.csv')
        df_param.to_csv(par_csv, index=False, encoding='utf-8-sig')
        print(f'[save] {os.path.basename(rel_csv)}, '
              f'{os.path.basename(par_csv)} ({len(df_param):,} rows)')
    else:
        print('[skip] release CSV (SAVE_RELEASE_CSV = False)')

    if save_column_stats:
        st = os.path.join(output_dir, f'column_statistics_{n_rel}.xlsx')
        build_column_statistics(df_release).to_excel(st, index=False)
        print(f'[save] {os.path.basename(st)}')
    else:
        print('[skip] column statistics (SAVE_COLUMN_STATS = False)')

    print(f'\n{"=" * 70}')
    print(f'[check] final N = {n_rel:,}')
    print(f'{"=" * 70}')
