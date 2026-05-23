"""根据 VizPlan 与 DataFrame 渲染 PNG（matplotlib / seaborn / wordcloud）。"""

from __future__ import annotations

import platform
import warnings
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd
import seaborn as sns

from schema import VizPlan

warnings.filterwarnings("ignore", category=UserWarning, module="matplotlib")


def _configure_matplotlib_zh() -> None:
    plt.rcParams["axes.unicode_minus"] = False
    if platform.system() == "Windows":
        plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "Arial Unicode MS"]
    else:
        plt.rcParams["font.sans-serif"] = [
            "Arial Unicode MS",
            "Noto Sans CJK SC",
            "PingFang SC",
            "Heiti TC",
            "DejaVu Sans",
        ]


def _wordcloud_font_path() -> str | None:
    if platform.system() == "Windows":
        p = Path(r"C:\Windows\Fonts\msyh.ttc")
        if p.is_file():
            return str(p)
    return None


def render_to_png(df: pd.DataFrame, plan: VizPlan, dest_path: Path) -> str:
    """
    将图表写入 dest_path（.png），返回绝对路径字符串。
    """
    _configure_matplotlib_zh()
    dest_path = dest_path.resolve()
    dest_path.parent.mkdir(parents=True, exist_ok=True)

    fig, ax = plt.subplots(figsize=(10, 6))
    chart = plan.chart_type

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
        ).generate(text)
        ax.imshow(wc, interpolation="bilinear")
        ax.axis("off")
        ax.set_title(plan.title)

    elif chart == "heatmap":
        r, c, v = plan.pivot_row_col, plan.pivot_col_col, plan.pivot_value_col
        if not r or not c or not v:
            raise ValueError("heatmap 需要 pivot_row_col、pivot_col_col、pivot_value_col")
        if not all(x in df.columns for x in (r, c, v)):
            raise ValueError("热力图列名不在 DataFrame 中")
        pivot = pd.pivot_table(df, index=r, columns=c, values=v, aggfunc="mean")
        sns.heatmap(pivot, annot=(pivot.size <= 120), fmt=".2f", cmap="YlOrRd", ax=ax)
        ax.set_title(plan.title)

    elif chart == "geo_scatter":
        lat_c, lng_c = plan.lat_column, plan.lng_column
        if not lat_c or not lng_c:
            raise ValueError("geo_scatter 需要 lat_column、lng_column")
        if not all(x in df.columns for x in (lat_c, lng_c)):
            raise ValueError("经纬度列不存在")
        tmp = df[[lat_c, lng_c]].dropna().copy()
        if plan.size_column and plan.size_column in df.columns:
            tmp["_sz"] = pd.to_numeric(df.loc[tmp.index, plan.size_column], errors="coerce").fillna(1)
            sz = (tmp["_sz"] / tmp["_sz"].max() * 400).clip(lower=10)
        else:
            sz = 30
        ax.scatter(
            tmp[lng_c],
            tmp[lat_c],
            s=sz if hasattr(sz, "__len__") else sz,
            alpha=0.5,
            c="steelblue",
            edgecolors="none",
        )
        ax.set_xlabel("经度")
        ax.set_ylabel("纬度")
        ax.set_title(plan.title)

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
        if plan.size_column and plan.size_column in plot_df.columns:
            s_raw = pd.to_numeric(plot_df[plan.size_column], errors="coerce").fillna(1)
            mx = float(s_raw.max()) or 1.0
            plot_df = plot_df.assign(
                _bubble=(s_raw / mx * 400).clip(lower=15),
            )
            sns.scatterplot(
                data=plot_df,
                x=x_c,
                y=y_c,
                size="_bubble",
                hue=hue_col,
                sizes=(20, 500),
                legend=False,
                ax=ax,
            )
        else:
            sns.scatterplot(data=plot_df, x=x_c, y=y_c, hue=hue_col, ax=ax)
        ax.set_title(plan.title)

    elif chart == "line":
        x_c, y_c = plan.x_column, plan.y_column
        if not x_c or not y_c:
            raise ValueError("line 需要 x_column、y_column")
        plot_df = df[[x_c, y_c]].dropna().copy()
        plot_df[y_c] = pd.to_numeric(plot_df[y_c], errors="coerce")
        plot_df = plot_df.dropna(subset=[y_c])
        plot_df = plot_df.sort_values(x_c)
        ax.plot(plot_df[x_c].astype(str), plot_df[y_c], marker="o", linewidth=2)
        ax.tick_params(axis="x", rotation=45)
        ax.set_title(plan.title)
        ax.grid(True, alpha=0.3)

    elif chart == "bar":
        cat = plan.x_column or plan.category_column
        val = plan.y_column
        if cat and cat in df.columns and val and val in df.columns:
            plot_df = df[[cat, val]].dropna().copy()
            plot_df[val] = pd.to_numeric(plot_df[val], errors="coerce")
            plot_df = plot_df.dropna(subset=[val]).sort_values(val, ascending=False).head(40)
            sns.barplot(data=plot_df, x=val, y=cat, ax=ax, orient="h")
        elif cat and cat in df.columns:
            vc = df[cat].astype(str).value_counts().head(30)
            sns.barplot(x=vc.values, y=vc.index, ax=ax, orient="h")
            ax.set_xlabel("计数")
        else:
            first_cat = None
            for c in df.columns:
                if df[c].dtype == object or str(df[c].dtype).startswith("string"):
                    first_cat = c
                    break
            if first_cat is None:
                raise ValueError("bar 图无法推断类别列")
            vc = df[first_cat].astype(str).value_counts().head(30)
            sns.barplot(x=vc.values, y=vc.index, ax=ax, orient="h")
            ax.set_xlabel("计数")
            if not plan.title:
                ax.set_title(f"{first_cat} 频次 Top")
        ax.set_title(plan.title or ax.get_title())

    else:
        raise ValueError(f"未知 chart_type: {chart}")

    plt.tight_layout()
    fig.savefig(dest_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return str(dest_path)
