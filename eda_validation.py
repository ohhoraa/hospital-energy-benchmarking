# -*- coding: utf-8 -*-
"""
eda_validation. Technical validation figures.

Input  : data_output/energy_benchmarking_{N}.csv  (S3 Part C)
Output : figures/*.png

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
mpl.rcParams['mathtext.fontset'] = 'custom'
mpl.rcParams['mathtext.rm'] = 'Arial'
mpl.rcParams['mathtext.it'] = 'Arial:italic'
mpl.rcParams['mathtext.bf'] = 'Arial:bold'

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

os.makedirs(figure_dir, exist_ok=True)

YEARS = (2018, 2019, 2020, 2021)


# -----------------------------------------------------------------------------
# Locate the released file
# -----------------------------------------------------------------------------
bench_csv = globals().get('bench_csv')
if bench_csv is None:
    _out_dir = os.path.join(_BASE_DIR, 'data_output')
    _cands = sorted(
        os.path.join(_out_dir, _f)
        for _f in (os.listdir(_out_dir) if os.path.isdir(_out_dir) else [])
        if _f.startswith('energy_benchmarking_')
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

#   Reference values of Figures 7 and 8.
#     SURVEY : medians of the independent national hospital survey, with the
#              number of institutions behind each one
#     EXTERNAL: UK CIBSE TM46 / Canada ENERGY STAR / U.S. ENERGY STAR national
#              median converted from kBtu/ft2
SURVEY = {'GH': (329.3, 42), 'H': (271.8, 23), 'CH': (232.1, 17)}
EXTERNAL = {'UK': 510.0, 'Canada': 611.1, 'USA': 739.1}
TITLE_PAD = 20      # gap between a panel title and the axes
LABEL_PAD = 12      # gap between an axis label and its ticks


def eui(d, year):
    """Annual site energy use intensity (kWh/m2 per year). NaN if gfa is 0."""
    return (d[f'site_sum_{year}'] / d['gfa']).replace([np.inf, -np.inf], np.nan)


def save_fig(fname):
    """Write the current figure."""
    out = os.path.join(figure_dir, fname)
    plt.savefig(out, dpi=300, bbox_inches='tight')
    print(f'[saved] {out}')
    plt.close()




# =============================================================================
# Figure 6. Interannual consistency (three panels)
# =============================================================================
PAIRS = [
    ('(a) 2018–2019', 2018, 2019),
    ('(b) 2019–2020', 2019, 2020),
    ('(c) 2020–2021', 2020, 2021),
]

_AX_MAX = max(eui(df, y).max() for y in YEARS)
AX_MAX = float(np.ceil(_AX_MAX / 100.0) * 100)

_, axes = plt.subplots(1, 3, figsize=(18, 6))


for ax, (title_txt, yx, yy) in zip(axes, PAIRS):
    x, y = eui(df, yx), eui(df, yy)
    m = x.notna() & y.notna()
    x, y = x[m], y[m]

    ax.scatter(x, y, alpha=0.55, label=f'Data (n = {len(x):,})', color='teal', s=42)

    slope, intercept, r_value, _, _ = linregress(x, y)
    xline = np.linspace(x.min(), x.max(), 200)
    ax.plot(xline, slope * xline + intercept, color='black', linestyle='--',
            linewidth=2, label=f'Trend line ($R^2$={r_value ** 2:.3f})')


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

    # Reference lines, labeled from the top down.
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
    values drawn in matching colors.

    Each ref_dict entry is either a scalar or a dict with the keys value,
    color, linestyle, linewidth and text.
    """
    sns.set_style('whitegrid')
    ref_dict = ref_dict or {}

    d_plot = d[~d[group_col].isin(exclude_groups)].copy()

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
plot_density_by_hos_type_with_ref(
    df, year=2018,
    group_col='hos_ty_eng',
    exclude_groups=('KH', 'TH'),
    ref_dict={
        f'Survey {t} (n = {n})': {'value': v, 'color': _F7_LINE_COLOR[t]}
        for t, (v, n) in SURVEY.items()
    },
    alpha=0.18, linewidth=1.0, bw_adjust=1.1,
    xlim=(0, 1000),
    save_path='fig7_survey_comparison.png',
)


# -- Figure 8. General and tertiary general hospitals only --------------------
plot_density_with_ref(
    df, years=YEARS,
    group_col='hos_ty_eng',
    exclude_groups=['H', 'KH', 'CH'],       # leaves GH + TH
    ref_dict=EXTERNAL,
    n_fill=0, linewidth=1.0, bw_adjust=1.1,
    xlim=(0, 1000),
    save_path='fig8_external_benchmarks.png',
)


print('\n[eda_validation] done')
