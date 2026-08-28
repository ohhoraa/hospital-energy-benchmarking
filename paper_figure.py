# -*- coding: utf-8 -*-
"""
paper_figure. The two figures that document the quality-control steps.

Inputs (from data_prepared/, written by S3)
  '{date} final_before_preprocessing {hira}_{yb}_{ya}.xlsx'
  '{date} final_after_outlier {hira}_all.xlsx'
Output
  figures/fig4_filtering_energy_vs_gfa.png
  figures/fig5_manual_check_bed_eui_by_type.png

Figure 4 - annual energy against gross floor area, for the population that
  remains after the two-stage integration. The two baseline conditions
  (principal use code, single-institution configuration) are applied here, so
  the script starts from the before_preprocessing file and reproduces the same
  population the filtering table starts from.
    (a) full range, with the institutions above the bed upper bound labelled
    (b) enlarged lower-left region, with the institutions at or below the annual
        energy lower bound highlighted, the four immediately above it drawn as
        open circles, and dashed constant-EUI reference lines

Figure 5 - bed-based energy use intensity against gross floor area, by
  institution type, used for the manual distribution check. The base population
  is the final dataset; the institutions the manual inspection removed as
  distribution errors (list_ty == 'dist_err' in manual_exclusions.csv) are added
  back so that they can be marked (A1, A2, ... - A for atypical), taken from the
  before_preprocessing file and put on the same corrected floor area. The
  matching errors (mat_err) are not marked: they were found on the matching, not
  on this view.
"""

import os

import pandas as pd
import matplotlib as mpl
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.patches import Circle
from matplotlib.offsetbox import AnnotationBbox, DrawingArea
from matplotlib.ticker import MaxNLocator, ScalarFormatter

from common import (MAIN_PURPS_CDS, YKIHO, SCOPE_CFG, final_filename,
                   manual_exclusion_types, totarea_adj)

# Type sizes. The figures are reduced heavily when placed in a two-column
# layout, so everything is set well above the matplotlib defaults. The
# multipliers reproduce the sizes the analysis figures were settled on
# (24 / 22 / 22 / 20 / 20 / 11); change BASE to rescale all of them at once.
BASE = 11
FS_TITLE = BASE * 2.2             # 24.2
FS_LEGEND = BASE * 2.0            # 22
FS_LABEL = BASE * 2.0             # 22
FS_TICK = BASE * 1.8              # 19.8
FS_ANNOT = BASE * 1.8             # 19.8
FS_INSET_TICK = BASE * 1.0        # 11, the inset carries a full tick scale
FS_SUBTITLE = FS_LABEL * 1.05     # panel titles of Figure 5
TITLE_PAD = 20                    # gap between the panel title and the axes
LABEL_PAD = 12                    # gap between an axis label and its ticks

mpl.rcParams['axes.linewidth'] = 0.8
mpl.rcParams['xtick.major.width'] = 0.6
mpl.rcParams['ytick.major.width'] = 0.6
mpl.rcParams['xtick.labelsize'] = FS_TICK
mpl.rcParams['ytick.labelsize'] = FS_TICK
mpl.rcParams['font.family'] = 'sans-serif'
mpl.rcParams['font.sans-serif'] = ['Arial', 'Helvetica', 'DejaVu Sans']
mpl.rcParams['axes.unicode_minus'] = False
mpl.rcParams['axes.grid'] = False


# =============================================================================
# 0. Settings (injectable from run_all_merge.py)
# =============================================================================
_BASE_DIR = os.path.dirname(os.path.abspath(__file__))

if 'data_dir' not in globals():
    data_dir = os.path.join(_BASE_DIR, 'data_prepared')
if 'figure_dir' not in globals():
    figure_dir = os.path.join(_BASE_DIR, 'figures')
if 'exclusion_csv' not in globals():
    exclusion_csv = os.path.join(_BASE_DIR, 'manual_exclusions.csv')
if 'date' not in globals():
    date = 260820
if 'hira' not in globals():
    hira = 202003
# The sub-period and the year the figures are drawn for, set by
# FIG_PAIR / FIG_YEAR in run_all_merge.py.
if 'fig_pair' not in globals():
    fig_pair = (2018, 2019)
if 'fig_year' not in globals():
    fig_year = fig_pair[1]            # 2019

# Filter bounds, kept identical to S2_clean.py.
ENERGY_MIN = 20_000          # annual site energy lower bound (kWh)
ENERGY_NEAR = 24_000         # upper edge of the "just above the bound" band
BED_MAX = 1_000              # bed upper bound
GFA_PLOT_MAX = 1e6           # institutions larger than this are not plottable

# Figure 4 geometry.
X_MAX, Y_MAX = 15_000, 0.5e6     # (b) limits
YI_MAX = 3e4                     # inset y limit
EUI_LINES_MAIN = (50, 10)        # constant-EUI reference lines on (b)
EUI_LINES_INSET = (5, 1)         # and on the inset
INSET_BOX = [0.365, 0.505, 0.62, 0.48]

# Marks. One base colour plus two highlights; no colour map, so that the
# highlights are the only thing colour carries.
C_OTHER, C_BED, C_LOW = '#9db4c0', '#d62728', '#ff7f0e'
C_REF, C_REF_TXT = '0.45', '0.35'        # EUI reference line and its label
REF_DASH = (0, (6, 4))
S_BASE, S_HL, S_BAND = 48, 58, 70        # marker sizes on (a)/(b)
SPINE_W = 0.9

# Figure 5. Set2, the first three colours, one per bed-count bin.
BED_BINS = [0, 100, 500, 1000]
BED_LABELS = ['30–100', '100–500', '500–1000']
BED_COLORS = {'30–100': '#66c2a5', '100–500': '#fc8d62', '500–1000': '#8da0cb'}
C_GREY = 'lightgray'                     # the whole population behind a panel
FIG5_SPINE = '0.5'                       # panel frame, and the legend box
MARK_R = 12                              # callout circle radius, in points
MARK_OFFSET_FRAC = 0.08                  # callout label offset, share of y span
# Callout prefix. 'A' for atypical, the word the manuscript uses for these
# institutions. Not 'PO' (potential outlier): the removal is a decision already
# taken, not a candidate, and these records are not erroneous - they are real
# institutions removed for atypicality, which is the opposite of what calling
# them outliers would say.
MARK_PREFIX = 'A'

os.makedirs(figure_dir, exist_ok=True)


class FixedExpFormatter(ScalarFormatter):
    """Axis formatter with the exponent pinned to a fixed power (e.g. always 1e4).

    Matplotlib picks the exponent from the axis maximum. In Figure 4 that makes
    the (b) panel (upper limit 5e5) read 1e5 while the inset inside it (upper
    limit 2.4e4) reads 1e4, so the two cannot be compared by eye. Pinning both
    to 1e4 puts them on the same units.
    """

    def __init__(self, exp):
        super().__init__(useMathText=False)   # plain '1e4', as on the inset
        self._fixed_exp = exp
        self.set_scientific(True)
        self.set_powerlimits((0, 0))          # always use the exponent form

    def _set_order_of_magnitude(self):
        self.orderOfMagnitude = self._fixed_exp


def set_fixed_exp(ax, exp, fontsize):
    """Pin the exponent of the y-axis label."""
    target = ax.yaxis
    target.set_major_formatter(FixedExpFormatter(exp))
    target.get_offset_text().set_fontsize(fontsize)


def draw_eui_refs(ax, euis, xmax, ymax, fontsize, linewidth=1.0):
    """Constant-EUI reference lines through the origin, with inline labels.

    These are not filter thresholds. They are the scale the reader uses to see
    how low a point is, so they are drawn as grey dashes only. The label goes on
    whichever edge the line leaves the axes through: the right edge if it gets
    there first, otherwise the top.
    """
    for e in euis:
        ax.plot([0, xmax], [0, e * xmax], color=C_REF, linestyle=REF_DASH,
                linewidth=linewidth, zorder=2)
        if e * xmax <= ymax:                      # leaves through the right edge
            tx, ty, va, ha = xmax * 0.98, e * xmax, 'bottom', 'right'
        else:                                     # leaves through the top edge
            tx, ty, va, ha = ymax / e, ymax * 0.985, 'top', 'left'
        ax.text(tx, ty, f'{e:g} kWh/m$^2$', fontsize=fontsize, color=C_REF_TXT,
                va=va, ha=ha, zorder=7)


def save_fig(fname):
    """Write the current figure. Whether this step runs at all is
    decided by RUN_* in run_all_merge.py, so there is no per-figure
    switch here."""
    out = os.path.join(figure_dir, fname)
    plt.savefig(out, dpi=300, bbox_inches='tight')
    print(f'[saved] {out}')
    plt.close()


# =============================================================================
# 1. Figure 4 - annual energy against gross floor area
# =============================================================================
_yb, _ya = fig_pair
_fp = os.path.join(data_dir,
                   final_filename('before_preprocessing', date, hira,
                                  f'{_yb}_{_ya}'))
if not os.path.exists(_fp):
    raise FileNotFoundError(
        f'Input for Figure 4 not found: {_fp}\n'
        f'  -> run S3_combine.py first (it writes the final_* files).'
    )

d4 = pd.read_excel(_fp)
print(f'[fig4] input {os.path.basename(_fp)}: {len(d4):,} rows')

# Baseline conditions: the same two the filtering table treats as the starting
# population rather than as filtering steps.
d4 = d4[d4['main_purps_cd'].astype(str).isin(MAIN_PURPS_CDS)]
_single = {SCOPE_CFG[s]['model_ty'] for s in SCOPE_CFG}
d4 = d4[d4['model_ty'].isin(_single)]
n_integrated = d4[YKIHO].nunique()
print(f'[fig4] after the two baseline conditions: {n_integrated:,} institutions')

# Gross floor area. totarea_adj is created during screening, so at this stage
# the register value is used.
d4 = d4.assign(gfa=d4['totarea'], energy=d4[f'site_sum_{fig_year}'])

# Institutions that cannot be placed on the axes: a floor area of zero, or one
# so large that it compresses everything else. Both are removed by the
# subsequent filtering or screening in any case.
_bad = (d4['gfa'].isna() | (d4['gfa'] <= 0) | (d4['gfa'] > GFA_PLOT_MAX)
        | d4['energy'].isna())
n_zero = int((d4['gfa'].fillna(0) <= 0).sum())
n_huge = int((d4['gfa'] > GFA_PLOT_MAX).sum())
d4p = d4[~_bad]
n_plot = len(d4p)
print(f'[fig4] not plotted: {int(_bad.sum())} '
      f'(zero floor area {n_zero}, above {GFA_PLOT_MAX:.0e} m2 {n_huge})')
print(f'[fig4] plotted: {n_plot:,}')

hl_bed = d4p[d4p['bed_cnt'] > BED_MAX]
hl_en = d4p[d4p['energy'] <= ENERGY_MIN]
hl_band = d4p[d4p['energy'].between(ENERGY_MIN, ENERGY_NEAR, inclusive='right')]
print(f'[fig4] bed_cnt > {BED_MAX:,}: {len(hl_bed)} / '
      f'site_sum_{fig_year} <= {ENERGY_MIN:,}: {len(hl_en)}')

_x, _y = d4p['gfa'], d4p['energy']


def _style4(ax):
    """Axis furniture shared by (a) and (b)."""
    ax.set_box_aspect(1)                    # square plotting box
    ax.grid(False)
    for sp in ax.spines.values():
        sp.set_visible(True)
        sp.set_linewidth(SPINE_W)
        sp.set_color('black')
    ax.set_xlabel('Gross floor area (m$^2$)', fontsize=FS_LABEL)
    ax.set_ylabel(f'{fig_year} Site energy (kWh/yr)', fontsize=FS_LABEL,
                  labelpad=LABEL_PAD)
    # Large type makes the default tick count collide, so it is reduced.
    ax.xaxis.set_major_locator(MaxNLocator(nbins=5))
    ax.yaxis.set_major_locator(MaxNLocator(nbins=5))
    ax.tick_params(labelsize=FS_TICK)
    ax.xaxis.get_offset_text().set_fontsize(FS_TICK)
    ax.yaxis.get_offset_text().set_fontsize(FS_TICK)


def _base4(ax, s=S_BASE):
    ax.scatter(_x, _y, s=s, color=C_OTHER, alpha=0.6,
               edgecolor='white', linewidth=0.3, zorder=3)


fig, axes = plt.subplots(1, 2, figsize=(16, 8))

# -- (a) full range ----------------------------------------------------------
ax = axes[0]
_base4(ax)
ax.scatter(hl_bed['gfa'], hl_bed['energy'], s=S_HL, color=C_BED, zorder=6)
x_hi, y_hi = float(_x.max()) * 1.07, float(_y.max()) * 1.07
ax.set_xlim(0, x_hi)
ax.set_ylim(0, y_hi)

# Bed-count labels, placed top-down and pushed up whenever two would overlap.
_min_gap = 0.035 * y_hi
_placed = []
for _, r in hl_bed.sort_values('energy', ascending=False).iterrows():
    y_lab = float(r['energy'])
    while any(abs(y_lab - p) < _min_gap for p in _placed):
        y_lab += _min_gap
    _placed.append(y_lab)
    ax.annotate(f'{int(r["bed_cnt"]):,}', xy=(r['gfa'], r['energy']),
                xytext=(r['gfa'] + 0.022 * x_hi, y_lab),
                fontsize=FS_ANNOT, color=C_BED, va='center', zorder=7)

ax.set_title(f'(a) Full range (n = {n_plot:,})', loc='center',
             fontsize=FS_TITLE, y=1.0, pad=TITLE_PAD)
_style4(ax)

# -- (b) enlarged lower-left region -----------------------------------------
ax = axes[1]
_base4(ax)
draw_eui_refs(ax, EUI_LINES_MAIN, X_MAX, Y_MAX, FS_ANNOT)
ax.scatter(hl_en['gfa'], hl_en['energy'], s=S_HL, color=C_LOW, zorder=6)
ax.scatter(hl_band['gfa'], hl_band['energy'], s=S_BAND, facecolor='none',
           edgecolor=C_LOW, linewidth=2.0, zorder=6)
ax.axhline(ENERGY_MIN, color=C_LOW, linestyle='--', linewidth=1.2, zorder=5)
ax.set_xlim(0, X_MAX)
ax.set_ylim(0, Y_MAX)
ax.set_title('(b) Enlarged — lower-left region of (a)', loc='center',
             fontsize=FS_TITLE, y=1.0, pad=TITLE_PAD)
_style4(ax)

# Both y axes of (b) are pinned to 1e4. Left to itself the outer panel would
# read 1e5 against the inset's 1e4, and the two could not be compared by eye.
set_fixed_exp(ax, exp=4, fontsize=FS_TICK)

# inset: upper right of (b), enlarging the lower tail where the two lowest
# reference lines separate. It is opaque and above the points it covers.
axi = ax.inset_axes(INSET_BOX, facecolor='white')
axi.set_zorder(8)
axi.patch.set_alpha(1.0)
axi.scatter(_x, _y, s=S_BASE / 2, color=C_OTHER, alpha=0.6,
            edgecolor='white', linewidth=0.2)
# The inset's reference-line labels are set at the same size as the one on (b),
# not at the inset's own tick size: they carry the same information, so they
# should not read as a smaller class of label.
draw_eui_refs(axi, EUI_LINES_INSET, X_MAX, YI_MAX, FS_ANNOT, linewidth=0.8)
axi.scatter(hl_en['gfa'], hl_en['energy'], s=26, color=C_LOW, zorder=6)
axi.scatter(hl_band['gfa'], hl_band['energy'], s=34, facecolor='none',
            edgecolor=C_LOW, linewidth=1.4, zorder=6)
axi.axhline(ENERGY_MIN, color=C_LOW, linestyle='--', linewidth=1.2)
axi.set_xlim(0, X_MAX)
axi.set_ylim(0, YI_MAX)
axi.xaxis.set_major_locator(MaxNLocator(nbins=4))
axi.yaxis.set_major_locator(MaxNLocator(nbins=4))
axi.tick_params(labelsize=FS_INSET_TICK)
axi.xaxis.get_offset_text().set_fontsize(FS_INSET_TICK)
set_fixed_exp(axi, exp=4, fontsize=FS_INSET_TICK)
# The label sits in the top-right corner, the only part of the inset that no
# reference line or point runs through.
axi.text(0.98, ENERGY_MIN / YI_MAX + 0.02, f'{ENERGY_MIN:,} kWh',
         transform=axi.transAxes, fontsize=FS_ANNOT, ha='right', color=C_LOW)

handles = [
    Line2D([], [], marker='o', linestyle='none', markersize=13,
           markerfacecolor=C_OTHER, markeredgecolor='white', alpha=0.8,
           label=f'Other institutions (n = {n_plot:,})'),
    Line2D([], [], marker='o', linestyle='none', markersize=15, color=C_BED,
           label=f'bed_cnt > {BED_MAX:,} (n = {len(hl_bed):,})'),
    Line2D([], [], marker='o', linestyle='none', markersize=15, color=C_LOW,
           label=f'≤ {ENERGY_MIN:,} kWh (n = {len(hl_en):,})'),
    Line2D([], [], marker='o', linestyle='none', markersize=15,
           markerfacecolor='none', markeredgecolor=C_LOW, markeredgewidth=2,
           label=f'{ENERGY_MIN:,}–{ENERGY_NEAR:,} kWh (n = {len(hl_band):,})'),
    Line2D([], [], linestyle=REF_DASH, color=C_REF,
           label='EUI reference lines'),
]
# Explicit margins rather than tight_layout: tight_layout sizes each column to
# its own tick labels, and with a square box aspect the two panels then come out
# at different heights, which puts their titles at different heights. Equal
# columns by construction keeps the two titles on one line.
fig.subplots_adjust(left=0.09, right=0.97, top=0.90, bottom=0.12, wspace=0.30)
fig.legend(handles=handles, loc='center left', bbox_to_anchor=(0.995, 0.5),
           frameon=False, fontsize=FS_LEGEND)
save_fig('fig4_filtering_energy_vs_gfa.png')


# =============================================================================
# 2. Figure 5 - bed-based EUI against gross floor area, by institution type
# =============================================================================
_fp_fin = os.path.join(data_dir, final_filename('after_outlier', date, hira, 'all'))
if not os.path.exists(_fp_fin):
    raise FileNotFoundError(
        f'Input for Figure 5 not found: {_fp_fin}\n'
        f'  -> run S3_combine.py first.'
    )

d5 = pd.read_excel(_fp_fin)
print(f'\n[fig5] input {os.path.basename(_fp_fin)}: '
      f'{d5[YKIHO].nunique():,} institutions')

# The manually excluded institutions are no longer in the final file, so they
# are read back from before_preprocessing and appended for marking only.
#   dist_err only: those are the points this figure is about - the matching is
#   sound, so the plotted position is itself the finding. A mat_err institution
#   was found on the matching, so its coordinates here mean nothing.
_po = manual_exclusion_types(exclusion_csv)['dist_err']
_fp_pre = os.path.join(data_dir,
                       final_filename('before_preprocessing', date, hira, 'all'))
po_rows = pd.DataFrame()
if _po and os.path.exists(_fp_pre):
    _pre = pd.read_excel(_fp_pre)
    po_rows = _pre[_pre[YKIHO].astype(str).isin(_po)].copy()
    if len(po_rows):
        po_rows['totarea_adj'] = totarea_adj(po_rows)
print(f'[fig5] manually excluded institutions added back for marking: '
      f'{po_rows[YKIHO].nunique() if len(po_rows) else 0}')

keep = ['ykiho', 'totarea_adj', 'bed_cnt', 'hos_ty_eng', f'site_sum_{fig_year}']
d5 = pd.concat([d5[keep], po_rows[keep]], ignore_index=True) if len(po_rows) \
    else d5[keep]
d5 = d5.drop_duplicates(subset=[YKIHO])

d5 = d5[(d5['bed_cnt'] > 0) & (d5['totarea_adj'] > 0)]
d5['bed_eui'] = d5[f'site_sum_{fig_year}'] / d5['bed_cnt']

# Tertiary general hospitals are shown with the general hospitals: there are
# too few of them to read a distribution from on their own.
d5['panel_ty'] = d5['hos_ty_eng'].replace({'TH': 'GH'})

# Panel order is fixed, smallest typical scale first: H -> KH -> CH -> GH(TH).
# Fixing it keeps the panels comparable between runs and between figures.
PANEL_ORDER = ['H', 'KH', 'CH', 'GH']
PANEL_LABEL = {'GH': 'GH(TH)'}

d5['bed_bin'] = pd.cut(d5['bed_cnt'], bins=BED_BINS, labels=BED_LABELS,
                       include_lowest=True)

# The PO label is offset below its circle by a share of the y span, so the gap
# stays the same wherever the point sits.
_y_span = float(d5['bed_eui'].max() - d5['bed_eui'].min())
_y_lo = float(d5['bed_eui'].min())

# PO numbering follows the order of the exclusion list, so the labels stay
# stable between runs.
MARK_ORDER = {y: i + 1 for i, y in enumerate(_po)}

panels = [p for p in PANEL_ORDER if (d5['panel_ty'] == p).any()]
fig, axes = plt.subplots(1, len(panels), figsize=(4.8 * len(panels), 5.4),
                         sharex=True, sharey=True, squeeze=False)

for ax, ty in zip(axes[0], panels):
    ax.set_box_aspect(1)          # square plotting box
    ax.grid(False)
    for sp in ax.spines.values():
        sp.set_linewidth(SPINE_W)
        sp.set_color(FIG5_SPINE)

    sub = d5[d5['panel_ty'] == ty]
    # The whole population in grey behind the panel's own type, so that each
    # panel is read against the same background.
    ax.scatter(d5['totarea_adj'], d5['bed_eui'], color=C_GREY, alpha=0.3, s=18)
    for lab in BED_LABELS:
        s = sub[sub['bed_bin'] == lab]
        if len(s):
            ax.scatter(s['totarea_adj'], s['bed_eui'], s=45,
                       color=BED_COLORS[lab], alpha=0.8, edgecolor='none')

    # Dashed circle plus number on the manually excluded institutions.
    marks = sub[sub[YKIHO].astype(str).isin(MARK_ORDER)]
    for _, r in marks.iterrows():
        da = DrawingArea(2 * MARK_R, 2 * MARK_R, 0, 0)
        da.add_artist(Circle((MARK_R, MARK_R), radius=MARK_R, fill=False,
                             edgecolor='red', linewidth=2, linestyle='--'))
        ax.add_artist(AnnotationBbox(da, (r['totarea_adj'], r['bed_eui']),
                                     xycoords='data', frameon=False))
        # Below the circle, unless that would put the label under the axes -
        # for a point near the bottom it goes above instead.
        _off = MARK_OFFSET_FRAC * _y_span
        _below = r['bed_eui'] - _off >= _y_lo + 0.02 * _y_span
        ax.text(r['totarea_adj'], r['bed_eui'] + (-_off if _below else _off),
                f'{MARK_PREFIX}{MARK_ORDER[str(r[YKIHO])]}', fontsize=FS_ANNOT, color='red',
                weight='bold', ha='center',
                va='top' if _below else 'bottom', zorder=6)

    ax.set_title(f'{PANEL_LABEL.get(ty, ty)} (n = {len(sub):,})',
                 fontsize=FS_SUBTITLE, pad=TITLE_PAD)
    ax.set_xlabel('GFA (m$^2$)', fontsize=FS_LABEL)
    # Large type makes the default tick count collide, as on Figure 4.
    ax.xaxis.set_major_locator(MaxNLocator(nbins=4))
    ax.yaxis.set_major_locator(MaxNLocator(nbins=5))
    ax.tick_params(labelsize=FS_TICK)

axes[0][0].set_ylabel(f'{fig_year} Site-bed EUI (kWh/bed·yr)', fontsize=FS_LABEL,
                      labelpad=LABEL_PAD)

# One row of legend entries above the panel titles. It is anchored beyond the
# figure edge and picked up by bbox_inches='tight' on saving, so the panels keep
# their square shape.
handles = [Line2D([], [], marker='o', linestyle='none', markersize=13,
                  color=BED_COLORS[l], label=f'{l} beds') for l in BED_LABELS]
plt.tight_layout()
fig.legend(handles=handles, loc='lower center', bbox_to_anchor=(0.5, 1.02),
           ncol=len(handles), frameon=False, fontsize=FS_LABEL,
           handletextpad=0.4, columnspacing=1.6)
save_fig('fig5_manual_check_bed_eui_by_type.png')

print('\n[paper_figure] done')
