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
#   DH Dental / TH Tertiary general
#   The March 2020 release does not report psychiatric hospitals as a type of
#   their own - they are reported as long-term care hospitals (CH). Later
#   releases separate them; add the entry here if one is used.
HOS_TY_LABEL_MAP = {
    '종합병원': 'GH',
    '병원': 'H',
    '요양병원': 'CH',
    '한방병원': 'KH',
    '치과병원': 'DH',
    '상급종합': 'TH',
}

# HIRA institution key (encrypted institution identifier).
YKIHO = 'ykiho'

# Per-scope configuration.
#   pk_col   : primary key used for counting and merging
#   model_ty : the single-institution configuration retained by the filters
#   prefix   : file-name prefix of the intermediate outputs
SCOPE_CFG = {
    'SB': {
        'pk_col': 'mgm_bld_pk',
        'model_ty': MODEL_TY_SB_SI,
        'prefix': 'df_SB_merge',
        'match_level': 'CASE102',
    },
    'MB': {
        'pk_col': 'mgm_upper_bld_pk',
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


def col_counts(df, col, label, step):
    """Print the number of distinct values at one step and record it.

    label : console text, which names the column the count refers to
    step  : row key of the count table. Labels that vary by scope (they embed
            the primary-key name or the model_ty value) must pass a normalised
            `step`, otherwise one step is split across two rows of the table.
    """
    print(f'{label} : {df[col].nunique(dropna=True)}')
    if _USE_COUNTER:
        counter.log(df, col, step=step)


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


MANUAL_EXCLUSION_STEP = 'after manual exclusion'


def drop_manual_exclusions(df, ykiho_list, print_counts=None, list_ty_map=None):
    """Remove the listed institutions and report how many were removed.

    list_ty_map : {ykiho: list_ty}. Only used to break the removal down by
                  type in the log, so that the two findings stay distinguishable
                  in the run output.
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
        print_counts(df_out, MANUAL_EXCLUSION_STEP, step=MANUAL_EXCLUSION_STEP)

    return df_out


# =============================================================================
# 4. Building register: derived values and corrections
# =============================================================================
# Gap above which the master-record floor area and the summed member records
# are taken to cover different sets of buildings (about one building's worth).
TOTAREA_GAP = 500


def totarea_adj(df):
    """Corrected gross floor area, released as `gfa`.

    For an MB record the master-register floor area is compared with the sum of
    its member building records; a gap of at least TOTAREA_GAP m2 means the two
    totals cover different sets of buildings, so the larger (more complete)
    value is taken. An SB record holds a single register record and has nothing
    to compare against, so the raw value is kept.

    The scope is read row by row from model_ty, so a frame that mixes SB and MB
    rows (the S3 concatenation, which paper_figure.py reads) is handled as well
    as a single-scope frame. bld_area_total is produced by S1_MB only, so an
    SB-only frame does not carry it; its absence leaves every row on the raw
    value, which is the intended SB behaviour.
    """
    tot = pd.to_numeric(df['totarea'], errors='coerce')
    if 'bld_area_total' in df.columns:
        bld = pd.to_numeric(df['bld_area_total'], errors='coerce')
    else:
        bld = pd.Series(np.nan, index=df.index)

    is_mb = df['model_ty'].astype(str).str.startswith('MB')
    use_max = is_mb & (tot - bld).abs().ge(TOTAREA_GAP)
    print(f'--- totarea_adj corrected on {int(use_max.sum())} rows')
    return np.where(use_max, np.maximum(tot, bld), tot)


def add_totarea_abs_error(df):
    """Absolute relative error between gfa (totarea) and gfa_r.

    Written to totarea_abs_error. NaN when either value is zero or missing
    (avoids division by zero). S2 screening keeps rows below 0.99, which
    removes the NaN rows as well.
    """
    df = df.copy()
    df['totarea_abs_error'] = np.where(
        df['totarea'].notna() & df['vl_rat_estm_totarea'].notna() &
        (df['totarea'] != 0) & (df['vl_rat_estm_totarea'] != 0),
        (df['totarea'] - df['vl_rat_estm_totarea']).abs() / df['totarea'],
        np.nan,
    )
    print(f'--- totarea_abs_error NaN : {df["totarea_abs_error"].isna().sum()}')
    return df


# A building coverage ratio above 100% is impossible by definition, so it is a
# bound rather than a tunable threshold.
BC_RAT_MAX = 100


def clean_bc_rat(df):
    """Building coverage ratio: out-of-range check, correction, then removal.

    1) If bc_rat > 100, recompute it as arch_area / plat_area * 100.
    2) If it still exceeds 100 after recomputation, drop the row. A lot area of
       zero or missing makes the recomputation impossible, so those rows fail
       here.
    """
    df = df.copy()

    valid_denom = (df['bc_rat'] > BC_RAT_MAX) & (df['plat_area'] > 0)
    n_recalc = int(valid_denom.sum())

    df.loc[valid_denom, 'bc_rat'] = (
        df.loc[valid_denom, 'arch_area'] / df.loc[valid_denom, 'plat_area'] * 100
    )

    before = len(df)
    df = df[df['bc_rat'] <= BC_RAT_MAX].copy()

    print('\n=== bc_rat correction ===')
    print(f'recomputed rows : {n_recalc}')
    print(f'removed rows    : {before - len(df)}')
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
# Thresholds of the "in use" test for a secondary energy source, as reported in
# the manuscript. A source counts as in use when EITHER is met.
EN_TY_MIN_KWH = 10        # absolute annual consumption
EN_TY_MIN_SHARE = 0.001   # share of the annual total


def classify_energy_hybrid(df, g_col, h_col, sum_col, ty_col):
    """Classify the combination of energy sources in use (E / EG / EH / EGH).

    A source counts as "in use" when its absolute annual consumption reaches
    EN_TY_MIN_KWH or when its share of total consumption reaches
    EN_TY_MIN_SHARE. An absolute rule alone misses small quantities at large
    hospitals; a share rule alone misses real use at small ones, so the two are
    combined with OR.
    """
    out = df.copy()
    g_used = ((out[g_col] >= EN_TY_MIN_KWH)
              | ((out[g_col] / out[sum_col]) >= EN_TY_MIN_SHARE))
    h_used = ((out[h_col] >= EN_TY_MIN_KWH)
              | ((out[h_col] / out[sum_col]) >= EN_TY_MIN_SHARE))

    #   The two flags are booleans, so the three conditions plus the default
    #   cover every row: neither source in use is electricity only.
    out[ty_col] = np.select(
        [g_used & h_used, g_used & ~h_used, ~g_used & h_used],
        ['EGH', 'EG', 'EH'],
        default='E',
    )
    return out


def add_en_ty_and_flag(df, pk_col, year_b, year_a):
    """Per-year energy-source combination plus a two-year agreement flag.

    flag_en_ty_{b}_{a} : 0 identical / 1 different / 2 either year missing
    A change in the set of energy sources between the two years suggests a
    plant replacement or a metering change, so screening removes it. Screening
    keeps flag == 0 only, so a missing year is removed as well.
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

    #   Created as an integer column and only ever assigned 0, 1 or 2 through
    #   the masks below, so no fill is needed.
    df[flag_col] = 0
    df.loc[df[col_a].isna() | df[col_b].isna(), flag_col] = 2
    df.loc[df[col_a].notna() & df[col_b].notna() & (df[col_a] != df[col_b]), flag_col] = 1

    print(f'* energy-source mismatch ({flag_col} == 1): {df[flag_col].eq(1).sum()}')
    return df


def add_comp_ratio_flag(df, year_b, year_a):
    """Two-year consumption ratio (year a / year b) and its outlier flag.

    flag_comp_5_{b}_{a} : 0 within 0.2-5 / 1 below 0.2 or above 5
                          2 the ratio is undefined, i.e. either year's total is
                            missing or zero
    A fivefold change within a pair is more likely a metering or attribution
    error than a real change in operation, so screening removes it. Screening
    keeps flag == 0 only, so an undefined ratio is removed as well; it is
    flagged 2 rather than 1 so that the two reasons stay distinguishable, which
    mirrors add_en_ty_and_flag.
    """
    df = df.copy()
    col_b, col_a = f'site_sum_{year_b}', f'site_sum_{year_a}'
    ratio_col = f'comp_ratio_{year_b}_{year_a}'
    flag_col = f'flag_comp_5_{year_b}_{year_a}'

    _defined = (df[col_a].notna() & df[col_b].notna()
                & (df[col_a] != 0) & (df[col_b] != 0))
    df[ratio_col] = np.where(_defined, df[col_a] / df[col_b], np.nan)

    #   pd.cut leaves an undefined ratio outside every bin, so the categorical
    #   is filled with 2 before the integer cast. Casting first would raise on
    #   the NaN category.
    df[flag_col] = (
        pd.cut(df[ratio_col],
               bins=[0, 0.2, 5, float('inf')],
               labels=[1, 0, 1],
               right=False, ordered=False)
        .astype(float).fillna(2).astype(int)
    )

    print(f'* consumption-ratio outlier ({flag_col} == 1): {df[flag_col].eq(1).sum()}')
    _n2 = int(df[flag_col].eq(2).sum())
    if _n2:
        print(f'* consumption ratio undefined ({flag_col} == 2): {_n2} '
              f'(a yearly total is missing or zero)')
    return df


# =============================================================================
# 6. HIRA: derived values
# =============================================================================
