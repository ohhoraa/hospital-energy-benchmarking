# -*- coding: utf-8 -*-
"""
pu_rat. Primary use area ratio from the floor summary records.

Input  : full floor summary register, pipe-delimited text, euc-kr, about 4 GB
Output : data_prepared/{date} pu_rat.txt      (pipe-delimited, utf-8-sig, header)
         data_prepared/{date} pu_rat_log.txt  (run log)
         -> read by S1_SB_merge.py / S1_MB_merge.py, joined on mgm_bld_pk

This step is kept as a separate script rather than folded into S0 because the
source file is about 4 GB. It only has to be re-run when the floor summary
register itself is updated; S1 then reuses the much smaller output for every
subsequent run. `RUN_PU_RAT` in run_all_merge.py is the switch.

Definitions
-----------
    flr_tot_area       sum of floor areas per building record, parking included
    flr_hos_area       sum of floor areas whose principal use is a medical
                       facility (HOS_NMS union HOS_CDS)
    flr_parking_area   sum of floor areas used for parking
                       (PARKING_CDS union PARKING_NMS)
    flr_net_area       flr_tot_area - flr_parking_area     <- denominator
    flr_main_purps_rat flr_hos_area / flr_net_area * 100   <- pu_rat

Parking is excluded from the denominator on the basis of the registered use
being a car park or a garage (current codes 20001 / 20009), regardless of
whether the floor is above or below ground.

Medical use follows Table 1, Item 9 (medical facilities) of the Enforcement
Decree of the Building Act; the Item 3(d) Class I neighbourhood living
facilities (clinic, dental clinic, Korean medicine clinic, midwifery clinic,
postpartum care centre) are excluded from the numerator but remain in the
denominator. See the HOS_NMS block below for the item-by-item basis.

Identification uses the registered use NAME and the registered use CODE
together (their union). The register mixes two code systems (current
five-digit 09xxx and superseded four-digit 7xxx), mixes zero-padded and
non-padded spellings, and assigns several codes to one name, so a hand-written
code list silently misses cases; conversely, name matching alone misses the
rows whose name is missing but whose code is present. The code set is
therefore derived from the name-code pairs observed in the source and combined
with a seed list, subject to a safeguard (see Section 3).
"""

import os
import time
from datetime import datetime

import numpy as np
import pandas as pd


# =============================================================================
# 0. Settings (injectable from run_all_merge.py)
# =============================================================================
_BASE_DIR = os.path.dirname(os.path.abspath(__file__))

if 'data_dir_in' not in globals():
    data_dir_in = os.path.join(_BASE_DIR, 'data_raw')
if 'data_dir' not in globals():
    data_dir = os.path.join(_BASE_DIR, 'data_prepared')
if 'date' not in globals():
    date = 260820

# Floor summary source file.
if 'flr_ouln_file' not in globals():
    flr_ouln_file = 'bld_flr_ouln_delimiter_bar_euckr.txt'

# Output file name (read by S1).
if 'pu_rat_file' not in globals():
    pu_rat_file = f'{date} pu_rat.txt'

# Write the run log to a text file. Optional, but useful on a script that
# reads about 4 GB: it is where a failure is traced back to.
if 'save_log' not in globals():
    save_log = True

os.makedirs(data_dir, exist_ok=True)


# =============================================================================
# 0-1. Logging - written to a text file rather than the console
# =============================================================================
log_path = os.path.join(data_dir, f'{date} pu_rat_log.txt') if save_log else None
_log_fh = open(log_path, 'w', encoding='utf-8-sig') if save_log else None
_log_note = log_path if save_log else '(logging disabled)'


def log(*args, sep=' '):
    """Write one progress line to the log file.

    Nothing is printed to the console while the 4 GB source is being read; the
    console receives a single completion or failure line at the end.
    """
    if _log_fh is None:
        return
    _log_fh.write(sep.join(str(a) for a in args) + '\n')
    _log_fh.flush()


_t_start = time.perf_counter()
_t_mark = _t_start


def _fmt_sec(sec):
    if sec < 60:
        return f'{sec:.1f}s'
    m, s_ = divmod(int(round(sec)), 60)
    return f'{m}m {s_}s'


def lap(label):
    """Record the elapsed time of the section just finished."""
    global _t_mark
    now = time.perf_counter()
    log(f'   [time] {label} {_fmt_sec(now - _t_mark)}  '
        f'(cumulative {_fmt_sec(now - _t_start)})')
    _t_mark = now


# The body is wrapped in try/finally so that the log file is closed even when
# an exception is raised (the script is executed with runpy).
try:
    log('=' * 100)
    log('Primary use area ratio from the building register floor summary')
    log(f'run at    : {datetime.now():%Y-%m-%d %H:%M:%S}')
    log(f'date={date} / data_dir={data_dir}')
    log('=' * 100)

    # =========================================================================
    # 1. Use classification - Enforcement Decree of the Building Act, Table 1
    # =========================================================================
    # Numerator = Item 9, medical facilities. In each comment below, "9(a)" and
    # "9(b)" refer to the sub-items of the current decree, and cur/old give the
    # building register use codes (current five-digit / superseded four-digit).
    #
    #   Item 9(a) Hospitals: general hospital, hospital, dental hospital,
    #             Korean medicine hospital, psychiatric hospital, long-term
    #             care hospital
    #   Item 9(b) Isolation hospitals: infectious disease hospital, narcotics
    #             treatment centre, and similar facilities
    #
    # The register stores the use name that was in force when the floor was
    # registered, so superseded names survive in the data, and the code system
    # also carries finer categories that the decree does not enumerate
    # (maternity hospital, other hospital, other medical facility).
    HOS_NMS = [
        # -- Item 9(a), hospitals -------------------------------------------
        '종합병원',      # general hospital           cur 09101 / old 7101
        '병원',          # hospital                   cur 09100, 09107 / old 7100, 7107
        '치과병원',      # dental hospital            cur 09103 / old 7103
        '한방병원',      # Korean medicine hospital   cur 09104 / old 7104
        '정신병원',      # psychiatric hospital       cur 09105 / old 7105
        '요양병원',      # long-term care hospital    cur 09109 / old none
        '요양소',        # superseded name of the above (see note)
        #   The current decree contains no "yoyangso". It was the last item of
        #   the medical-facility list in the earlier decree ("general hospital,
        #   hospital, dental hospital, Korean medicine hospital, psychiatric
        #   hospital, yoyangso") and was replaced in that same position by
        #   "yoyangbyeongwon" (long-term care hospital). The category did not
        #   change, only the name, so the superseded name follows the category
        #   of the name that replaced it: Item 9. It appears nowhere among the
        #   neighbourhood living facilities. The code layout matches this
        #   reading: 09107 hospital, 09108 yoyangso, 09109 long-term care
        #   hospital, i.e. 09108 sits inside the 091xx hospital block and 09109
        #   was appended later.
        '산부인과병원',   # maternity hospital, sub-category of 9(a) 'hospital'
                          #                            cur 09102 / old 7102
        '기타병원',      # other hospital, residual of 9(a)  cur 09199 / old none
        # -- Item 9(b), isolation hospitals ---------------------------------
        '격리병원',      # isolation hospital         cur 09106, 09200 / old 7106, 7300
        '전염병원',      # infectious disease hospital cur 09201 / old 7301
        '기타격리병원',   # other isolation hospital   cur 09299 / old none
        # -- Item 9, top level and residual ---------------------------------
        '의료시설',      # medical facility (top level) cur 09000 / old 7000
        '기타의료시설',   # other medical facility      cur 09999 / old 7999
        #
        # -- Deliberately NOT in the numerator ------------------------------
        #   narcotics treatment centre 09202/7302 : named in Item 9(b) but does
        #                            not occur in this source; revisit if it does
        #   funeral hall  09301/7201 : Item 28, funeral facilities
        #   animal clinic 03036 etc. : Items 3 and 4, neighbourhood living
        #   public health centre 03108 : Item 3(f)
        #   medical tourism hotel 15208 : Item 15, lodging
        #
        #   Item 3(d), Class I neighbourhood living facilities: "clinics,
        #   dental clinics, Korean medicine clinics, acupuncture clinics,
        #   bonesetting clinics, midwifery clinics, massage clinics, postpartum
        #   care centres and similar facilities for the treatment of
        #   residents". These are outpatient care institutions and are excluded
        #   from the numerator while remaining in the denominator; simply
        #   leaving them out of this list achieves that. The postpartum care
        #   centre is named explicitly in the decree. "josanso" does not appear
        #   in the current decree; it follows the category of "josanwon"
        #   (midwifery clinic), which replaced it in the same position, which
        #   mirrors the yoyangso -> yoyangbyeongwon mapping above.
    ]

    # Seed code list for medical facilities.
    #   Section 3 derives the code set from the name-code pairs observed in the
    #   source, but a code that never co-occurs with a name (every row carrying
    #   it has a missing name) cannot be derived that way. The codes documented
    #   above are therefore seeded and unioned with the derived set. Seeds must
    #   still pass the two safeguards below.
    _SEED5 = [
        '09000',                                      # medical facility
        '09100', '09101', '09102', '09103',           # hospital / general / maternity / dental
        '09104', '09105', '09107', '09108', '09109',  # Korean med / psychiatric / hospital / yoyangso / long-term care
        '09199', '09999',                             # other hospital / other medical facility
        '09106', '09200', '09201', '09299',           # isolation / isolation / infectious / other isolation
    ]
    _SEED_OLD = ['7000', '7100', '7101', '7102', '7103', '7104', '7105',
                 '7106', '7107', '7300', '7301', '7999']
    #   Both spellings are seeded because the source mixes them ('09000' / '9000').
    HOS_CDS_SEED = set(_SEED5) | {c.lstrip('0') for c in _SEED5} | set(_SEED_OLD)

    log(f'\n[config] medical-use names: {len(HOS_NMS)}')
    log(f'   Table 1 Item 9 (medical facilities): included in the numerator')
    log(f'   Table 1 Item 3(d) Class I neighbourhood living facilities '
        f'(clinic, dental clinic, Korean medicine clinic, midwifery clinic, '
        f'postpartum care centre): excluded from the numerator, retained in '
        f'the denominator')

    # Car parks and garages, regardless of floor position.
    #   Both code and name are checked: codes alone miss the superseded system,
    #   names alone are sensitive to spelling variants. Disagreements between
    #   the two are logged.
    PARKING_CDS = ['20001', '20009']
    PARKING_NMS = ['주차장', '차고']

    # Only the four columns needed for the aggregation are read.
    USECOLS = ['mgm_bld_pk', 'main_purps_cd', 'main_purps_nm', 'area']

    PK = 'mgm_bld_pk'

    # =========================================================================
    # 2. Load
    # =========================================================================
    file_path = os.path.join(data_dir_in, flr_ouln_file)
    if not os.path.exists(file_path):
        _cand = ([f for f in os.listdir(data_dir_in) if f.lower().endswith('.txt')]
                 if os.path.isdir(data_dir_in) else [])
        log(f'[ERROR] floor summary source not found: {file_path}')
        log(f'        .txt files in that folder: {_cand if _cand else "(no such folder)"}')
        raise FileNotFoundError(
            f'Floor summary source not found: {file_path}\n'
            f'  -> .txt files in that folder: {_cand if _cand else "(no such folder)"}\n'
            f'  -> check FLR_OULN_FILE in run_all_merge.py and data_raw/\n'
            f'  -> log: {_log_note}'
        )

    log(f'[load] {file_path}')
    log(f'       (about 4 GB; only {USECOLS} are read)')
    df_bldg = pd.read_csv(
        file_path, delimiter='|', encoding='euc-kr', low_memory=False,
        usecols=USECOLS,
        # Codes must keep their leading zero (09000 must not become 9000) and
        # the primary key is a string.
        dtype={PK: str, 'main_purps_cd': str},
    )
    log(f'[load] rows = {len(df_bldg):,}')

    # Normalise both text columns ONCE, here, so that every section below
    # works on the same values. Matching is done on the registered name, so
    # ideographic spaces and padding have to go; and `astype(str)` turns a
    # missing value into the literal 'nan', which would defeat `isna()` later.
    # The code is only stripped of whitespace, never re-valued: a leading zero
    # is meaningful (09000 is not 9000).
    for _c in ('main_purps_nm', 'main_purps_cd'):
        df_bldg[_c] = (df_bldg[_c].astype(str)
                       .str.replace('\u3000', ' ', regex=False)
                       .str.strip()
                       .replace({'nan': np.nan, 'None': np.nan, '': np.nan}))

    lap('load')

    # =========================================================================
    # 3. Medical-facility code set
    # =========================================================================
    # Medical use is identified by registered name OR registered code. The code
    # set is derived from the name-code pairs present in the source rather than
    # written by hand, because the current five-digit (09xxx) and superseded
    # four-digit (7xxx) systems coexist, zero padding is inconsistent
    # ('9000' / '09000'), and one name can carry several codes. Padding a
    # four-digit code to five digits is not a valid conversion - it maps some
    # codes to a different use entirely - so no zero padding is applied
    # anywhere in this script.
    #
    # The derived set is unioned with a seed list, because a code that never
    # co-occurs with a name (every row carrying it has a missing name) cannot
    # be derived. One safeguard then applies: a code seen with both medical and
    # non-medical names is dropped, and those rows are judged by name only.
    # This also covers the Item 3(d) clinic names, which are non-medical for
    # the purposes of the numerator.
    _pair = (df_bldg[['main_purps_nm', 'main_purps_cd']]
             .dropna(subset=['main_purps_nm', 'main_purps_cd'])
             .groupby(['main_purps_nm', 'main_purps_cd']).size().rename('n')
             .reset_index())

    _hos_pair = _pair[_pair['main_purps_nm'].isin(HOS_NMS)]
    _cd_nms = _pair.groupby('main_purps_cd')['main_purps_nm'].apply(set).to_dict()
    #   _pair only holds rows where both name and code are present, so the full
    #   set of codes has to come from the column directly.
    _all_cd = set(df_bldg['main_purps_cd'].dropna().unique())

    _derived = set(_hos_pair['main_purps_cd'])
    _cand_cd = _derived | (HOS_CDS_SEED & _all_cd)

    # Safeguard. A code that never co-occurs with a name has an empty name set
    # and passes; the seeded codes fall into this case, which is the point.
    _HOS_SET = set(HOS_NMS)
    HOS_CDS = {c for c in _cand_cd if _cd_nms.get(c, set()) <= _HOS_SET}
    _mixed = sorted(_cand_cd - HOS_CDS)

    log(f'\n[codes] HOS_CDS = {len(HOS_CDS)} '
        f'(derived {len(_derived)} + seeded {len(HOS_CDS_SEED & _all_cd)})')
    if _mixed:
        log(f'   WARNING: {len(_mixed)} code(s) seen with both medical and '
            f'non-medical names dropped (those rows are judged by name only)')
    _new_cd = sorted(_derived - HOS_CDS_SEED)
    if _new_cd:
        log(f'   WARNING: {len(_new_cd)} code(s) derived from the source are '
            f'absent from the seed list: {_new_cd}')
        log('            the code system has changed; extend _SEED5/_SEED_OLD.')
    _only_cd = int((df_bldg['main_purps_nm'].isna()
                    & df_bldg['main_purps_cd'].isin(HOS_CDS)).sum())
    log(f'   {_only_cd:,} row(s) identified by code alone (missing name)')

    lap('code set')

    # =========================================================================
    # 4. Cleaning - every aggregation below uses this one frame
    # =========================================================================
    log('\n' + '-' * 70)
    log('[clean]')
    log('-' * 70)

    df = df_bldg.dropna(subset=[PK]).copy()
    log(f'1) drop missing {PK} : rows {len(df_bldg):,} -> {len(df):,}  '
        f'({df[PK].nunique():,} building records)')

    #   Both text columns were normalised once, right after the load.
    #   `na=False` is required: with missing values, str.fullmatch returns an
    #   object dtype containing NaN rather than a boolean mask, and `~` then
    #   raises TypeError.
    _odd_m = (df['main_purps_cd'].notna()
              & ~df['main_purps_cd'].str.fullmatch(r'\d{5}', na=False))
    if _odd_m.any():
        log(f'   [check] {int(_odd_m.sum()):,} row(s) whose use code is not '
            f'five digits (superseded or malformed); identification falls '
            f'back on the use name for these')

    # Area to numeric.
    df['area'] = pd.to_numeric(df['area'], errors='coerce')
    log('   [area distribution]')
    log(df['area'].describe().to_string())

    # Negative area -> absolute value. This must happen BEFORE the positivity
    # filter, otherwise the conversion would never apply.
    _neg = df['area'] < 0
    n_neg = int(_neg.sum())
    n_neg_pk = int(df.loc[_neg, PK].nunique())
    log(f'2) negative area: {n_neg:,} rows -> absolute value '
        f'({n_neg_pk:,} building records affected)')
    df.loc[_neg, 'area'] = df.loc[_neg, 'area'].abs()

    # Drop zero and missing areas (negatives were already made positive).
    _bad_area = df['area'].isna() | (df['area'] <= 0)
    log(f'3) drop missing or zero area: {int(_bad_area.sum()):,} rows')
    df = df[~_bad_area]

    # Rows with a missing use name are NOT dropped. A floor of unknown use is
    # still floor area, and removing it would shrink the denominator and
    # overstate pu_rat. The numerator is judged on code or name, so a row with
    # a code is still identified; a row with neither only enters the
    # denominator.
    _bad_nm = df['main_purps_nm'].isna()
    _bad_cd = df['main_purps_cd'].isna()
    log(f'4) missing use name: {int(_bad_nm.sum()):,} rows '
        f'(for reference: missing use code {int(_bad_cd.sum()):,}, '
        f'name present and code missing {int((~_bad_nm & _bad_cd).sum()):,}, '
        f'name missing and code present {int((_bad_nm & ~_bad_cd).sum()):,})')
    log(f'   -> kept, contributing to the denominator only '
        f'({int(df.loc[_bad_nm, PK].nunique()):,} building records / '
        f'{df.loc[_bad_nm, "area"].sum():,.0f} m2)')

    lap('clean')
    log(f'\n[after cleaning] rows {len(df):,} / building records '
        f'{df[PK].nunique():,}')

    # =========================================================================
    # 5. Aggregation per building record
    # =========================================================================
    log('\n' + '-' * 70)
    log('[aggregate]')
    log('-' * 70)

    def _sum_by_pk(d, name):
        """Sum of area per building record."""
        return d.groupby(PK)['area'].sum().rename(name)

    # Both medical use and parking are identified by code OR name, so that
    # missing names and superseded codes compensate for each other.
    _hos_nm = df['main_purps_nm'].isin(HOS_NMS)
    _hos_cd = df['main_purps_cd'].isin(HOS_CDS)
    _is_hos = _hos_nm | _hos_cd
    _park_cd = df['main_purps_cd'].isin(PARKING_CDS)
    _park_nm = df['main_purps_nm'].isin(PARKING_NMS)
    _is_park = _park_cd | _park_nm

    flr_tot_area = _sum_by_pk(df, 'flr_tot_area')                    # incl. parking
    flr_hos_area = _sum_by_pk(df[_is_hos], 'flr_hos_area')           # medical
    flr_parking_area = _sum_by_pk(df[_is_park], 'flr_parking_area')  # parking

    log(f'medical rows {int(_is_hos.sum()):,} / '
        f'building records {df.loc[_is_hos, PK].nunique():,}')
    log(f'parking rows {int(_is_park.sum()):,} / '
        f'building records {df.loc[_is_park, PK].nunique():,}')

    # Cross-check: how much each identification route contributes.
    _h_only_cd = int((_hos_cd & ~_hos_nm).sum())
    _h_only_nm = int((_hos_nm & ~_hos_cd).sum())
    if _h_only_cd or _h_only_nm:
        log(f'[check] medical identification: {_h_only_cd:,} row(s) by code '
            f'only, {_h_only_nm:,} by name only')
    _p_diff = int((_park_cd ^ _park_nm).sum())
    if _p_diff:
        log(f'[check] parking identification: {_p_diff:,} row(s) where code and '
            f'name disagree; the union was used')

    out = pd.concat([flr_tot_area, flr_hos_area, flr_parking_area], axis=1)
    out[['flr_hos_area', 'flr_parking_area']] = \
        out[['flr_hos_area', 'flr_parking_area']].fillna(0)

    # Denominator = total floor area minus parking.
    out['flr_net_area'] = out['flr_tot_area'] - out['flr_parking_area']

    # pu_rat (%). Undefined (NaN) when the denominator is zero; not filled with 0.
    out['flr_main_purps_rat'] = np.where(
        out['flr_net_area'] > 0,
        out['flr_hos_area'] / out['flr_net_area'] * 100,
        np.nan,
    )

    out = out.reset_index()

    _n_zero_net = int((out['flr_net_area'] <= 0).sum())
    if _n_zero_net:
        log(f'[check] {_n_zero_net:,} building records with flr_net_area <= 0 '
            f'(parking only) -> flr_main_purps_rat = NaN')

    log(f'building records {out[PK].nunique():,} / rows {len(out):,}')
    log('\n[flr_main_purps_rat distribution]')
    log(out['flr_main_purps_rat'].describe().to_string())

    lap('aggregate')

    # =========================================================================
    # 6. Save
    # =========================================================================
    # Fixed column order, written WITH a header: S1 selects columns by name.
    OUT_COLS = [PK, 'flr_tot_area', 'flr_hos_area', 'flr_parking_area',
                'flr_net_area', 'flr_main_purps_rat']
    out = out[OUT_COLS]

    out_path = os.path.join(data_dir, pu_rat_file)
    out.to_csv(out_path, sep='|', index=False, encoding='utf-8-sig')
    log(f'\n[save] {out_path}')
    log(f'       columns: {OUT_COLS}')

    lap('save')
    _elapsed = _fmt_sec(time.perf_counter() - _t_start)
    log(f'\n[pu_rat] done  ({datetime.now():%Y-%m-%d %H:%M:%S})  '
        f'- total {_elapsed}')

except Exception as e:
    log(f'\n[ERROR] {type(e).__name__}: {e}')
    log(f'[time] failed after {_fmt_sec(time.perf_counter() - _t_start)}')
    print(f'[pu_rat] failed ({type(e).__name__}, '
          f'{_fmt_sec(time.perf_counter() - _t_start)} elapsed) -> log: {_log_note}',
          flush=True)
    raise
else:
    print(f'[pu_rat] done ({_elapsed}) -> log: {_log_note}', flush=True)
finally:
    if _log_fh is not None:
        _log_fh.close()
