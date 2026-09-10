# -*- coding: utf-8 -*-
"""
eda_validation. Technical validation figures.

Input  : data_output/hospital_energy_benchmarking_{N}.csv  (S3 Part C)
         data_prepared/{date} final_after_outlier {hira}_all.xlsx  (S3 Part B)
           - change-point model fit statistics, which the released CSV does
             not carry
Output : figures/*.png
         figures/tv_numbers_{N}.txt   - every number the Technical Validation
                                        section of the manuscript quotes
         data_output/table4_data_quality_{N}.xlsx
                                      - Table 4, the change-point model fit
                                        per sub-period and energy source

Run this through run_all_merge.py, which supplies bench_csv from S3. Run on its
own (F5) it takes the released CSV from data_output, but only when exactly one
is there, and it prints the file name and write time. With several released
CSVs present it stops rather than guessing which N to validate.

Figures (numbered as in the paper)
----------------------------------
6) fig6_interannual_consistency.png
   Interannual consistency: site EUI of consecutive years in three panels
   (2018–2019 / 2019–2020 / 2020–2021) with a trend line and R2.
7) fig7_survey_comparison.png
   EUI distribution by institution type with the medians of an independent
   national hospital survey.
8) fig8_external_benchmarks.png
   General and tertiary general hospitals only: the four annual EUI
   distributions with the national benchmark values of other countries.
"""

import datetime
import os

import numpy as np
import pandas as pd
import matplotlib as mpl
import matplotlib.pyplot as plt
import seaborn as sns
from scipy.stats import linregress

mpl.rcParams['axes.linewidth'] = 0.8
mpl.rcParams['xtick.major.width'] = 0.6
mpl.rcParams['ytick.major.width'] = 0.6
mpl.rcParams['xtick.labelsize'] = 11
mpl.rcParams['ytick.labelsize'] = 11
mpl.rcParams['font.family'] = 'sans-serif'
mpl.rcParams['font.sans-serif'] = ['Arial', 'Helvetica', 'DejaVu Sans']
mpl.rcParams['axes.unicode_minus'] = False
#   Mathtext ($...$) is rendered by the mathtext.* fonts, not font.family, so
#   without these four lines the exponents in 'kWh/m$^2$' and '$R^2$' come out
#   in DejaVu Sans while the surrounding text is Arial.
mpl.rcParams['mathtext.fontset'] = 'custom'
mpl.rcParams['mathtext.rm'] = 'Arial'
mpl.rcParams['mathtext.it'] = 'Arial:italic'
mpl.rcParams['mathtext.bf'] = 'Arial:bold'

#   Arial is resolved silently to the next available font when it is missing,
#   which produces figures that do not match the manuscript. Say so instead.
try:
    from matplotlib import font_manager as _fm
    _fm.findfont(_fm.FontProperties(family='Arial'), fallback_to_default=False)
    print('[font] Arial resolved')
except Exception:
    print('[font] WARNING: Arial not found - figures will not match the '
          'manuscript. Install Arial or change the font settings.')


# =============================================================================
# Settings (injectable from run_all_merge.py)
# =============================================================================
_BASE_DIR = os.path.dirname(os.path.abspath(__file__))

if 'figure_dir' not in globals():
    figure_dir = os.path.join(_BASE_DIR, 'figures')
if 'output_dir' not in globals():
    output_dir = os.path.join(_BASE_DIR, 'data_output')
#   The fit statistics (ns_*, r2_*) are not in the released CSV, so the
#   data-quality table reads them from the S3 Part B stage file.
if 'cpm_xlsx' not in globals():
    cpm_xlsx = None

os.makedirs(figure_dir, exist_ok=True)
os.makedirs(output_dir, exist_ok=True)

YEARS = (2018, 2019, 2020, 2021)


# -----------------------------------------------------------------------------
# Locate the released file
# -----------------------------------------------------------------------------
#   The path is supplied by run_all_merge.py, which takes it from S3, so the
#   validated file is always the one this run wrote. Searching the output folder
#   for a released CSV would risk validating a file left over from an earlier
#   run with a different N.
bench_csv = globals().get('bench_csv')
if bench_csv is None:
    #   Standalone run (F5 in an editor). Fall back to the released CSV in
    #   data_output, but only when exactly one is there, and name the file and
    #   its write time so the run cannot silently validate the wrong N.
    #   os.listdir, not glob: _BASE_DIR can contain '[' and ']' (as in
    #   'D:\\[02] ...'), which glob reads as a character class and then
    #   matches nothing.
    _out_dir = os.path.join(_BASE_DIR, 'data_output')
    _cands = sorted(
        os.path.join(_out_dir, _f)
        for _f in (os.listdir(_out_dir) if os.path.isdir(_out_dir) else [])
        if _f.startswith('hospital_energy_benchmarking_')
        and _f.endswith('.csv'))
    if len(_cands) == 1:
        bench_csv = _cands[0]
        _mt = datetime.datetime.fromtimestamp(os.path.getmtime(bench_csv))
        print('[eda_validation] bench_csv was not supplied - standalone run.')
        print(f'                 using {os.path.basename(bench_csv)} '
              f'(written {_mt:%Y-%m-%d %H:%M})')
    elif len(_cands) > 1:
        raise RuntimeError(
            'bench_csv was not supplied and data_output holds more than one '
            'released CSV, so the one to validate is ambiguous:\n'
            + ''.join(f'    {os.path.basename(c)}\n' for c in _cands)
            + '  -> delete the stale files, or set bench_csv at the top of '
              'this file, or run through run_all_merge.py.'
        )
    else:
        raise RuntimeError(
            'bench_csv was not supplied and no released CSV was found in '
            f'{os.path.join(_BASE_DIR, "data_output")}.\n'
            '  -> run this through run_all_merge.py with RUN_S3 = True and '
            'SAVE_RELEASE_CSV = True; it passes the path of the released CSV '
            'that S3 just wrote.'
        )

print(f'[eda_validation] input: {os.path.basename(bench_csv)}')
df = pd.read_csv(bench_csv)
print(f'  {len(df):,} rows x {df.shape[1]} cols')

_need = ['gfa', 'hos_ty_eng'] + [f'site_sum_{y}' for y in YEARS]
_missing = [c for c in _need if c not in df.columns]
if _missing:
    raise KeyError(
        f'Columns missing from the released CSV: {_missing}\n'
        f'  -> check RELEASE_COLS in S3_combine.py.'
    )


# =============================================================================
# Helpers
# =============================================================================
EUI_UNIT = 'kWh/m$^2$·yr'

#   Reference values used by Figures 7 and 8 and reported in tv_numbers.txt.
#   Kept here so the figure and the reported numbers cannot drift apart.
#     SURVEY : medians of the independent national hospital survey, with the
#              number of institutions behind each one (the samples are small,
#              so the values are drawn as reference lines only).
#     EXTERNAL: UK CIBSE TM46 / Canada ENERGY STAR / U.S. ENERGY STAR national
#              median converted from kBtu/ft2.
SURVEY = {'GH': (329.3, 42), 'H': (271.8, 23), 'CH': (232.1, 17)}
EXTERNAL = {'UK': 510.0, 'Canada': 611.1, 'USA': 739.1}
GH_TH = ('GH', 'TH')
US_MEDIAN_GFA = 30_286          # ENERGY STAR, median GFA of U.S. hospitals (m2)

_TV = []                        # lines written to tv_numbers.txt


def tv(line=''):
    """Record a line for tv_numbers.txt and echo it."""
    _TV.append(line)
    print(line)


def write_tv_numbers():
    out = os.path.join(figure_dir, f'tv_numbers_{len(df)}.txt')
    with open(out, 'w', encoding='utf-8') as fh:
        fh.write('\n'.join(_TV) + '\n')
    print(f'[saved] {out}')
TITLE_PAD = 20      # gap between a panel title and the axes
LABEL_PAD = 12      # gap between an axis label and its ticks


def eui(d, year):
    """Annual site energy use intensity (kWh/m2 per year). NaN if gfa is 0."""
    return (d[f'site_sum_{year}'] / d['gfa']).replace([np.inf, -np.inf], np.nan)


def save_fig(fname):
    """Write the current figure. Whether this step runs at all is
    decided by RUN_* in run_all_merge.py, so there is no per-figure
    switch here."""
    out = os.path.join(figure_dir, fname)
    plt.savefig(out, dpi=300, bbox_inches='tight')
    print(f'[saved] {out}')
    plt.close()


tv('=' * 68)
tv(f'Technical Validation numbers   (N = {len(df)})')
tv('=' * 68)
tv('')


# =============================================================================
# Table 4. Change-point model fit  (Technical Validation 4.1)
# =============================================================================
#   Institutions are counted where the model results carry a fit for the
#   source. That is not the same as the number supplied with it by the billing
#   records: the two differ, so the difference is reported in tv_numbers rather
#   than left implicit in the table. The fit over the summed consumption
#   (ns_0 / r2_0) is not released and is not reported.
SOURCES = [('elec', 11, 'Electricity'),
           ('gas', 12, 'Gas'),
           ('heat', 13, 'District heating')]
SUBPERIODS = [(2018, 2019), (2020, 2021)]
R2_GOOD = 0.7
R2_POOR = 0.3
N_MONTHS = 24           # a complete sub-period


def _locate_cpm_xlsx():
    """Sub-period stage file of S3 Part B ('final_after_outlier ..._all')."""
    if cpm_xlsx is not None:
        return cpm_xlsx
    _dir = os.path.join(_BASE_DIR, 'data_prepared')
    #   os.listdir, not glob, for the same reason as bench_csv above.
    cands = sorted(
        os.path.join(_dir, f)
        for f in (os.listdir(_dir) if os.path.isdir(_dir) else [])
        if 'final_after_outlier' in f and f.endswith('_all.xlsx')
        and not f.startswith('~$'))
    if len(cands) == 1:
        return cands[0]
    if not cands:
        raise RuntimeError(
            'The data-quality table needs the S3 Part B stage file '
            "('final_after_outlier ..._all.xlsx'), which was not found in "
            f'{_dir}.\n  -> run through run_all_merge.py with RUN_S3 = True, '
            'or set cpm_xlsx at the top of this file.')
    raise RuntimeError(
        'More than one after_outlier _all file is present, so the one to '
        'report is ambiguous:\n'
        + ''.join(f'    {os.path.basename(c)}\n' for c in cands)
        + '  -> delete the stale files, or set cpm_xlsx at the top of this '
          'file.')


def build_data_quality_table(dcpm):
    """One row per sub-period x energy source, in the order of the table."""
    rows = []
    for yb, ya in SUBPERIODS:
        pair = f'{yb}_{ya}'
        for key, code, label in SOURCES:
            supplied = ((dcpm[f'site_{key}_{yb}'].fillna(0) > 0)
                        | (dcpm[f'site_{key}_{ya}'].fillna(0) > 0))
            ns = dcpm.loc[supplied, f'ns_{code}_{pair}']
            r2 = dcpm.loc[supplied, f'r2_{code}_{pair}'].dropna()
            rows.append({
                'Sub-period': f'{yb}–{ya}',
                'Energy source': label,
                'Institutions (n)': int(ns.notna().sum()),
                f'Fits with {N_MONTHS} monthly records (n)':
                    int((ns == N_MONTHS).sum()),
                'Fewest monthly records (n)': (int(ns.min())
                                               if ns.notna().any() else None),
                'Median R2': round(float(r2.median()), 2) if len(r2) else None,
                'R2 Q1': round(float(r2.quantile(0.25)), 2) if len(r2) else None,
                'R2 Q3': round(float(r2.quantile(0.75)), 2) if len(r2) else None,
                f'R2 >= {R2_GOOD} (%)': (round(float((r2 >= R2_GOOD).mean() * 100))
                                         if len(r2) else None),
                f'R2 < {R2_POOR} (n)': int((r2 < R2_POOR).sum()) if len(r2) else 0,
                #   Not a table column: kept so that the gap below can be
                #   reported without putting an unexplained count in the table.
                '_supplied': int(supplied.sum()),
            })
    return pd.DataFrame(rows)


TABLE_COLS = [c for c in (
    'Sub-period', 'Energy source', 'Institutions (n)',
    f'Fits with {N_MONTHS} monthly records (n)', 'Fewest monthly records (n)',
    'Median R2', 'R2 Q1', 'R2 Q3', f'R2 >= {R2_GOOD} (%)',
    f'R2 < {R2_POOR} (n)')]


_cpm_fp = _locate_cpm_xlsx()
_dcpm = pd.read_excel(_cpm_fp)
if len(_dcpm) != len(df):
    raise RuntimeError(
        f'{os.path.basename(_cpm_fp)} holds {len(_dcpm):,} rows but the '
        f'released CSV holds {len(df):,}. The two must be the same population '
        'for the data-quality table to describe the released dataset.\n'
        '  -> re-run S3 so that the stage file and the release come from the '
        'same run.')

_tbl = build_data_quality_table(_dcpm)
_tbl_fp = os.path.join(output_dir, f'table4_data_quality_{len(df)}.xlsx')
_tbl[TABLE_COLS].to_excel(_tbl_fp, index=False)
print(f'[saved] {_tbl_fp}')

tv('[4.1] Completeness and model fit  (Table 4)')
for _r in _tbl.to_dict('records'):
    tv(f'  {_r["Sub-period"]} {_r["Energy source"]:<17} '
       f'institutions = {_r["Institutions (n)"]:,}   '
       f'{N_MONTHS}-month fits = {_r[f"Fits with {N_MONTHS} monthly records (n)"]:,}   '
       f'fewest records = {_r["Fewest monthly records (n)"]}   '
       f'R2 = {_r["Median R2"]:.2f} ({_r["R2 Q1"]:.2f}-{_r["R2 Q3"]:.2f})   '
       f'>= {R2_GOOD} = {_r[f"R2 >= {R2_GOOD} (%)"]:.0f}%   '
       f'< {R2_POOR} = {_r[f"R2 < {R2_POOR} (n)"]}')
for _r in _tbl.to_dict('records'):
    _gap = _r['_supplied'] - _r['Institutions (n)']
    if _gap:
        tv(f'  [gap] {_r["Sub-period"]} {_r["Energy source"]}: '
           f'{_gap} of {_r["_supplied"]:,} institutions supplied with this '
           f'source have no fit (not a table column)')
tv('')


# =============================================================================
# Figure 6. Interannual consistency (three panels)
# =============================================================================
PAIRS = [
    ('(a) 2018–2019', 2018, 2019),
    ('(b) 2019–2020', 2019, 2020),
    ('(c) 2020–2021', 2020, 2021),
]

#   One shared limit for the three panels so they stay comparable, rounded up
#   from the largest EUI in any of the six series. Hard-coding it risks
#   clipping a point while the legend still counts it: at N = 1,299 the
#   2020-2021 panel had one institution above the former 800 bound.
_AX_MAX = max(eui(df, y).max() for y in YEARS)
AX_MAX = float(np.ceil(_AX_MAX / 100.0) * 100)

_, axes = plt.subplots(1, 3, figsize=(18, 6))

tv('[4.2] Interannual consistency  (Figure 6)')
_fig6 = {}

for ax, (title_txt, yx, yy) in zip(axes, PAIRS):
    x, y = eui(df, yx), eui(df, yy)
    m = x.notna() & y.notna()
    x, y = x[m], y[m]

    ax.scatter(x, y, alpha=0.55, label=f'Data (n = {len(x):,})', color='teal', s=42)

    slope, intercept, r_value, _, _ = linregress(x, y)
    xline = np.linspace(x.min(), x.max(), 200)
    ax.plot(xline, slope * xline + intercept, color='black', linestyle='--',
            linewidth=2, label=f'Trend line ($R^2$={r_value ** 2:.3f})')

    _off = int(((x > AX_MAX) | (y > AX_MAX)).sum())
    _fig6[f'{yx}-{yy}'] = (r_value ** 2, slope, len(x))
    tv(f'  {yx}-{yy}: n = {len(x):,}   R2 = {r_value ** 2:.4f}   '
       f'slope = {slope:.4f}   off-plot = {_off}')

    ax.set_title(title_txt, fontsize=22, y=1.0, pad=TITLE_PAD)
    ax.set_xlabel(f'{yx} Site EUI ({EUI_UNIT})', fontsize=18)
    ax.set_ylabel(f'{yy} Site EUI ({EUI_UNIT})', fontsize=18,
                  labelpad=LABEL_PAD)
    ax.tick_params(axis='both', labelsize=18)
    ax.legend(loc='upper left', fontsize=15, frameon=True)
    ax.grid(False)
    ax.set_xlim(0, AX_MAX)
    ax.set_ylim(0, AX_MAX)

plt.tight_layout()
save_fig('fig6_interannual_consistency.png')

_r2 = {k: v[0] for k, v in _fig6.items()}
_lo = min(_r2, key=_r2.get)
tv(f'  axis limit      : 0 - {AX_MAX:,.0f} (largest EUI in any year '
   f'= {_AX_MAX:.0f})')
tv(f'  R2 range        : {min(_r2.values()):.3f} - {max(_r2.values()):.3f}')
tv(f'  lowest R2       : {_lo} ({_r2[_lo]:.4f})')
tv(f'  subperiod-boundary pair 2019-2020: {_r2["2019-2020"]:.4f}'
   f'  ({"the lowest" if _lo == "2019-2020" else "not the lowest"})')
tv('')


# =============================================================================
# Figures 7-8. EUI distributions with reference values
# =============================================================================
def plot_density_with_ref(d, years, group_col, exclude_groups, ref_dict=None,
                          figsize=(6, 5), n_fill=0, alpha=0.30,
                          linewidth=1.0, bw_adjust=1.1, fill=True, xlim=None,
                          save_path=None):
    """Overlay the EUI distributions of several years and mark reference values.

    years : list of years; the legend label is the year itself.
    """
    sns.set_style('whitegrid')
    ref_dict = ref_dict or {}

    d_plot = d[~d[group_col].isin(exclude_groups)]

    colors = ['tab:blue', 'tab:orange', 'tab:green', 'tab:red'][:len(years)]

    series = [eui(d_plot, y).dropna() for y in years]
    medians = [s.median() for s in series]

    _, ax = plt.subplots(figsize=figsize)
    ax.grid(False)

    for i, (s, med, year, color) in enumerate(zip(series, medians, years, colors)):
        sns.kdeplot(x=s, ax=ax, fill=(fill and i == n_fill), common_norm=False,
                    bw_adjust=bw_adjust, alpha=alpha, linewidth=linewidth,
                    color=color, label=f'{year} (median = {med:.1f}, n = {len(s):,})')

    # Reference lines, labelled from the top down.
    y_min, y_max = ax.get_ylim()
    ax.set_ylim(y_min, y_max * 1.25)
    _, y_max = ax.get_ylim()
    for i, (ref_name, ref_value) in enumerate(ref_dict.items()):
        ax.axvline(ref_value, color='black', linestyle='--', linewidth=1.5)
        ax.text(ref_value + 5, y_max * (0.6 - i * 0.08),
                f'{ref_name} = {ref_value:.1f}', va='top', ha='left',
                fontsize=11, color='black',
                bbox=dict(facecolor='white', edgecolor='none', alpha=0.6, pad=1.2))

    ax.set_xlabel(f'Site EUI ({EUI_UNIT})', fontsize=13)
    ax.set_ylabel('Density', fontsize=13)
    ax.tick_params(axis='both', labelsize=11)
    ax.legend(fontsize=10, frameon=True, loc='upper right')
    if xlim is not None:
        ax.set_xlim(xlim)

    plt.tight_layout()
    save_fig(save_path)


def plot_density_by_hos_type_with_ref(d, year, exclude_groups,
                                      group_col='hos_ty_eng', ref_dict=None,
                                      figsize=(6, 5),
                                      alpha=0.18, linewidth=1.0, bw_adjust=1.1,
                                      fill=True, xlim=None,
                                      save_path=None):
    """EUI distribution of one year by institution type, with per-type reference
    values drawn in matching colours.

    Each ref_dict entry is either a scalar or a dict with the keys value,
    color, linestyle, linewidth and text.
    """
    sns.set_style('whitegrid')
    ref_dict = ref_dict or {}

    d_plot = d[~d[group_col].isin(exclude_groups)].copy()

    #   Sorted, not order of appearance: the colour a type receives must not
    #   depend on which row happens to come first in the input file, because
    #   ref_dict pins a colour per type.
    groups = sorted(d_plot[group_col].dropna().unique().tolist())
    if not groups:
        raise ValueError(f"no valid group values in '{group_col}'")

    labels = {g: str(g) for g in groups}

    base = ['tab:blue', 'tab:orange', 'tab:green', 'tab:red',
            'tab:purple', 'tab:brown']
    color_map = {g: base[i % len(base)] for i, g in enumerate(groups)}

    _, ax = plt.subplots(figsize=figsize)
    ax.grid(False)

    for g in groups:
        s = eui(d_plot[d_plot[group_col] == g], year).dropna()
        if len(s) <= 1:
            print(f'[skip] {g}: {len(s)} observation(s), KDE not possible')
            continue
        sns.kdeplot(x=s, ax=ax, fill=fill, common_norm=False, bw_adjust=bw_adjust,
                    alpha=alpha, linewidth=linewidth, color=color_map[g],
                    label=f'{labels[g]} (median = {s.median():.1f}, n = {len(s):,})')

    orig_y_max = ax.get_ylim()[1]
    ax.set_ylim(0, orig_y_max * 1.40)
    new_y_max = ax.get_ylim()[1]

    for i, (ref_name, info) in enumerate(ref_dict.items()):
        if isinstance(info, dict):
            v = info.get('value')
            c = info.get('color', 'black')
            ls = info.get('linestyle', '--')
            lw = info.get('linewidth', 1.5)
            txt = info.get('text', f'{ref_name} = {v:.1f}')
        else:
            v, c, ls, lw, txt = info, 'black', '--', 1.5, f'{ref_name} = {info:.1f}'
        ax.axvline(v, color=c, linestyle=ls, linewidth=lw)
        ax.text(v * 1.05,
                orig_y_max + (new_y_max - orig_y_max) * (0.15 - i * 0.18),
                txt, va='top', ha='left', fontsize=11, color=c,
                bbox=dict(facecolor='white', edgecolor='none', alpha=0.6, pad=1.2))

    ax.set_xlabel(f'{year} Site EUI ({EUI_UNIT})', fontsize=13)
    ax.set_ylabel('Density', fontsize=13)
    ax.tick_params(axis='both', labelsize=11)
    ax.legend(fontsize=10, frameon=True, loc='upper right')
    if xlim is not None:
        ax.set_xlim(xlim)

    plt.tight_layout()
    save_fig(save_path)


_F7_LINE_COLOR = dict(zip(sorted(SURVEY),
                          ('tab:blue', 'tab:orange', 'tab:green')))

# -- Figure 7. By institution type, against the national survey medians -------
#    The survey samples are small (GH 42 / H 23 / CH 17), so the values are
#    shown as reference lines only.
plot_density_by_hos_type_with_ref(
    df, year=2018,
    group_col='hos_ty_eng',
    exclude_groups=('KH', 'TH'),
    #   The colour must follow the type, not the order of SURVEY: the plotting
    #   helper assigns curve colours over sorted(group values).
    ref_dict={
        f'Survey {t} (n = {n})': {'value': v, 'color': _F7_LINE_COLOR[t]}
        for t, (v, n) in SURVEY.items()
    },
    alpha=0.18, linewidth=1.0, bw_adjust=1.1,
    xlim=(0, 1000),
    save_path='fig7_survey_comparison.png',
)

tv('[4.3] Comparison with the national hospital survey  (Figure 7, 2018)')
_diffs = []
for _t, (_sv, _n) in SURVEY.items():
    _s = eui(df[df['hos_ty_eng'] == _t], 2018).dropna()
    _med = _s.median()
    _d = (_med - _sv) / _sv * 100
    _diffs.append(_d)
    tv(f'  {_t}: ours median = {_med:.1f} (n = {len(_s):,})   '
       f'survey = {_sv:.1f} (N = {_n})   difference = {_d:+.2f}%   '
       f'max = {_s.max():.0f}, above the 1,000 axis limit = '
       f'{int((_s > 1000).sum())}')
tv(f'  absolute differences: {min(abs(d) for d in _diffs):.2f}% - '
   f'{max(abs(d) for d in _diffs):.2f}%   '
   f'(signs: {", ".join(f"{t}{d:+.1f}" for t, d in zip(SURVEY, _diffs))})')
tv('')

# -- Figure 8. General and tertiary general hospitals only --------------------
#    UK     : CIBSE TM46
#    Canada : ENERGY STAR (Canada)
#    USA    : ENERGY STAR (U.S. national median, converted from kBtu/ft2)
plot_density_with_ref(
    df, years=YEARS,
    group_col='hos_ty_eng',
    exclude_groups=['H', 'KH', 'CH'],       # leaves GH + TH
    ref_dict=EXTERNAL,
    n_fill=0, linewidth=1.0, bw_adjust=1.1,
    xlim=(0, 1000),
    save_path='fig8_external_benchmarks.png',
)

tv('[4.3] Comparison with external national benchmarks  (Figure 8, GH + TH)')
_g = df[df['hos_ty_eng'].isin(GH_TH)]
tv(f'  general and tertiary hospitals: n = {len(_g):,}   '
   f'median gfa = {_g["gfa"].median():,.0f} m2')
tv(f'  median gfa, all institution types = {df["gfa"].median():,.0f} m2   '
   f'(NOT the subset the EUI comparison uses)')
tv(f'  U.S. hospitals, ENERGY STAR median gfa = {US_MEDIAN_GFA:,} m2   '
   f'-> {US_MEDIAN_GFA / _g["gfa"].median():.2f}x the GH+TH median')
for _y in YEARS:
    _s = eui(_g, _y).dropna()
    _pcts = '  '.join(f'{k} p{(_s < v).mean() * 100:.0f}'
                      for k, v in EXTERNAL.items())
    tv(f'  {_y}: median = {_s.median():.1f} (n = {len(_s):,})   '
       f'max = {_s.max():.0f}, above the 1,000 axis limit = '
       f'{int((_s > 1000).sum())}   percentile of each benchmark: {_pcts}')
_s18 = eui(_g, 2018).dropna()
tv('  benchmark / 2018 GH+TH median: '
   + '  '.join(f'{k} {v / _s18.median():.2f}x' for k, v in EXTERNAL.items()))
tv('')
write_tv_numbers()

print('\n[eda_validation] done')
