# -*- coding: utf-8 -*-
"""
cpm_besig. Change-point models fitted with BE-sig (CPM = True), called from
S1_SB_merge.py / S1_MB_merge.py through attach_cpm().

BE-sig is downloaded at the pinned commit into third_party/ on the first run.
For each building left after the S1 merge and each sub-period, one model is
fitted per energy source (11, 12, 13) and for their sum (0), on the monthly
kWh of the months with a record. Settings: candidate models 1p, 3p_h, 3p_c,
5p; lowest RMSE; multistart, 10 starts, seed 0; 4 decimals. The baseload /
heating / cooling components are the split of the model prediction. See
README.md for details.
"""

import os
import sys
import time

import numpy as np
import pandas as pd


# =============================================================================
# Settings
# =============================================================================
BESIG_REPO = 'https://github.com/brainwt/Building-Energy-Signature-aka-CPM'
BESIG_COMMIT = '75c841c0b5f75640679c7ed3db62ef5cce47602b'

MODEL_TYPES = ('1p', '3p_h', '3p_c', '5p')
N_STARTS = 10
SEED = 0
ROUND_DIGITS = 4

# Energy source codes as text ('11', '12', '13'), plus '0' for the sum of the
# three. '0' is the suffix the CPM columns of the sum carry in S2 (ns_0, r2_0).
KINDS = ('11', '12', '13')
TOTAL = '0'

# Fields written per energy source (column name = {field}_{kind}).
CPM_FIELDS = ['cpm_ty', 'b0', 'b1', 'b2', 'b3', 'b4',
              'ns', 'cvrmse', 'rmse', 'nmbe', 'r2']


# =============================================================================
# BE-sig source
# =============================================================================
def besig_path(third_party_dir):
    return os.path.join(third_party_dir, f'besig_{BESIG_COMMIT[:7]}')


def fetch_besig(third_party_dir):
    """Download the pinned BE-sig commit once and put its src/ on sys.path.

    Returns the folder of the bundled monthly weather files.
    """
    import shutil
    import subprocess
    import urllib.request
    import zipfile

    root = besig_path(third_party_dir)
    src = os.path.join(root, 'src')
    if not os.path.isdir(os.path.join(src, 'besig')):
        os.makedirs(third_party_dir, exist_ok=True)
        if shutil.which('git'):
            print(f'[CPM] git clone {BESIG_REPO} -> {root}', flush=True)
            subprocess.run(['git', 'clone', '--quiet', BESIG_REPO + '.git', root],
                           check=True)
            subprocess.run(['git', '-C', root, 'checkout', '--quiet', BESIG_COMMIT],
                           check=True)
        else:
            url = f'{BESIG_REPO}/archive/{BESIG_COMMIT}.zip'
            print(f'[CPM] download {url}', flush=True)
            zpath = root + '.zip'
            urllib.request.urlretrieve(url, zpath)
            with zipfile.ZipFile(zpath) as z:
                top = z.namelist()[0].split('/')[0]
                z.extractall(third_party_dir)
            os.replace(os.path.join(third_party_dir, top), root)
            os.remove(zpath)
    if src not in sys.path:
        sys.path.insert(0, src)
    return os.path.join(root, 'data', 'weather')


def check_weather_years(weather_dir, years):
    """Stop before fitting if BE-sig ships no temperature file for a year."""
    missing = [y for y in years
               if not os.path.exists(os.path.join(
                   weather_dir, f'T_weather_all_monthly_{y}.csv'))]
    if missing:
        raise FileNotFoundError(
            f'BE-sig commit {BESIG_COMMIT[:7]} has no monthly temperature for '
            f'{missing} (looked in {weather_dir}).\n'
            f'  -> restrict YEAR_PAIRS to the years it covers, or pin a commit '
            f'that ships them.')


# =============================================================================
# Fitting
# =============================================================================
_W = None          # {(station, 'YYYYMM'): mean temperature}, one per process


def _init_worker(src, weather_dir, years):
    """Load the temperatures once per process (and make BE-sig importable)."""
    global _W
    if src not in sys.path:
        sys.path.insert(0, src)
    frames = []
    for y in years:
        fp = os.path.join(weather_dir, f'T_weather_all_monthly_{y}.csv')
        frames.append(pd.read_csv(fp, dtype={'USE_YM': str},
                                  usecols=['loc', 't_avg', 'USE_YM']))
    w = pd.concat(frames)
    _W = {(int(r.loc), r.USE_YM.strip()): float(r.t_avg) for r in w.itertuples()}


def _fit_series(months, y, station):
    """One monthly series -> (fitted values, monthly components)."""
    from besig import AnalysisConfig
    from besig.pipeline import run_cpm
    from besig.models import MODELS
    from besig.disaggregation import disaggregate

    t = np.array([_W.get((station, m), np.nan) for m in months], float)
    ok = ~np.isnan(t)
    months = [m for m, k in zip(months, ok) if k]
    t, y = t[ok], np.asarray(y, float)[ok]
    n = len(y)
    if n <= 1:
        # Too short to fit: no model statistics, measured value as baseload.
        comp = pd.DataFrame({'ym': months, 'base': y, 'htg': 0.0, 'clg': 0.0})
        return {'cpm_ty': '1p'}, comp

    # A model needs more months than parameters.
    models = tuple(m for m in MODEL_TYPES if MODELS[m].n_params < n)
    cfg = AnalysisConfig(energy_path='-', weather_dir='-', make_plots=False,
                         model_types=models, strategy='multistart',
                         n_starts=N_STARTS, seed=SEED)
    res = run_cpm(t, y, cfg, with_disaggregation=False)
    best = min(res, key=lambda r: r.rank)          # rank 1 = lowest RMSE
    s = best.stats
    d = disaggregate(best.cpm_type, s.coefficients, t)
    rec = {'cpm_ty': best.cpm_type,
           **{f'b{i}': s.coefficients[i] for i in range(5)},
           'ns': s.ns, 'rmse': s.rmse, 'nmbe': s.nmbe, 'cvrmse': s.cvrmse,
           'r2': s.r2}
    comp = pd.DataFrame({'ym': months, 'base': d.base_series,
                         'htg': d.heating_series, 'clg': d.cooling_series})
    return rec, comp


def _job(args):
    """One building key x one sub-period -> rows for the four series."""
    key, period, station, g = args
    series = {k: v.groupby('use_ym')['kwh'].sum()
              for k, v in g.groupby('engy_kind_cd')}
    series[TOTAL] = g.groupby('use_ym')['kwh'].sum()
    rows = []
    for kind, s in series.items():
        row = {'key': key, 'period': period, 'kind': kind, 'station': station}
        try:
            rec, comp = _fit_series(list(s.index), s.values, station)
        except Exception as e:
            # One failed series must not stop the run. It is reported at the
            # end; without components, attach_cpm puts its measured value in baseload.
            rows.append({**row, 'error': str(e)[:200]})
            continue
        row.update(rec)
        if kind != TOTAL:
            # Annual components of the metered sources.
            comp['year'] = comp['ym'].str[:4]
            for yr, gg in comp.groupby('year'):
                for c in ('base', 'htg', 'clg'):
                    row[f'{c}_{yr}'] = float(gg[c].sum())
        rows.append(row)
    return rows


def fit_all(usage, stations, year_pairs, third_party_dir, n_jobs=None):
    """Fit every target key and sub-period.

    usage     monthly records of the target keys, columns
              key, engy_kind_cd ('11'/'12'/'13'), use_ym ('YYYYMM'), kwh
    stations  {key: KMA station code}
    Returns one row per key x sub-period x energy source with the fitted
    values and the annual components (base_{year}, htg_{year}, clg_{year}).
    """
    weather_dir = fetch_besig(third_party_dir)
    src = os.path.join(besig_path(third_party_dir), 'src')
    years = sorted({y for p in year_pairs for y in p})
    check_weather_years(weather_dir, years)

    jobs, no_station = [], 0
    for key, g in usage.groupby('key'):
        st = stations.get(key)
        if st is None or pd.isna(st):
            no_station += 1
            continue
        for yb, ya in year_pairs:
            gg = g[g['use_ym'].str[:4].isin((str(yb), str(ya)))]
            if len(gg):
                jobs.append((key, f'{yb}_{ya}', int(st), gg))
    if n_jobs is None:
        n_jobs = max(1, (os.cpu_count() or 2) - 1)
    interactive = hasattr(sys, 'ps1') or 'spyder_kernels' in sys.modules
    if interactive:
        n_jobs = 1
    print(f'[CPM] {len(jobs):,} fits (key x sub-period), '
          f'{no_station:,} key(s) without a station skipped, '
          f'{n_jobs} process(es)', flush=True)

    rows, t0 = [], time.time()
    if n_jobs > 1:
        from multiprocessing import Pool
        with Pool(n_jobs, initializer=_init_worker,
                  initargs=(src, weather_dir, years)) as p:
            for i, r in enumerate(p.imap_unordered(_job, jobs, chunksize=8)):
                rows += r
                if i and i % 500 == 0:
                    print(f'  {i:,}/{len(jobs):,}  {time.time() - t0:,.0f}s',
                          flush=True)
    else:
        _init_worker(src, weather_dir, years)
        for i, a in enumerate(jobs):
            rows += _job(a)
            if i and i % 500 == 0:
                print(f'  {i:,}/{len(jobs):,}  {time.time() - t0:,.0f}s',
                      flush=True)

    res = pd.DataFrame(rows)
    num = [c for c in CPM_FIELDS if c in res.columns and c != 'cpm_ty']
    res[num] = res[num].astype(float).round(ROUND_DIGITS)
    n_err = int(res['error'].notna().sum()) if 'error' in res.columns else 0
    print(f'[CPM] done in {time.time() - t0:,.0f}s, {len(res):,} series, '
          f'{n_err:,} failed', flush=True)
    return res


def to_wide(res, pk_out, period):
    """Rows of one sub-period -> one row per key, columns {field}_{kind}.

    Same layout as the CPM files the pipeline reads with CPM = False (ns_11,
    r2_0, ...), plus the fitting period in date_s / date_e.
    """
    yb, ya = period.split('_')
    r = res[res['period'] == period]
    wide = r.pivot_table(index='key', columns='kind',
                         values=[c for c in CPM_FIELDS if c in r.columns],
                         aggfunc='first').reset_index()
    wide.columns = [c[0] if c[0] == 'key' else f'{c[0]}_{c[1]}'
                    for c in wide.columns]
    wide = wide.rename(columns={'key': pk_out})
    wide.insert(1, 'date_s', f'x{yb}01')
    wide.insert(2, 'date_e', f'x{ya}12')
    # Every field for every source, so S2 always finds ns_13, r2_13 and so on.
    for f in CPM_FIELDS:
        for k in (TOTAL,) + KINDS:
            if f'{f}_{k}' not in wide.columns:
                wide[f'{f}_{k}'] = np.nan
    return wide


def components_long(res, year_pairs):
    """Annual components per key x source x year, from the fit of the
    sub-period that contains the year. Columns: key, engy_kind_cd, year,
    base, htg, clg (kWh)."""
    out = []
    metered = res[res['kind'] != TOTAL]
    for yb, ya in year_pairs:
        r = metered[metered['period'] == f'{yb}_{ya}']
        for y in (yb, ya):
            cols = {f'base_{y}': 'base', f'htg_{y}': 'htg', f'clg_{y}': 'clg'}
            have = [c for c in cols if c in r.columns]
            if not have:
                continue
            d = r[['key', 'kind'] + have].rename(columns=cols)
            d = d.rename(columns={'kind': 'engy_kind_cd'})
            d['year'] = str(y)
            out.append(d)
    if not out:
        return pd.DataFrame(columns=['key', 'engy_kind_cd', 'year',
                                     'base', 'htg', 'clg'])
    return pd.concat(out, ignore_index=True)


# =============================================================================
# S1 hook
# =============================================================================
def attach_cpm(df, pk, monthly, pair, third_party_dir, n_jobs=None,
               out_csv=None):
    """Fit the buildings of one S1 table and add the results to it.

    df       S1 table of one scope and one sub-period (after the merge)
    pk       its building key ('mgm_bld_pk' or 'mgm_upper_bld_pk')
    monthly  S0 monthly series (after_*-monthly.csv): key, engy_kind_cd,
             use_ym, kwh
    pair     (year_b, year_a)
    out_csv  where to keep every fitted series, for checking

    Returns the table with the CPM columns ({field}_{0|11|12|13}, date_s,
    date_e) and the components replaced; rows without any fit are removed.
    """
    from common import (SOURCE_SUFFIX, SOURCE_TOTAL, add_component_totals)

    yb, ya = pair
    period = f'{yb}_{ya}'
    df = df.copy()
    key = df[pk].astype(str).str.strip()

    stations = (pd.DataFrame({'key': key, 'st': df['kma_obsrvn_cd']})
                .drop_duplicates('key').set_index('key')['st'].to_dict())
    usage = monthly[monthly['key'].isin(set(key))]
    res = fit_all(usage, stations, [pair], third_party_dir, n_jobs=n_jobs)
    if out_csv:
        res.to_csv(out_csv, index=False, encoding='utf-8-sig')

    # CPM columns, placed where the CPM join put them with CPM = False
    # (in front of the energy columns).
    wide = to_wide(res, '_key', period).set_index('_key')
    fitted = key.isin(wide.index)
    n_drop = int((~fitted).sum())
    if n_drop:
        print(f'[CPM] {n_drop:,} row(s) removed: no series could be fitted '
              f'(no station, or no month with a temperature)', flush=True)
    df, key = df[fitted.values].copy(), key[fitted.values]
    cpm_cols = list(wide.columns)
    add = wide.reindex(key.values)
    add.index = df.index
    at = (df.columns.get_loc(f'site_sum_{yb}')
          if f'site_sum_{yb}' in df.columns else len(df.columns))
    df = pd.concat([df.iloc[:, :at], add[cpm_cols], df.iloc[:, at:]], axis=1)

    # Components: the split of the fitted models. A source with no component
    # (no fit, or no month with a temperature) is all baseload, as a series
    # too short to fit.
    comp = components_long(res, [pair])
    for y in (yb, ya):
        cy = comp[comp['year'] == str(y)]
        for e, sx in SOURCE_SUFFIX.items():
            c = (cy[cy['engy_kind_cd'] == str(e)]
                 .drop_duplicates('key').set_index('key'))
            tot = pd.to_numeric(df[f'site_{SOURCE_TOTAL[e]}_{y}'],
                                errors='coerce').fillna(0)
            base = key.map(c['base'])
            df[f'site_base_{sx}_{y}'] = base.where(base.notna(), tot).values
            df[f'site_htg_{sx}_{y}'] = key.map(c['htg']).fillna(0).values
            df[f'site_clg_{sx}_{y}'] = key.map(c['clg']).fillna(0).values
        add_component_totals(df, f'_{y}')
    return df
