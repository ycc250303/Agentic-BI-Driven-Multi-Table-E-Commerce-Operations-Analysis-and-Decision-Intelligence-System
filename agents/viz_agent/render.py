"""根据 VizPlan 与 DataFrame 渲染 PNG（matplotlib / seaborn / wordcloud）。"""

from __future__ import annotations

import os
import platform
import warnings
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.font_manager as fm
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np
import pandas as pd
import seaborn as sns

try:
    from agents.viz_agent.render_context import RenderExtras
    from agents.viz_agent.schema import VizPlan
except ModuleNotFoundError:
    from render_context import RenderExtras
    from schema import VizPlan

warnings.filterwarnings("ignore", category=UserWarning, module="matplotlib")

_PALETTE = {
    "primary": "#2563EB",
    "forecast": "#F97316",
    "positive": "#059669",
    "negative": "#DC2626",
    "grid": "#E5E7EB",
}
_DELIVERY_COLORS = {"准时": "#059669", "延迟": "#DC2626", "其他": "#6B7280"}

# 可通过 AGENTIC_BI_VIZ_FONT 覆盖；否则按当前系统自动探测
_WINDOWS_FONT_FILES: tuple[str, ...] = (
    r"C:\Windows\Fonts\msyh.ttc",
    r"C:\Windows\Fonts\msyhbd.ttc",
    r"C:\Windows\Fonts\simhei.ttf",
    r"C:\Windows\Fonts\simsun.ttc",
)

# macOS：优先 FreeType/matplotlib 可直接读取的字体（避免新版 PingFangUI 私有格式）
_MAC_FONT_FILES: tuple[str, ...] = (
    "/System/Library/Fonts/Hiragino Sans GB.ttc",
    "/System/Library/Fonts/STHeiti Medium.ttc",
    "/System/Library/Fonts/STHeiti Light.ttc",
    "/System/Library/Fonts/Supplemental/Songti.ttc",
    "/System/Library/Fonts/Supplemental/STHeiti Light.ttc",
    "/System/Library/Fonts/Supplemental/STHeiti Medium.ttc",
    "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
    "/System/Library/Fonts/PingFang.ttc",
    "/System/Library/Fonts/LanguageSupport/PingFang.ttc",
    "/Library/Fonts/Arial Unicode.ttf",
    "/Library/Fonts/Microsoft/Microsoft YaHei.ttf",
)

_LINUX_FONT_FILES: tuple[str, ...] = (
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/google-noto-cjk/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
)

_MAC_FONT_NAME_FALLBACKS: tuple[str, ...] = (
    "PingFang SC",
    "Hiragino Sans GB",
    "STHeiti",
    "Songti SC",
    "Heiti SC",
    "Arial Unicode MS",
    "Microsoft YaHei",
    "SimHei",
    "Noto Sans CJK SC",
)

_WINDOWS_FONT_NAME_FALLBACKS: tuple[str, ...] = (
    "Microsoft YaHei",
    "SimHei",
    "SimSun",
    "Noto Sans CJK SC",
    "Arial Unicode MS",
)

_LINUX_FONT_NAME_FALLBACKS: tuple[str, ...] = (
    "Noto Sans CJK SC",
    "Noto Sans CJK JP",
    "WenQuanYi Micro Hei",
    "WenQuanYi Zen Hei",
    "Arial Unicode MS",
    "Microsoft YaHei",
    "SimHei",
)

_MAC_FONT_SCAN_DIRS: tuple[str, ...] = (
    "/System/Library/Fonts",
    "/System/Library/Fonts/Supplemental",
    "/System/Library/Fonts/LanguageSupport",
    "/Library/Fonts",
)

_MAC_FONT_SCAN_KEYWORDS: tuple[str, ...] = (
    "Hiragino Sans GB",
    "STHeiti",
    "Songti",
    "PingFang",
    "Arial Unicode",
)

_resolved_cjk_font: tuple[str | None, str | None] | None = None


def _platform_font_files() -> tuple[str, ...]:
    system = platform.system()
    if system == "Darwin":
        return _MAC_FONT_FILES
    if system == "Windows":
        return _WINDOWS_FONT_FILES
    return _LINUX_FONT_FILES


def _platform_font_name_fallbacks() -> tuple[str, ...]:
    system = platform.system()
    if system == "Darwin":
        return _MAC_FONT_NAME_FALLBACKS
    if system == "Windows":
        return _WINDOWS_FONT_NAME_FALLBACKS
    return _LINUX_FONT_NAME_FALLBACKS


def _scan_mac_font_files() -> list[Path]:
    found: list[Path] = []
    seen: set[str] = set()
    for directory in _MAC_FONT_SCAN_DIRS:
        root = Path(directory)
        if not root.is_dir():
            continue
        for path in root.iterdir():
            if not path.is_file() or path.suffix.lower() not in {".ttf", ".ttc", ".otf"}:
                continue
            if not any(keyword in path.name for keyword in _MAC_FONT_SCAN_KEYWORDS):
                continue
            resolved = str(path.resolve())
            if resolved in seen:
                continue
            seen.add(resolved)
            found.append(path)
    return found


def _register_font_file(path: Path) -> str | None:
    try:
        fm.fontManager.addfont(str(path))
    except (OSError, ValueError):
        pass
    try:
        return fm.FontProperties(fname=str(path)).get_name()
    except (OSError, ValueError):
        return None


def _registered_fonts() -> dict[str, str]:
    return {f.name: f.fname for f in fm.fontManager.ttflist}


def _match_registered_font(
    registered: dict[str, str],
    target: str,
) -> tuple[str, str] | None:
    if target in registered:
        return target, registered[target]
    target_key = target.lower().replace(" ", "")
    for name, path in registered.items():
        name_key = name.lower().replace(" ", "")
        if target_key in name_key or name_key in target_key:
            return name, path
    return None


def _resolve_cjk_font() -> tuple[str | None, str | None]:
    """解析可用于 matplotlib / wordcloud 的中文字体，返回 (font_name, font_path)。"""
    global _resolved_cjk_font
    if _resolved_cjk_font is not None:
        return _resolved_cjk_font

    env_path = os.environ.get("AGENTIC_BI_VIZ_FONT", "").strip()
    if env_path:
        custom = Path(env_path)
        if custom.is_file():
            name = _register_font_file(custom)
            if name:
                _resolved_cjk_font = (name, str(custom.resolve()))
                return _resolved_cjk_font

    # macOS 上系统字体常已由 matplotlib 索引，优先按名称匹配（含词云 font_path）
    registered = _registered_fonts()
    for name in _platform_font_name_fallbacks():
        matched = _match_registered_font(registered, name)
        if matched:
            _resolved_cjk_font = matched
            return _resolved_cjk_font

    font_paths: list[Path] = [Path(p) for p in _platform_font_files()]
    if platform.system() == "Darwin":
        font_paths.extend(_scan_mac_font_files())

    for path in font_paths:
        if not path.is_file():
            continue
        name = _register_font_file(path)
        if name:
            _resolved_cjk_font = (name, str(path.resolve()))
            return _resolved_cjk_font

    _resolved_cjk_font = (None, None)
    return _resolved_cjk_font


def _configure_matplotlib_zh() -> None:
    plt.rcParams["axes.unicode_minus"] = False
    font_name, _font_path = _resolve_cjk_font()
    fallbacks = list(_platform_font_name_fallbacks()) + ["DejaVu Sans"]
    if font_name:
        plt.rcParams["font.family"] = font_name
        plt.rcParams["font.sans-serif"] = [font_name] + [
            n for n in fallbacks if n != font_name
        ]
    else:
        plt.rcParams["font.sans-serif"] = list(fallbacks)
        system = platform.system()
        hint = (
            "macOS 可在「字体册」下载苹方/宋体，或设置 AGENTIC_BI_VIZ_FONT；"
            if system == "Darwin"
            else "请安装 Noto Sans CJK / 微软雅黑，或设置 AGENTIC_BI_VIZ_FONT；"
        )
        warnings.warn(
            "未找到可用的中文字体，图表中文可能显示为方框；"
            f"{hint}指向 .ttf/.ttc 文件。",
            UserWarning,
            stacklevel=3,
        )


def _wordcloud_font_path() -> str | None:
    _font_name, font_path = _resolve_cjk_font()
    return font_path


def _apply_style() -> None:
    sns.set_theme(style="whitegrid", context="notebook")
    _configure_matplotlib_zh()
    plt.rcParams["figure.facecolor"] = "white"
    plt.rcParams["axes.facecolor"] = "#FAFAFA"
    plt.rcParams["grid.color"] = _PALETTE["grid"]
    plt.rcParams["grid.alpha"] = 0.6


def _format_axis_currency(ax: plt.Axes, axis: str = "x") -> None:
    tick = mticker.FuncFormatter(lambda x, _pos: f"{x/1e6:.1f}M" if x >= 1e6 else f"{x/1e3:.0f}K")
    if axis == "x":
        ax.xaxis.set_major_formatter(tick)
    else:
        ax.yaxis.set_major_formatter(tick)


def _human_axis_label(column: str) -> str:
    """将数据列名转为图表轴中文标签。"""
    cl = (column or "").lower()
    mapping = {
        "category": "产品品类",
        "product_category_english": "产品品类",
        "topic": "差评主题",
        "payment_type": "支付方式",
        "payment_installments": "分期数",
        "month": "月份",
        "year_month": "年月",
        "customer_state": "州",
        "state": "州",
    }
    if column in mapping:
        return mapping[column]
    if "category" in cl:
        return "产品品类"
    if "topic" in cl or "theme" in cl or "reason" in cl:
        return "差评主题"
    if "payment" in cl and "install" in cl:
        return "分期数"
    if "payment" in cl:
        return "支付方式"
    if "month" in cl or "date" in cl:
        return "时间"
    return column


def _human_value_label(column: str) -> str:
    cl = (column or "").lower()
    if cl in ("count", "cnt", "bad_review_count"):
        return "提及次数"
    if "rate" in cl:
        return "占比"
    if "gmv" in cl or "sales" in cl:
        return "销售额"
    if "installment" in cl:
        return "分期数"
    return column or "数值"


def _style_title(ax: plt.Axes, title: str, subtitle: str = "") -> None:
    ax.set_title(title, fontsize=14, fontweight="bold", pad=12)
    if subtitle:
        ax.text(
            0.01,
            1.02,
            subtitle,
            transform=ax.transAxes,
            fontsize=10,
            color="#6B7280",
        )


def _render_wordcloud_compare(
    extras: RenderExtras,
    dest_path: Path,
    title: str,
) -> str:
    from wordcloud import WordCloud

    data = extras.wordcloud_compare or {}
    pos = data.get("positive") or {}
    neg = data.get("negative") or {}
    if not pos and not neg:
        raise ValueError("对比词云缺少 positive/negative 词频")

    font = _wordcloud_font_path()
    fig, axes = plt.subplots(1, 2, figsize=(14, 6.5))
    panels = [
        ("好评 Top 词", pos, _PALETTE["positive"]),
        ("差评 Top 词", neg, _PALETTE["negative"]),
    ]
    for ax, (panel_title, freqs, color) in zip(axes, panels):
        if not freqs:
            ax.text(0.5, 0.5, "暂无数据", ha="center", va="center")
            ax.axis("off")
            ax.set_title(panel_title, fontsize=12, fontweight="bold")
            continue
        wc = WordCloud(
            width=900,
            height=520,
            background_color="white",
            font_path=font,
            collocations=False,
            colormap=None,
            prefer_horizontal=0.9,
            color_func=lambda *args, c=color, **kwargs: c,
        ).generate_from_frequencies(freqs)
        ax.imshow(wc, interpolation="bilinear")
        ax.axis("off")
        ax.set_title(panel_title, fontsize=12, fontweight="bold", color=color)
    fig.suptitle(title, fontsize=15, fontweight="bold", y=1.02)
    if extras.subtitle:
        fig.text(0.5, 0.01, extras.subtitle, ha="center", fontsize=10, color="#6B7280")
    plt.tight_layout()
    fig.savefig(dest_path, dpi=160, bbox_inches="tight")
    plt.close(fig)
    return str(dest_path.resolve())


_LINE_MAX_SERIES = 8


def _ordered_time_categories(values: pd.Series) -> list:
    """将时间/年月轴按时间顺序排列，避免字符串或 seaborn 默认顺序错乱。"""
    uniq = [v for v in values.dropna().unique().tolist()]
    if not uniq:
        return []

    as_series = pd.Series(uniq, dtype=object)
    for fmt in ("%Y-%m", "%Y-%m-%d", "%Y/%m", "%Y%m"):
        try:
            parsed = pd.to_datetime(as_series.astype(str), errors="coerce", format=fmt)
            if parsed.notna().all():
                order = sorted(range(len(uniq)), key=lambda i: parsed.iloc[i])
                return [uniq[i] for i in order]
        except (ValueError, TypeError):
            continue

    try:
        parsed = pd.to_datetime(as_series.astype(str), errors="coerce")
        if parsed.notna().mean() >= 0.8:
            order = sorted(
                range(len(uniq)),
                key=lambda i: parsed.iloc[i] if pd.notna(parsed.iloc[i]) else pd.Timestamp.min,
            )
            return [uniq[i] for i in order]
    except (ValueError, TypeError):
        pass

    return sorted(uniq, key=str)


def _resolve_line_series_column(
    df: pd.DataFrame,
    plan: VizPlan,
    x_column: str,
    y_column: str,
) -> str | None:
    explicit = plan.category_column or plan.hue_column
    if (
        explicit
        and explicit in df.columns
        and explicit not in (x_column, y_column)
        and df[explicit].nunique(dropna=True) > 1
    ):
        return explicit

    from agents.viz_agent.line_plan import infer_line_series_column

    return infer_line_series_column(df, x_column, y_column)


def _prepare_line_dataframe(
    df: pd.DataFrame,
    plan: VizPlan,
) -> tuple[pd.DataFrame, str, str, str | None, list, str | None]:
    x_c, y_c = plan.x_column, plan.y_column
    if not x_c or not y_c:
        raise ValueError("line 需要 x_column、y_column")
    if x_c not in df.columns or y_c not in df.columns:
        raise ValueError("line 列名不在 DataFrame 中")

    series_col = _resolve_line_series_column(df, plan, x_c, y_c)
    use_cols = [x_c, y_c] + ([series_col] if series_col else [])
    plot_df = df[use_cols].copy()
    plot_df[y_c] = pd.to_numeric(plot_df[y_c], errors="coerce")
    plot_df = plot_df.dropna(subset=[y_c])
    if plot_df.empty:
        raise ValueError("line 无有效数值行")

    if series_col:
        plot_df = plot_df.groupby([x_c, series_col], as_index=False, observed=True)[
            y_c
        ].sum()
        n_series = int(plot_df[series_col].nunique())
        legend_note = None
        if n_series > _LINE_MAX_SERIES:
            top_groups = (
                plot_df.groupby(series_col, observed=True)[y_c]
                .sum()
                .nlargest(_LINE_MAX_SERIES)
                .index.tolist()
            )
            plot_df = plot_df[plot_df[series_col].isin(top_groups)]
            legend_note = f"Top {_LINE_MAX_SERIES}"
    else:
        plot_df = plot_df.groupby(x_c, as_index=False)[y_c].sum()
        legend_note = None

    x_order = _ordered_time_categories(plot_df[x_c])
    plot_df[x_c] = pd.Categorical(plot_df[x_c], categories=x_order, ordered=True)
    if series_col:
        plot_df = plot_df.sort_values([series_col, x_c])
    else:
        plot_df = plot_df.sort_values(x_c)

    return plot_df, x_c, y_c, series_col, x_order, legend_note


def _style_line_axes(
    ax: plt.Axes,
    *,
    x_column: str,
    y_column: str,
    series_column: str | None,
    legend_note: str | None,
    extras: RenderExtras | None,
) -> None:
    ax.set_xlabel(_human_axis_label(x_column))
    ax.set_ylabel(_human_value_label(y_column))
    if extras and extras.value_format == "currency":
        _format_axis_currency(ax, axis="y")
    ax.grid(True, alpha=0.35)
    ax.tick_params(axis="x", rotation=45)

    if series_column:
        title = _human_axis_label(series_column)
        if legend_note:
            title = f"{title}（{legend_note}）"
        ax.legend(
            title=title,
            bbox_to_anchor=(1.02, 1),
            loc="upper left",
            frameon=True,
            fontsize=8,
        )
    elif ax.get_legend_handles_labels()[0]:
        ax.legend(loc="upper left", frameon=True, fontsize=9)


def _render_line_with_forecast(
    df: pd.DataFrame,
    plan: VizPlan,
    ax: plt.Axes,
    extras: RenderExtras | None,
) -> None:
    plot_df, x_c, y_c, series_col, x_order, legend_note = _prepare_line_dataframe(
        df, plan
    )

    if series_col:
        sns.lineplot(
            data=plot_df,
            x=x_c,
            y=y_c,
            hue=series_col,
            marker="o",
            linewidth=2.0,
            markersize=4,
            ax=ax,
            palette="tab10",
            sort=False,
            errorbar=None,
        )
        _style_line_axes(
            ax,
            x_column=x_c,
            y_column=y_c,
            series_column=series_col,
            legend_note=legend_note,
            extras=extras,
        )
        return

    hist_x = [str(v) for v in x_order]
    indexed = plot_df.set_index(x_c)[y_c]
    hist_y = [float(indexed.loc[cat]) for cat in x_order]

    ax.plot(
        hist_x,
        hist_y,
        marker="o",
        linewidth=2.4,
        color=_PALETTE["primary"],
        label="历史 GMV",
        markersize=5,
    )

    forecast = (extras.forecast if extras else None) or {}
    if forecast.get("ok"):
        fc_x = list(forecast.get("periods") or [])
        fc_y = forecast.get("values") or []
        fc_lo = forecast.get("lower") or []
        fc_hi = forecast.get("upper") or []
        if fc_x and fc_y:
            offset = len(hist_x)
            x_idx = list(range(offset, offset + len(fc_x)))
            ax.axvline(offset - 0.5, color="#9CA3AF", linestyle="--", linewidth=1, alpha=0.8)
            ax.fill_between(
                x_idx,
                fc_lo,
                fc_hi,
                color=_PALETTE["forecast"],
                alpha=0.18,
                label="95% 置信区间",
            )
            ax.plot(
                x_idx,
                fc_y,
                marker="D",
                linewidth=2.2,
                linestyle="--",
                color=_PALETTE["forecast"],
                label="未来 6 周预测",
                markersize=5,
            )
            all_x = hist_x + fc_x
            all_pos = list(range(len(all_x)))
            ax.set_xticks(all_pos)
            ax.set_xticklabels(all_x, rotation=45, ha="right")

    _style_line_axes(
        ax,
        x_column=x_c,
        y_column=y_c,
        series_column=None,
        legend_note=None,
        extras=extras,
    )


def render_to_png(
    df: pd.DataFrame,
    plan: VizPlan,
    dest_path: Path,
    *,
    extras: RenderExtras | None = None,
) -> str:
    """将图表写入 dest_path（.png），返回绝对路径字符串。"""
    _apply_style()
    dest_path = dest_path.resolve()
    dest_path.parent.mkdir(parents=True, exist_ok=True)

    chart = plan.chart_type
    subtitle = (extras.subtitle if extras else "") or ""

    if chart == "wordcloud" and extras and extras.wordcloud_compare:
        return _render_wordcloud_compare(extras, dest_path, plan.title)

    fig, ax = plt.subplots(figsize=(11, 6.5))

    if chart == "wordcloud":
        from wordcloud import WordCloud

        col = plan.text_column
        if not col or col not in df.columns:
            raise ValueError("wordcloud 需要有效的 text_column")
        text = " ".join(df[col].dropna().astype(str).tolist())
        if not text.strip():
            raise ValueError("文本列为空，无法生成词云")
        font = _wordcloud_font_path()
        wc = WordCloud(
            width=1200,
            height=700,
            background_color="white",
            font_path=font,
            collocations=False,
            colormap="Blues",
        ).generate(text)
        ax.imshow(wc, interpolation="bilinear")
        ax.axis("off")
        _style_title(ax, plan.title, subtitle)

    elif chart == "heatmap":
        r, c, v = plan.pivot_row_col, plan.pivot_col_col, plan.pivot_value_col
        if not r or not c or not v:
            raise ValueError("heatmap 需要 pivot_row_col、pivot_col_col、pivot_value_col")
        if not all(x in df.columns for x in (r, c, v)):
            raise ValueError("热力图列名不在 DataFrame 中")
        pivot = pd.pivot_table(df, index=r, columns=c, values=v, aggfunc="sum", fill_value=0)
        show_annot = pivot.size <= 80
        sns.heatmap(
            pivot,
            annot=show_annot,
            fmt=".0f",
            cmap="YlOrRd",
            linewidths=0.4,
            linecolor="white",
            ax=ax,
            cbar_kws={"label": _human_value_label(v)},
        )
        ax.set_xlabel(_human_axis_label(c))
        ax.set_ylabel(_human_axis_label(r))
        _style_title(ax, plan.title, subtitle)

    elif chart == "geo_scatter":
        lat_c, lng_c = plan.lat_column, plan.lng_column
        if not lat_c or not lng_c:
            raise ValueError("geo_scatter 需要 lat_column、lng_column")
        plot_df = df.dropna(subset=[lat_c, lng_c]).copy()
        if plot_df.empty:
            raise ValueError("无有效经纬度数据")

        color_col = (extras.color_column if extras else None) or plan.hue_column
        size_col = plan.size_column
        sizes = 80
        colors = _PALETTE["primary"]

        if size_col and size_col in plot_df.columns:
            s_raw = pd.to_numeric(plot_df[size_col], errors="coerce").fillna(1)
            sizes = (s_raw / s_raw.max() * 700).clip(lower=40)

        if color_col and color_col in plot_df.columns:
            c_raw = pd.to_numeric(plot_df[color_col], errors="coerce").fillna(0)
            sc = ax.scatter(
                plot_df[lng_c],
                plot_df[lat_c],
                s=sizes,
                c=c_raw,
                cmap="YlOrRd",
                alpha=0.78,
                edgecolors="white",
                linewidths=0.6,
            )
            plt.colorbar(sc, ax=ax, label="销售额 GMV", shrink=0.85)
        else:
            ax.scatter(
                plot_df[lng_c],
                plot_df[lat_c],
                s=sizes,
                c=colors,
                alpha=0.65,
                edgecolors="white",
                linewidths=0.6,
            )

        label_col = plan.x_column
        if label_col and label_col in plot_df.columns:
            for _, row in plot_df.iterrows():
                ax.annotate(
                    str(row[label_col]),
                    (row[lng_c], row[lat_c]),
                    fontsize=8,
                    ha="center",
                    va="center",
                    color="#111827",
                    fontweight="bold",
                )
        ax.set_xlabel("经度")
        ax.set_ylabel("纬度")
        _style_title(ax, plan.title, subtitle)

    elif chart == "scatter":
        x_c, y_c = plan.x_column, plan.y_column
        if not x_c or not y_c:
            raise ValueError("scatter 需要 x_column、y_column")
        plot_df = df.copy()
        plot_df[x_c] = pd.to_numeric(plot_df[x_c], errors="coerce")
        plot_df[y_c] = pd.to_numeric(plot_df[y_c], errors="coerce")
        plot_df = plot_df.dropna(subset=[x_c, y_c])
        hue_col = (
            plan.hue_column
            if plan.hue_column and plan.hue_column in plot_df.columns
            else None
        )
        if hue_col:
            palette = _DELIVERY_COLORS
        else:
            palette = None

        if plan.size_column and plan.size_column in plot_df.columns:
            s_raw = pd.to_numeric(plot_df[plan.size_column], errors="coerce").fillna(1)
            mx = float(s_raw.max()) or 1.0
            plot_df = plot_df.assign(_bubble=(s_raw / mx * 500).clip(lower=20))
            sns.scatterplot(
                data=plot_df,
                x=x_c,
                y=y_c,
                size="_bubble",
                hue=hue_col,
                palette=palette,
                sizes=(30, 450),
                alpha=0.62,
                edgecolor="white",
                linewidth=0.4,
                ax=ax,
            )
        else:
            sns.scatterplot(
                data=plot_df,
                x=x_c,
                y=y_c,
                hue=hue_col,
                palette=palette,
                alpha=0.62,
                ax=ax,
            )
        ax.set_xlabel("商品重量（g，分桶）")
        ax.set_ylabel("运费（R$）")
        _style_title(ax, plan.title, subtitle)

    elif chart == "line":
        from agents.viz_agent.line_plan import normalize_line_plan

        plan = normalize_line_plan(df, plan)
        series_col = plan.category_column or plan.hue_column
        if (
            series_col
            and series_col in df.columns
            and df[series_col].nunique(dropna=True) > 1
        ):
            fig.set_size_inches(12.5, 6.5)
        _render_line_with_forecast(df, plan, ax, extras)
        _style_title(ax, plan.title, subtitle)

    elif chart == "bar":
        cat = plan.x_column or plan.category_column
        val = plan.y_column
        if (
            val
            and val in df.columns
            and len(df) == 1
            and (not cat or cat not in df.columns)
        ):
            metric = pd.to_numeric(df[val].iloc[0], errors="coerce")
            if pd.isna(metric):
                raise ValueError("bar 图无法读取单一汇总数值")
            label = plan.title or _human_value_label(val)
            kpi_df = pd.DataFrame({"指标": [label], val: [float(metric)]})
            sns.barplot(
                data=kpi_df,
                x=val,
                y="指标",
                ax=ax,
                orient="h",
                color=_PALETTE["primary"],
            )
            if extras and extras.value_format == "currency":
                _format_axis_currency(ax, axis="x")
            ax.set_xlabel(_human_value_label(val))
            ax.set_ylabel("")
        elif cat and cat in df.columns and val and val in df.columns:
            plot_df = df[[cat, val]].dropna().copy()
            plot_df[val] = pd.to_numeric(plot_df[val], errors="coerce")
            plot_df = plot_df.dropna(subset=[val]).sort_values(val, ascending=True).tail(20)
            sns.barplot(
                data=plot_df,
                x=val,
                y=cat,
                ax=ax,
                orient="h",
                color=_PALETTE["primary"],
            )
            if extras and extras.value_format == "currency":
                _format_axis_currency(ax, axis="x")
        elif cat and cat in df.columns:
            vc = df[cat].astype(str).value_counts().head(20)
            sns.barplot(x=vc.values, y=vc.index, ax=ax, orient="h", color=_PALETTE["primary"])
            ax.set_xlabel("计数")
        else:
            first_cat = None
            for c in df.columns:
                if df[c].dtype == object or str(df[c].dtype).startswith("string"):
                    first_cat = c
                    break
            if first_cat is None:
                raise ValueError("bar 图无法推断类别列")
            vc = df[first_cat].astype(str).value_counts().head(20)
            sns.barplot(x=vc.values, y=vc.index, ax=ax, orient="h", color=_PALETTE["primary"])
            ax.set_xlabel("计数")
        _style_title(ax, plan.title or ax.get_title(), subtitle)

    else:
        plt.close(fig)
        raise ValueError(f"未知 chart_type: {chart}")

    plt.tight_layout()
    fig.savefig(dest_path, dpi=160, bbox_inches="tight")
    plt.close(fig)
    return str(dest_path)
