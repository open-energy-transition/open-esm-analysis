"""Create Streamlit web app to visualise tool inventory data.

(C) Open Energy Transition (OET)
License: MIT / CC0 1.0
"""

import datetime
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Literal

import git
import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from st_keyup import st_keyup

COLUMN_NAME_MAPPING: dict[str, str] = {
    "created_at": "Created",
    "updated_at": "Updated",
    "stargazers_count": "Stars",
    "commit_stats.total_committers": "Contributors",
    "commit_stats.dds": "DDS",
    "forks_count": "Forks",
    "dependent_repos_count": "Dependents",
    "last_month_downloads": "Last Month Downloads",
    "category": "Category",
}

COLUMN_DTYPES: dict[str, Callable] = {
    "created_at": pd.to_datetime,
    "updated_at": pd.to_datetime,
    "stargazers_count": pd.to_numeric,
    "commit_stats.total_committers": pd.to_numeric,
    "commit_stats.dds": lambda x: 100 * pd.to_numeric(x),
    "forks_count": pd.to_numeric,
    "dependent_repos_count": pd.to_numeric,
    "last_month_downloads": pd.to_numeric,
    "category": lambda x: x.str.split(","),
}

NUMBER_FORMAT: dict[str, str] = {
    "Stars": "localized",
    "Contributors": "localized",
    "DDS": "%d%%",
    "Forks": "localized",
    "Dependents": "localized",
    "Last Month Downloads": "localized",
}

COLUMN_HELP: dict[str, str] = {
    "Created": "First ever repository commit",
    "Updated": "Most recent repository commit",
    "Stars": "Repository bookmarks",
    "Contributors": "active source code contributors",
    "DDS": "Development distribution score (the bigger the number the better, 0 means only one contributor. [Click for more info](https://report.opensustain.tech/chapters/development-distribution-score))",
    "Forks": "Number of Git forks",
    "Dependents": "Packages dependent on this project (only available if the project is indexed on a package repository)",
    "Last Month Downloads": "Package installs last month (only available if the project is indexed on a package repository)",
    "Category": "Category of energy system planning / operation problem for which this tool could be used. This is based on [G-PST entries](https://api.github.com/repos/G-PST/opentools) and our own manual assignment applied to a subset of tools.",
    "Docs": "Link to tool documentation.",
    "Score": "The tool score is a weighted average of all numeric metrics, after scaling those metrics to similar ranges.",
}

DEFAULT_ORDER = "Stars"


def create_vis_table(tool_data_dir: Path) -> pd.DataFrame:
    """Create the tool table with columns renamed and filtered ready for visualisation.

    Args:
        tool_data_dir (Path): The directory in which to find tool list and stats.

    Returns:
        pd.DataFrame: Filtered and column renamed tool table.
    """
    stats_df = pd.read_csv(tool_data_dir / "stats.csv", index_col=0)
    tools_df = pd.read_csv(tool_data_dir / "filtered.csv", index_col="url")

    df = (
        pd.merge(left=stats_df, right=tools_df, right_index=True, left_index=True)
        .rename_axis(index="url")
        .reset_index()
    )

    # Assume: projects categorised as "Jupyter Notebook" are actually Python projects.
    # This occurs because the repository language is based on number of lines and Jupyter Notebooks have _a lot_ of lines.
    df["language"] = df.language.replace({"Jupyter Notebook": "Python"})

    df["name"] = df.url + "#" + df.name.apply(lambda x: x.split(",")[0])

    for col, dtype_func in COLUMN_DTYPES.items():
        df[col] = dtype_func(df[col])
    df["Docs"] = df["pages"].fillna(df["rtd"]).fillna(df["wiki"]).fillna(df["homepage"])
    df["Score"] = pd.Series(
        np.random.choice([0, 100], size=len(df.index)), index=df.index
    )
    df_vis = df.rename(columns=COLUMN_NAME_MAPPING)[
        ["name", "Docs", "Score"] + list(COLUMN_NAME_MAPPING.values())
    ]
    return df_vis


def is_datetime_column(series: pd.Series) -> bool:
    """Check if a column is datetime."""
    return pd.api.types.is_datetime64_any_dtype(series)


def is_numeric_column(series: pd.Series) -> bool:
    """Check if a column is numeric."""
    return pd.api.types.is_numeric_dtype(series)


def is_categorical_column(series: pd.Series) -> bool:
    """Check if a column should be treated as categorical."""
    return isinstance(series.dtype, pd.StringDtype | pd.CategoricalDtype)


def is_list_column(series: pd.Series) -> bool:
    """Check if a column contains lists of items."""
    return all(series.dropna().apply(lambda x: isinstance(x, list)))


def nan_filter(col: pd.Series) -> pd.Series:
    """Remove rows with NaNs in column.

    Args:
        col (pd.Series): Column potentially containing NaNs

    Returns:
        pd.Series: Filtered `col`.
    """
    return col.notna()


def numeric_range_filter(
    col: pd.Series, min_val: float | int, max_val: float | int
) -> pd.Series:
    """Filter numeric column.

    Args:
        col (pd.Series): Column to filter.
        min_val (float | int): Lower bound (inclusive).
        max_val (float | int): Upper bound (inclusive).

    Returns:
        pd.Series: Filtered `col`.
    """
    return ((col >= min_val) & (col <= max_val)) | col.isna()


def date_range_filter(
    col: pd.Series, start_date: datetime.date, end_date: datetime.date
) -> pd.Series:
    """Filter datetime column.

    Will only filter to dates, not to hours or other high frequencies.

    Args:
        col (pd.Series): Column to filter.
        start_date (datetime.date): Lower datetime bound (inclusive).
        end_date (datetime.date): Upper datetime bound (inclusive).

    Returns:
        pd.Series: Filtered `col`.
    """
    start_datetime = pd.Timestamp(start_date)
    end_datetime = pd.Timestamp(end_date) + pd.Timedelta(hours=23, minutes=59)
    col_no_tz = col.dt.tz_localize(None)
    return ((col_no_tz >= start_datetime) & (col_no_tz <= end_datetime)) | col.isna()


def categorical_filter(col: pd.Series, to_filter: Iterable) -> pd.Series:
    """Filter string columns.

    Args:
        col (pd.Series): Column to filter.
        to_filter (Iterable): List of category items to keep.

    Returns:
        pd.Series: Filtered `col`.
    """
    return col.isin(to_filter) | col.isna()


def list_filter(col: pd.Series, to_filter: Iterable) -> pd.Series:
    """Filter list columns.

    Dataframes shouldn't really be holding lists so this is a bit of a hack.

    Args:
        col (pd.Series): Column to filter.
        to_filter (Iterable): List of category items to keep.

    Returns:
        pd.Series: Filtered `col`.
    """
    with pd.option_context("future.no_silent_downcasting", True):
        return (
            col.dropna()
            .apply(lambda x: any(i in x for i in to_filter))
            .reindex(col.index)
            .fillna(True)
            .infer_objects()
        )


def add_scoring(cols: list[str]) -> float:
    """Create inputs for defining the score weighting for a given column and the metric scaling method.

    Args:
        cols (list[str]): List
        score_col (st.container): Streamlit column in which to add the number input.

    Returns:
        float: Column score weighting
    """
    selectbox_cols = st.columns(len(cols))
    selectbox_cols[0].selectbox(
        "Metric scaling method",
        ("min-max", "rank"),
        help="""Select the method by which metrics should be scaled to bring them to a similar range.
    `min-max` uses [min-max normalisation](https://en.wikipedia.org/wiki/Feature_scaling#Rescaling_(min-max_normalization)).
    `rank` uses the absolute rank of a tool for each metric.""",
        key="scoring_method",
    )
    score_cols = st.columns(len(cols))
    for i, score_col in enumerate(score_cols):
        col_name = cols[i]
        number = score_col.number_input(
            label=col_name,
            min_value=0.0,
            max_value=1.0,
            value=0.5,
            step=0.1,
            format="%0.01f",
            key=f"scoring_{col_name}",
        )

    return number


def update_score_col(df: pd.DataFrame) -> pd.Series:
    """Generate a new set of scores by combining all columns of the given dataframe.

    Args:
        df (pd.DataFrame): Tool metric table containing only columns relevant to scoring.

    Returns:
        pd.Series: Tool score.
    """
    # Add tool score by combining metrics with the provided weightings
    scores = {col: st.session_state.get(f"scoring_{col}", 0.5) for col in df.columns}
    scoring_method = st.session_state.get("scoring_method", "min-max")
    normalised_data = normalise(df, scoring_method)
    score = normalised_data.mul(scores).div(sum(scores.values())).sum(axis=1).mul(100)
    return score


def normalise(
    df: pd.DataFrame, scaling_method: Literal["min-max", "rank"]
) -> pd.DataFrame:
    """Scale each column of the given dataframe relative to data in that column.

    Args:
        df (pd.DataFrame): Tool metric table. All columns must be numeric.
        scaling_method (Literal[min-max, rank]): Tool scaling method to use

    Returns:
        pd.DataFrame: `df` with each column scaled.
    """
    if scaling_method == "min-max":
        return (df - df.min()) / (df.max() - df.min())
    elif scaling_method == "rank":
        return df.rank() / df.rank().max()


def slider(
    col: pd.Series, reset_mode: bool, plot_dist: bool = True
) -> tuple[float, float] | tuple[datetime.date, datetime.date]:
    """Generate a slider for numeric / datetime table data.

    Args:
        col (pd.Series): Data table column.
        reset_mode (bool): Whether to reset slider to initial values.
        plot_dist (bool): If True, add a distribution plot of the column's data above the slider.

    Returns:
        tuple[float, float] | tuple[datetime.date, datetime.date]:
            Min/max values given by slider to use in data table filtering.
            Will be in datetime format if that was the format of the inputs, otherwise floats.
    """
    if col.dtype.kind == "M":
        default_range = (col.min().date(), col.max().date())
    else:
        default_range = (col.min(), col.max())
    current_range = (
        default_range
        if reset_mode
        else st.session_state.get(f"slider_{col.name}", default_range)
    )
    if col.dtype.kind == "M":
        slider_range = tuple(pd.Timestamp(i).timestamp() for i in current_range)
        col = col.apply(lambda x: x.timestamp())
    else:
        slider_range = current_range

    if plot_dist:
        dist_plot(col, slider_range)
    selected_range = st.sidebar.slider(
        f"Range for {col.name}",
        min_value=default_range[0],
        max_value=default_range[1],
        value=current_range,
        key=f"slider_{col.name}",
    )

    return selected_range


def multiselect(unique_values: list[str], col: str, reset_mode: bool) -> list[str]:
    """Generate a multiselect box for categorical table data.

    Args:
        unique_values (list[str]): Unique categorical values.
        col (str): Column name.
        reset_mode (bool): Whether to reset multiselect to initial values.

    Returns:
        list[str]: values given by multiselect to use in data table filtering.
    """
    current_selected = (
        unique_values
        if reset_mode
        else st.session_state.get(f"multiselect_{col}", unique_values)
    )
    selected_values = st.sidebar.multiselect(
        f"Select {col} values",
        options=unique_values,
        default=current_selected,
        key=f"multiselect_{col}",
    )
    return selected_values


def reset(button_press: bool = False) -> bool:
    """Return result of the reset button having been pressed.

    Args:
        button_press (bool, optional): If pressed, this will be True. Defaults to False.

    Returns:
        bool: True if it is time to reset, False otherwise.
    """
    # Reset filters button and logic
    if button_press:
        # Set a flag to indicate we want to reset
        st.session_state["reset_filters"] = True
        st.rerun()

    # Check if we need to reset filters
    reset_mode = st.session_state.get("reset_filters", False)
    if reset_mode:
        # Clear the reset flag
        st.session_state["reset_filters"] = False
    return reset_mode


def header_and_missing_value_toggle(col: pd.Series, reset_mode: bool) -> bool:
    """Create sidebar subheader and missing value toggle for a column.

    Args:
        col (pd.Series): Stats table column.
        reset_mode (bool): Whether to reset multiselect to initial values.

    Returns:
        bool: True if there are NaN values and the missing value toggle is switched on.
    """
    name: str = col.name  # type:ignore
    missing_count = col.isnull().sum()
    if missing_count > 0:
        missing_text = f"🚫 Missing values: {missing_count}"
        st.sidebar.subheader(f"{name} ({missing_text})", help=COLUMN_HELP[name])
        exclude_nan = st.sidebar.toggle(
            f"Exclude missing values for {name}",
            value=False
            if reset_mode
            else st.session_state.get(f"exclude_nan_{name}", False),
            key=f"exclude_nan_{name}",
        )
    else:
        missing_text = "✅ No missing values"
        st.sidebar.subheader(f"{name} ({missing_text})", help=COLUMN_HELP[name])
        exclude_nan = False
    return exclude_nan


@st.cache_data
def _distribution_table(col: pd.Series, bins: int = 30) -> pd.DataFrame:
    """Pre-compute histogram representing the distribution of values for each numeric column of the tool stats table.

    This reduces the calculation complexity on re-running the streamlit app.

    Args:
        col (pd.Series): Numeric column of the tool stats table.
        bins (int): Number of histogram bins to use in generating the tables. Defaults to 30.

    Returns:
        pd.DataFrame: x/y values of histogram describing the distribution of values in `col`.
    """
    y, x = np.histogram(col.dropna(), bins=bins)
    # bin edges to midpoint
    x = [(a + b) / 2 for a, b in zip(x, x[1:])]

    return pd.DataFrame({"x": x, "y": y})


def _plotly_plot(df: pd.DataFrame) -> go.Figure:
    """Create a static plotly bar plot.

    The fill colour of bars is dictated by the "color" column, with "in"/"out" values in the column coloured as red/grey, respectively.
    The resulting figure will have no interactivity.
    These plots are meant to be updated by user-induced changes that are passed by streamlit in the form of changes to the dataframe.

    Args:
        df (pd.DataFrame): Data to plot, with "x", "y", and "color" columns

    Returns:
        go.Figure: Plotly figure.
    """
    fig = px.bar(
        df,
        x="x",
        y="y",
        color="color",
        color_discrete_map={"in": "#FF4B4B", "out": "#A3A8B8"},
    )
    fig.update_layout(
        yaxis_title=None,
        yaxis={"visible": False, "range": (0, df.y.max())},
        xaxis={"visible": False},
        margin={"b": 0, "t": 0},
        bargap=0,
        showlegend=False,
        height=100,
        title="",
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
    )
    fig.update_traces(hoverinfo="skip", hovertemplate=None)
    return fig


def dist_plot(col: pd.Series, slider_range: tuple[float, float]) -> None:
    """Create a distribution plot in the sidebar.

    Args:
        col (pd.Series): Column of data linked to the distribution data table.
        slider_range (tuple[float, float]): Min/max defined by the user-defined slider values.
    """
    df_dist = _distribution_table(col)
    df_dist["color"] = [
        "in" if ((i >= slider_range[0]) & (i <= slider_range[1])) else "out"
        for i in df_dist.x
    ]
    fig = _plotly_plot(df_dist)

    config = {"displayModeBar": False, "staticPlot": True}
    st.sidebar.plotly_chart(
        fig,
        selection_mode=[],
        use_container_width=True,
        key=f"{col.name}_chart",
        config=config,
    )


def preamble(latest_changes: str):
    """Text to show before the app table.

    Args:
        latest_changes (str): the date associated with the most recent changes to the table.
    """
    st.markdown(
        f"""
        # Smarter Investments in Open Energy Planning: How Data Can Guide Decision-Makers

        This analysis is available at OET's [open-esm-analysis GitHub repository](https://github.com/open-energy-transition/open-esm-analysis/).

        The global energy transition is moving fast, but so are the challenges in directing time and resources effectively.
        Achieving international climate goals will require around **4.5 trillion in annual investments** by the early 2030s.
        To optimize infrastructure investments, grid operations and policy decisions, open-source tools are becoming the elephant in the room with increasing adoption across all sectors (see e.g. this [ENTSO-E post on LinkedIn](https://www.linkedin.com/posts/entso-e_energytransition-opensource-innovation-activity-7293296246813851649-2ynL)).

        However, with an ever-growing number of open-source (OS) energy tools, the question remains: **How do decision-makers - whether researchers, funders, or grid operators - select the right tools for their needs?**
        The answer lies in data combined with experience.

        ## The Challenge: Identifying Reliable and Impactful Tools

        Funders and users alike need to distinguish between active, well-maintained tools and those that might no longer be viable. While qualitative reviews (user feedback, case studies, etc.) are valuable, quantitative metrics offer critical signals about a tool's reliability, sustainability, and adoption.

        The table below highlights key statistics for several leading OS energy planning tools, offering a snapshot of their development activity, usage, and maintenance.
        These tools have been collated from various publicly accessible tool inventories (see [our project homepage](https://github.com/open-energy-transition/open-esm-analysis/) for the full list!) and filtered for only those that have accessible Git repositories and are written in open source programming languages.

        ## Open-Source ESM Tools - Key Data Indicators

        **Data source**:
        - *Category*: [G-PST open tools](https://opentools.globalpst.org/) & [our own categorisation](https://github.com/open-energy-transition/open-esm-analysis/blob/main/inventory/categories.csv)
        - *All other metrics*: [ecosyste.ms](https://ecosyste.ms)

        **Last Update**: {latest_changes}

        **Default Order**: Number of {DEFAULT_ORDER} (descending)
        """
    )


def conclusion():
    """Text to show after the app table."""
    st.markdown(
        """
        ## Key Takeaways from the Data

        - **Adoption Signals Matter**: High download counts, active contributors, and ongoing issue resolutions suggest healthy, well-maintained projects. However, GitHub stars alone can be misleading—some highly starred projects have stalled development."
        - **Sustainability Risks**: Projects with fewer than 10 contributors face a higher risk of abandonment. Also depending on packages with a small number of contributors might be a risk for the project. Funders should be wary of investing in tools that lack a committed maintainer base.
        - **Transparency Gaps**: Some projects do not disclose key statistics (e.g., download counts), which may indicate poor release management and hinder long-term usability.
        - **Interoperability Potential**: Many tools serve niche roles, but interoperability—how well they integrate with others—is becoming a crucial factor for large-scale adoption.

        ## Beyond Data: The Need for Qualitative Assessments

        While data helps filter out unreliable tools, deeper investigation is needed to ensure a tool is the right fit. Some key qualitative factors to consider:

        - **Documentation Quality**: Are installation and usage guides clear and up to date?
        - **Community Support**: Is there an active forum, mailing list, or issue tracker?
        - **Use Cases**: Has the tool been applied in real-world projects similar to your needs?
        - **Licensing & Governance**: Is it permissively licensed (e.g., MIT) or does it enforce restrictions (e.g., GPL)?
        - **Collaboration Potential**: Can multiple stakeholders contribute effectively?

        ## The Case for a Live Decision-Support Platform

        Right now, there is no single source of truth for assessing the viability of open-source energy planning tools.
        An up-to-date, data-driven decision-support platform could bridge this gap, providing real-time insights on:

        - **Maintenance health** (contributor activity, unresolved issues)
        - **Adoption rates** (downloads, citations, user engagement)
        - **Tool interoperability** (compatibility testing with other OS models)
        - **Funding needs** (identifying tools at risk due to lack of maintainers)

        Such a platform would empower funders to invest wisely, helping direct resources to projects with the highest impact potential.

        Selecting the right OS energy planning tool is no longer just a technical choice — it's an **investment decision**.
        While **data-driven insights can highlight adoption trends, sustainability risks, and tool maturity**, *qualitative assessments remain essential for selecting the best fit*.

        **By combining live data tracking with structured qualitative evaluation**, the energy community can reduce wasted investments and ensure the best tools remain available for researchers, grid operators, project developers, investors and policymakers.

        **Would you find a real-time OS tool insight platform useful?** Share your thoughts and suggestions in the comments or the [issues tracker](https://github.com/open-energy-transition/open-esm-analysis/issues)!

        """
    )


def main(df: pd.DataFrame):
    """Main streamlit app generator.

    Args:
        df (pd.DataFrame): Table to display in app.
    """
    reset_mode = reset()
    st.sidebar.header("Table filters", divider=True)
    df_filtered = df
    col_config = {}
    numeric_cols = []
    # Show missing data info and toggle for docs column
    exclude_nan = header_and_missing_value_toggle(df["Docs"], reset_mode)
    if exclude_nan:
        df_filtered = df_filtered[nan_filter(df_filtered["Docs"])]

    # Add score filtering first.
    st.sidebar.subheader("Score", help=COLUMN_HELP["Score"])
    score_slider_range = slider(df["Score"], reset_mode, plot_dist=False)

    for col in COLUMN_NAME_MAPPING.values():
        # Show missing data info and toggle for each column
        exclude_nan = header_and_missing_value_toggle(df[col], reset_mode)
        if exclude_nan:
            df_filtered = df_filtered[nan_filter(df_filtered[col])]

        if is_datetime_column(df[col]):
            slider_range = slider(df[col], reset_mode)
            df_filtered = df_filtered[
                date_range_filter(df_filtered[col], *slider_range)
            ]
            col_config[col] = st.column_config.DateColumn(col, help=COLUMN_HELP[col])

        elif is_numeric_column(df[col]):
            slider_range = slider(df[col], reset_mode)

            df_filtered = df_filtered[
                numeric_range_filter(df_filtered[col], *slider_range)
            ]
            numeric_cols.append(col)
            col_config[col] = st.column_config.NumberColumn(
                col, help=COLUMN_HELP[col], format=NUMBER_FORMAT[col]
            )

        elif is_categorical_column(df[col]):
            # Categorical multiselect
            unique_values = sorted(df[col].dropna().unique().tolist())
            selected_values = multiselect(unique_values, col, reset_mode)
            df_filtered = df_filtered[
                categorical_filter(df_filtered[col], selected_values)
            ]
            col_config[col] = st.column_config.TextColumn(col, help=COLUMN_HELP[col])

        elif is_list_column(df[col]):
            # Categorical multiselect with list column entry
            unique_values = list(set(i for j in df[col].dropna().values for i in j))
            selected_values = multiselect(unique_values, col, reset_mode)
            df_filtered = df_filtered[list_filter(df_filtered[col], selected_values)]
            col_config[col] = st.column_config.ListColumn(col, help=COLUMN_HELP[col])

    # Add tool score by combining metrics with the provided weightings
    df_filtered["Score"] = update_score_col(df_filtered[numeric_cols])
    df_filtered = df_filtered[
        numeric_range_filter(df_filtered["Score"], *score_slider_range)
    ]

    # Sort the table based on default order
    df_filtered = df_filtered.sort_values(DEFAULT_ORDER, ascending=False)

    # Display options
    col1, col2 = st.columns([3, 2])
    with col2:
        search_result = st_keyup("Find a tool by name", value="", key="search_box")
    df_filtered = df_filtered[
        df_filtered["name"].str.lower().str.contains(search_result.lower())
    ]

    with col1:
        st.metric("Tools in view", f"{len(df_filtered)} / {len(df)}")
    column_config = {
        "name": st.column_config.LinkColumn(
            "Tool Name",
            help="Click on the tool name to navigate to its source code repository.",
            display_text=".*#(.*)",
        ),
        "Docs": st.column_config.LinkColumn(
            "Docs", display_text="📖", help=COLUMN_HELP["Docs"]
        ),
        "Score": st.column_config.ProgressColumn(
            "Score",
            min_value=0,
            max_value=100,
            format="%.0f%%",
            help=COLUMN_HELP["Score"],
        ),
        **col_config,
    }
    # Display the table
    if len(df_filtered) > 0:
        st.dataframe(
            df_filtered,
            use_container_width=True,
            hide_index=True,
            column_config=column_config,
            column_order=["name", "url", "Docs", "Score", *col_config.keys()],
        )
    else:
        st.warning(
            "No data matches the current filter criteria. Try adjusting your filters."
        )
    st.subheader("📊 Adjust tool scoring")
    st.markdown(
        "You can create your own tool scores by adjusting the weights applied to each numeric metric."
    )
    add_scoring(numeric_cols)

    reset_button = st.sidebar.button("🔄 Reset All Filters")
    reset_mode = reset(reset_button)


if __name__ == "__main__":
    # define the path of the CSV file listing the packages to assess
    output_dir = Path(__file__).parent.parent / "inventory" / "output"
    df_vis = create_vis_table(output_dir)
    g = git.cmd.Git()
    latest_changes = g.log("-1", "--pretty=%cs", output_dir / "stats.csv")

    st.set_page_config(layout="wide")
    preamble(latest_changes)
    main(df_vis)
    conclusion()
