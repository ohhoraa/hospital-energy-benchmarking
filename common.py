# -*- coding: utf-8 -*-
"""
Shared constants and helper functions.

Used by S1_SB_merge / S1_MB_merge / S2_clean / S3_combine.

Terminology
-----------
scope = 'SB' | 'MB'
  SB = Single Building    : one building register record = one institution
                            (HIRA match_level CASE102)
  MB = Multiple Buildings : one master building record + its member building
                            records (HIRA match_level CASE101)

Only single-institution configurations (SB-SI, MB-SI) are retained.
"""

import os
import numpy as np
import pandas as pd


# =============================================================================
# 0. Constants
# =============================================================================
# Principal-use code for medical facilities. The source register mixes
# zero-padded and non-padded codes, so both spellings are accepted.
MAIN_PURPS_CDS = ['09000', '9000']

# Building-institution configuration (model_ty).
#   SB/MB = building scope, SI/MI = number of institutions.
MODEL_TY_SB_SI = 'SB-SI'
MODEL_TY_SB_MI = 'SB-MI'
MODEL_TY_MB_SI = 'MB-SI'
MODEL_TY_MB_MI = 'MB-MI'

# HIRA institution type name (cl_cd_nm) -> English abbreviation (hos_ty_eng).
#   GH General / H Hospital / CH Long-term care / KH Korean medicine
#   PH Psychiatric / DH Dental / TH Tertiary general
HOS_TY_LABEL_MAP = {
    '종합병원': 'GH',
    '병원': 'H',
    '요양병원': 'CH',
    '한방병원': 'KH',
    '정신병원': 'PH',
    '치과병원': 'DH',
    '상급종합': 'TH',
}

# HIRA institution key (encrypted institution identifier).
YKIHO = 'ykiho'

# Per-scope configuration.
#   pk_col   : primary key used for counting and merging
#   gfa_col  : gross floor area used as the denominator of area_bed screening.
#              Both scopes use totarea_adj, which S2 sets to the master-record
#              value for MB (after the cross-check against the summed member
#              records) and to the raw value for SB.
#   model_ty : the single-institution configuration retained by the filters
#   prefix   : file-name prefix of the intermediate outputs
SCOPE_CFG = {
    'SB': {
        'pk_col': 'mgm_bld_pk',
        'gfa_col': 'totarea_adj',
        'model_ty': MODEL_TY_SB_SI,
        'prefix': 'df_SB_merge',
        'match_level': 'CASE102',
    },
    'MB': {
        'pk_col': 'mgm_upper_bld_pk',
        'gfa_col': 'totarea_adj',
        'model_ty': MODEL_TY_MB_SI,
        'prefix': 'df_MB_merge',
        'match_level': 'CASE101',
    },
}
SCOPES = ['MB', 'SB']

# Pipeline stages written to disk.
#   before_preprocessing : S1 output, read by S2
#   after_outlier        : S2 output (filtering + screening + manual removal),
#                          read by S3
STEPS = [
    'before_preprocessing',
    'after_outlier',
]

# Primary energy conversion factors (electricity / gas / district heating).
PRI_FACTOR = {11: 2.75, 12: 1.1, 13: 0.728}


# =============================================================================
# 1. File-name rules - defined in one place only
# =============================================================================
def step_filename(scope, step, date, hira, year_b, year_a):
    """Per-scope intermediate file name exchanged between S1 and S2.

    e.g. '260820 df_SB_merge_before_preprocessing 202003_2018_2019.xlsx'
    """
    prefix = SCOPE_CFG[scope]['prefix']
    return f'{date} {prefix}_{step} {hira}_{year_b}_{year_a}.xlsx'


def final_filename(step, date, hira, pair='all'):
    """File name of the SB+MB row-wise concatenation written by S3.

    e.g. '260820 final_after_outlier 202003_2018_2019.xlsx'
         '260820 final_after_outlier 202003_all.xlsx'
    """
    return f'{date} final_{step} {hira}_{pair}.xlsx'


# =============================================================================
# 2. Step counting
# =============================================================================
try:
    import counter
    _USE_COUNTER = True
except ImportError:
    _USE_COUNTER = False


def col_counts(df, col, label, step=None):
    """Print the number of distinct values at one step and record it.

    step : row key of the count table. Defaults to `label`.
           Labels that vary by scope (they embed the primary-key name or the
           model_ty value) must pass a normalised `step`, otherwise one step is
           split across two rows of the table.
    """
    n = df[col].nunique(dropna=True)
    print(f'{label} : {n}')
    if _USE_COUNTER:
        counter.log(df, col, label, step=step)
    return n


def make_counter(pk_col):
    """Return a function that prints both counts (building PK and institution).

    The console label states which column each count refers to, while the count
    table keys on `step` alone so that one step occupies one row.
    """
    def _print_counts(df, label, step=None):
        key = step if step is not None else label
        col_counts(df, pk_col, f'{label} ({pk_col})', step=key)
        col_counts(df, YKIHO, f'{label} ({YKIHO})', step=key)
    return _print_counts


# =============================================================================
# 3. Manual exclusion list
# =============================================================================
# What the manual inspection found. Both types are removed; they are kept apart
# because they are different findings and are read off different views.
#   mat_err  : matching error. The institution is linked to a building that
#              belongs to a different facility, or to only part of its own, so
#              the floor area and the energy do not describe the same thing.
#   dist_err : distribution error. The matching is sound, but the institution
#              sits where no operating institution can sit in the joint
#              distributions (bed-based intensity against floor area), so the
#              underlying record is taken to be wrong.
LIST_TYPES = ('mat_err', 'dist_err')


def load_manual_exclusions_table(csv_path):
    """Read the manual exclusion list without filtering."""
    if not os.path.exists(csv_path):
        raise FileNotFoundError(
            f'Manual exclusion list not found: {csv_path}\n'
            f'  -> place manual_exclusions.csv next to the scripts, or pass '
            f'exclusion_csv from run_all_merge.py.'
        )
    ex = pd.read_csv(csv_path, encoding='utf-8-sig')
    need = {'ykiho', 'list_ty'}
    miss = need - set(ex.columns)
    if miss:
        raise KeyError(
            f'{os.path.basename(csv_path)} is missing columns: {sorted(miss)}')

    ex['ykiho'] = ex['ykiho'].astype(str).str.strip()
    ex['list_ty'] = ex['list_ty'].astype(str).str.strip().str.lower()

    bad = sorted(set(ex['list_ty']) - set(LIST_TYPES))
    if bad:
        raise ValueError(
            f'{os.path.basename(csv_path)}: unknown list_ty value(s) {bad}\n'
            f'  -> expected one of {list(LIST_TYPES)}.')
    return ex


def manual_exclusion_types(csv_path):
    """{list_ty: [institution identifiers]} for the whole list."""
    ex = load_manual_exclusions_table(csv_path)
    return {t: ex.loc[ex['list_ty'] == t, 'ykiho'].tolist() for t in LIST_TYPES}


def load_manual_exclusions(csv_path):
    """Read the institutions to remove in the manual inspection.

    CSV schema
    ----------
    ykiho       : institution identifier
    list_ty     : 'mat_err' | 'dist_err' (see LIST_TYPES)
    reason_code : reason category
    reason_en   : reason text
    note_ko     : free-text note, not read by the code

    Returns
    -------
    (mat_err_list, dist_err_list) : institution identifiers per type
    """
    by_ty = manual_exclusion_types(csv_path)

    print(f'[manual_exclusions] mat_err = {len(by_ty["mat_err"])}, '
          f'dist_err = {len(by_ty["dist_err"])} '
          f'(file: {os.path.basename(csv_path)})')
    return by_ty['mat_err'], by_ty['dist_err']


def drop_manual_exclusions(df, ykiho_list, print_counts=None,
                           list_ty_map=None, step='after manual exclusion'):
    """Remove the listed institutions and report how many were removed.

    list_ty_map : {ykiho: list_ty}. Only used to break the removal down by
                  type in the log, so that the two findings stay distinguishable
                  in the run output.
    step        : row key of the count table.
    """
    df_out = df.copy()
    print(f'[manual] before = {len(df_out):,}')

    removed = df_out[df_out[YKIHO].isin(ykiho_list)]
    df_out = df_out[~df_out[YKIHO].isin(ykiho_list)]
    print(f'[manual] after  = {len(df_out):,}  (removed {len(removed):,})')

    if list_ty_map and len(removed):
        _ty = removed[YKIHO].astype(str).map(list_ty_map)
        for t in LIST_TYPES:
            print(f'[manual]   {t}: {int((_ty == t).sum())} row(s), '
                  f'{removed.loc[_ty == t, YKIHO].nunique()} institution(s)')

    if print_counts is not None:
        print_counts(df_out, step, step=step)

    return df_out


# =============================================================================
# 4. Building register: derived values and corrections
# =============================================================================
def add_totarea_abs_error(df, tot_col='totarea', vl_col='vl_rat_estm_totarea',
                          out_col='totarea_abs_error'):
    """Absolute relative error between gfa and gfa_r.

    NaN when either value is zero or missing (avoids division by zero).
    S2 screening removes rows whose value is >= 0.99.
    """
    df = df.copy()
    df[out_col] = np.where(
        df[tot_col].notna() & df[vl_col].notna() &
        (df[tot_col] != 0) & (df[vl_col] != 0),
        (df[tot_col] - df[vl_col]).abs() / df[tot_col],
        np.nan,
    )
    print(f'--- {out_col} NaN : {df[out_col].isna().sum()}')
    return df


def clean_bc_rat(df, bc_col='bc_rat', arch_col='arch_area', plat_col='plat_area',
                 threshold=100, verbose=False):
    """Building coverage ratio: out-of-range check, correction, then removal.

    1) If bc_rat > 100, recompute it as footprint_area / plat_area * 100.
    2) If it still exceeds 100 after recomputation, drop the row. A lot area of
       zero or missing makes the recomputation impossible, so those rows fail
       here.
    """
    df = df.copy()

    mask_high = df[bc_col] > threshold
    valid_denom = mask_high & (df[plat_col] > 0)
    n_recalc = int(valid_denom.sum())

    df.loc[valid_denom, bc_col] = (
        df.loc[valid_denom, arch_col] / df.loc[valid_denom, plat_col] * 100
    )

    before = len(df)
    df = df[df[bc_col] <= threshold].copy()
    removed = before - len(df)

    if verbose:
        print('\n=== bc_rat correction ===')
        print(f'recomputed rows : {n_recalc}')
        print(f'removed rows    : {removed}')
    return df


def grnd_flr_invalid(s):
    """Above-ground floor count is invalid when it is <= 0 or missing.

    Applied to grnd_flr_max for both scopes. For SB the building register holds
    a single record, so the maximum equals the raw value; for MB an institution
    is removed only when every member record is invalid.
    """
    return (s <= 0) | s.isna()


# =============================================================================
# 5. Energy: derived values
# =============================================================================
def classify_energy_hybrid(df, g_col, h_col, sum_col, ty_col,
                           min_val=10, ratio_thr=0.001):
    """Classify the combination of energy sources in use (E / EG / EH / EGH).

    A source counts as "in use" when its absolute annual consumption reaches
    min_val or when its share of total consumption reaches ratio_thr. An
    absolute rule alone misses small quantities at large hospitals; a share
    rule alone misses real use at small ones, so the two are combined with OR.
    """
    out = df.copy()
    g_used = (out[g_col] >= min_val) | ((out[g_col] / out[sum_col]) >= ratio_thr)
    h_used = (out[h_col] >= min_val) | ((out[h_col] / out[sum_col]) >= ratio_thr)

    conditions = [
        (~g_used) & (~h_used),
        (g_used) & (h_used),
        (g_used) & (~h_used),
        (~g_used) & (h_used),
    ]
    out[ty_col] = np.select(conditions, ['E', 'EGH', 'EG', 'EH'], default='unknown')
    return out


def add_en_ty_and_flag(df, pk_col, year_b, year_a):
    """Per-year energy-source combination plus a two-year agreement flag.

    flag_en_ty_{b}_{a} : 0 identical / 1 different / 2 one year missing / 3 other
    A change in the set of energy sources between the two years suggests a
    plant replacement or a metering change, so screening removes it.
    """
    df = df.copy()

    for year in (year_b, year_a):
        ty_col = f'en_ty_{year}'
        temp = classify_energy_hybrid(
            df,
            g_col=f'site_gas_{year}',
            h_col=f'site_heat_{year}',
            sum_col=f'site_sum_{year}',
            ty_col=ty_col,
        )[[pk_col, ty_col]].drop_duplicates(subset=[pk_col])
        df = df.merge(temp, on=pk_col, how='left')

    flag_col = f'flag_en_ty_{year_b}_{year_a}'
    col_b, col_a = f'en_ty_{year_b}', f'en_ty_{year_a}'

    df[flag_col] = 0
    df.loc[df[col_a].isna() | df[col_b].isna(), flag_col] = 2
    df.loc[df[col_a].notna() & df[col_b].notna() & (df[col_a] != df[col_b]), flag_col] = 1
    df[flag_col] = df[flag_col].fillna(3).astype(int)

    print(f'* energy-source mismatch ({flag_col} == 1): {df[flag_col].eq(1).sum()}')
    return df


def add_comp_ratio_flag(df, year_b, year_a):
    """Two-year consumption ratio (year a / year b) and its outlier flag.

    flag_comp_5_{b}_{a} : 1 when the ratio is below 0.2 or above 5.
    A fivefold change within a pair is more likely a metering or attribution
    error than a real change in operation, so screening removes it.
    """
    df = df.copy()
    col_b, col_a = f'site_sum_{year_b}', f'site_sum_{year_a}'
    ratio_col = f'comp_ratio_{year_b}_{year_a}'
    flag_col = f'flag_comp_5_{year_b}_{year_a}'

    df[ratio_col] = np.where(
        df[col_a].notna() & df[col_b].notna() & (df[col_a] != 0) & (df[col_b] != 0),
        df[col_a] / df[col_b],
        np.nan,
    )
    df[flag_col] = pd.cut(
        df[ratio_col],
        bins=[0, 0.2, 5, float('inf')],
        labels=[1, 0, 1],
        right=False, ordered=False,
    ).astype(int)

    print(f'* consumption-ratio outlier ({flag_col} == 1): {df[flag_col].eq(1).sum()}')
    return df


# =============================================================================
# 6. HIRA: derived values
# =============================================================================
def add_ct_mri_cnt(df, ct_col='ct_cnt', mri_col='mri_cnt', out_col='ct_mri_cnt'):
    """Sum of CT and MRI units. NaN when either is missing or negative."""
    df = df.copy()
    df[out_col] = np.where(
        df[ct_col].notna() & df[mri_col].notna() &
        (df[ct_col] >= 0) & (df[mri_col] >= 0),
        df[ct_col] + df[mri_col],
        np.nan,
    )
    return df
