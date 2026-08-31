import re
import pandas as pd
import streamlit as st


# --------------------
# SETTINGS
# --------------------

REPORT_COLUMNS = [
    "task_name",
    "priority",
    "status",
    "due_date",
    "days_remaining",
    "urgency",
    "dependencies",
]

COLUMN_ALIASES = {
    "task_name": ["task_name", "task", "title", "name"],
    "project": ["project", "project_name"],
    "owner": ["owner", "assignee", "assigned_to", "responsible"],
    "priority": ["priority", "importance"],
    "status": ["status", "task_status", "state"],
    "due_date": ["due_date", "due", "deadline", "target_date"],
    "dependencies": ["dependencies", "dependency", "depends_on", "blocked_by"],
}


# --------------------
# DATA PREPARATION
# --------------------

def normalize_column_name(column_name):
    column_name = str(column_name).strip().lower()
    return re.sub(r"[^a-z0-9]+", "_", column_name).strip("_")


def get_urgency(days_remaining):
    if pd.isna(days_remaining):
        return "No due date"
    if days_remaining < 0:
        return "Overdue"
    if days_remaining == 0:
        return "Due today"
    if days_remaining <= 2:
        return "Due soon"
    return "Later"


def load_uploaded_file(uploaded_file):
    file_type = uploaded_file.name.split(".")[-1].lower()
    uploaded_file.seek(0)

    if file_type == "csv":
        return pd.read_csv(uploaded_file)

    if file_type == "json":
        return pd.read_json(uploaded_file)

    if file_type in ["xlsx", "xls"]:
        return pd.read_excel(uploaded_file)

    raise ValueError("Upload a CSV, JSON, or Excel file.")


def standardize_columns(df):
    df = df.copy()

    df.columns = [
        normalize_column_name(column_name)
        for column_name in df.columns
    ]

    rename_map = {}

    for standard_name, aliases in COLUMN_ALIASES.items():
        matching_alias = next(
            (alias for alias in aliases if alias in df.columns),
            None,
        )

        if matching_alias:
            rename_map[matching_alias] = standard_name

    df = df.rename(columns=rename_map)

    required_fields = [
        "task_name",
        "owner",
        "priority",
        "status",
        "due_date",
    ]

    missing_fields = [
        field
        for field in required_fields
        if field not in df.columns
    ]

    if missing_fields:
        raise ValueError(
            "The uploaded file is missing required columns: "
            + ", ".join(missing_fields)
        )

    for optional_field in ["project", "dependencies"]:
        if optional_field not in df.columns:
            df[optional_field] = pd.NA

    return df


def standardize_task_values(df):
    df = df.copy()

    for field in [
        "task_name",
        "project",
        "owner",
        "priority",
        "status",
        "dependencies",
    ]:
        df[field] = df[field].astype("string").str.strip()

    status_mapping = {
        "completed": "Completed",
        "complete": "Completed",
        "done": "Completed",
        "closed": "Completed",
        "open": "Open",
        "not_started": "Not Started",
        "in_progress": "In Progress",
    }

    priority_mapping = {
        "critical": "High",
        "urgent": "High",
        "high": "High",
        "medium": "Medium",
        "moderate": "Medium",
        "normal": "Medium",
        "low": "Low",
        "minor": "Low",
    }

    status_keys = (
        df["status"]
        .str.lower()
        .str.replace(" ", "_", regex=False)
    )

    priority_keys = df["priority"].str.lower()

    df["status"] = status_keys.map(status_mapping).fillna(df["status"])
    df["priority"] = priority_keys.map(priority_mapping).fillna(df["priority"])

    df["dependencies"] = df["dependencies"].replace(
        {
            "": pd.NA,
            "None": pd.NA,
            "none": pd.NA,
        }
    )

    df["due_date"] = pd.to_datetime(
        df["due_date"],
        errors="coerce",
    )

    return df


def prepare_task_data(df):
    df = standardize_columns(df)
    df = standardize_task_values(df)

    today = pd.Timestamp.today().normalize()
    deadline = today + pd.Timedelta(days=2)

    df["days_remaining"] = (df["due_date"] - today).dt.days
    df["urgency"] = df["days_remaining"].apply(get_urgency)

    df["is_unfinished"] = df["status"] != "Completed"
    df["is_overdue"] = (
        df["is_unfinished"]
        & (df["urgency"] == "Overdue")
    )
    df["is_due_today"] = (
        df["is_unfinished"]
        & (df["urgency"] == "Due today")
    )
    df["is_due_soon"] = (
        df["is_unfinished"]
        & (df["urgency"] == "Due soon")
    )

    urgency_order = {
        "Overdue": 1,
        "Due today": 2,
        "Due soon": 3,
        "Later": 4,
        "No due date": 5,
    }

    priority_order = {
        "High": 1,
        "Medium": 2,
        "Low": 3,
    }

    df["urgency_rank"] = df["urgency"].map(urgency_order)
    df["priority_rank"] = df["priority"].map(priority_order)

    task_status_lookup = (
        df.drop_duplicates("task_name", keep="last")
        .set_index("task_name")["status"]
    )

    df["dependency_task_status"] = df["dependencies"].map(
        task_status_lookup
    )

    df["is_task_blocked"] = (
        df["dependency_task_status"].notna()
        & (df["dependency_task_status"] != "Completed")
    )

    return df, today, deadline


# --------------------
# REPORT CREATION
# --------------------

def create_reports(df, owner, today, deadline):
    upcoming_tasks = df[
        (df["owner"] == owner)
        & df["is_unfinished"]
        & (df["due_date"] >= today)
        & (df["due_date"] <= deadline)
    ].sort_values("due_date")

    overdue_tasks = df[
        (df["owner"] == owner)
        & df["is_unfinished"]
        & df["is_overdue"]
    ].sort_values("due_date")

    action_list = df[
        (df["owner"] == owner)
        & df["is_unfinished"]
    ].sort_values(
        ["urgency_rank", "priority_rank", "due_date"]
    )

    owner_summary = df.groupby("owner").agg(
        total_tasks=("task_name", "count"),
        unfinished_tasks=("is_unfinished", "sum"),
        overdue_tasks=("is_overdue", "sum"),
        due_today=("is_due_today", "sum"),
        due_soon=("is_due_soon", "sum"),
    ).reset_index().sort_values(
        ["overdue_tasks", "due_today"],
        ascending=False,
    )

    dependency_watchlist = df[
        df["is_unfinished"]
        & df["dependencies"].notna()
    ].sort_values(
        ["urgency_rank", "due_date"]
    )

    blocked_tasks = df[
        df["is_unfinished"]
        & df["is_task_blocked"]
    ].sort_values(
        ["urgency_rank", "due_date"]
    )

    project_summary = pd.DataFrame(
        {
            "metric": [
                "Total tasks",
                "Unfinished tasks",
                "Completed tasks",
                "Overdue tasks",
                "Due today",
                "Due soon",
            ],
            "count": [
                len(df),
                df["is_unfinished"].sum(),
                (df["status"] == "Completed").sum(),
                df["is_overdue"].sum(),
                df["is_due_today"].sum(),
                df["is_due_soon"].sum(),
            ],
        }
    )

    required_fields = [
        "task_name",
        "owner",
        "priority",
        "status",
        "due_date",
    ]

    missing_required_tasks = df[
        df[required_fields].isna().any(axis=1)
    ]

    data_quality_summary = pd.DataFrame(
        {
            "check": [
                "Tasks with missing required values",
                "Duplicate task names",
            ],
            "count": [
                len(missing_required_tasks),
                df["task_name"].duplicated().sum(),
            ],
        }
    )

    return {
        "upcoming_tasks": upcoming_tasks[REPORT_COLUMNS],
        "overdue_tasks": overdue_tasks[REPORT_COLUMNS],
        "action_list": action_list[
            [
                "task_name",
                "priority",
                "urgency",
                "due_date",
                "days_remaining",
                "dependencies",
            ]
        ],
        "project_summary": project_summary,
        "owner_summary": owner_summary,
        "dependency_watchlist": dependency_watchlist[
            [
                "task_name",
                "owner",
                "priority",
                "urgency",
                "due_date",
                "dependencies",
            ]
        ],
        "blocked_tasks": blocked_tasks[
            [
                "task_name",
                "owner",
                "urgency",
                "due_date",
                "dependencies",
                "dependency_task_status",
            ]
        ],
        "data_quality_summary": data_quality_summary,
        "blocked_task_names": set(blocked_tasks["task_name"]),
    }


def create_daily_briefing(df, owner, reports, today):
    owner_overdue_count = (
        (df["owner"] == owner)
        & df["is_overdue"]
    ).sum()

    owner_due_today_count = (
        (df["owner"] == owner)
        & df["is_due_today"]
    ).sum()

    owner_blocked_count = (
        (df["owner"] == owner)
        & df["is_task_blocked"]
    ).sum()

    briefing_lines = [
        f"{owner.upper()} DAILY PROJECT BRIEFING",
        f"Date: {today.date()}",
        "",
        f"Overdue tasks: {owner_overdue_count}",
        f"Tasks due today: {owner_due_today_count}",
        f"Tasks blocked by another open task: {owner_blocked_count}",
        "",
        "Top priorities:",
    ]

    for _, task in reports["action_list"].head(3).iterrows():
        blocked_note = ""

        if task["task_name"] in reports["blocked_task_names"]:
            blocked_note = f", blocked by: {task['dependencies']}"

        briefing_lines.append(
            f"- {task['task_name']} "
            f"({task['priority']} priority, {task['urgency']}, "
            f"due {task['due_date'].date()}{blocked_note})"
        )

    return "\n".join(briefing_lines)


def dataframe_to_csv(dataframe):
    return dataframe.to_csv(index=False).encode("utf-8")


# --------------------
# BROWSER APP
# --------------------

st.set_page_config(
    page_title="Project Manager Assistant",
    page_icon="📋",
    layout="wide",
)

st.title("📋 Personal Project Manager Assistant")
st.write(
    "Upload a CSV, JSON, or Excel task file to generate task reports."
)

uploaded_file = st.file_uploader(
    "Upload task data",
    type=["csv", "json", "xlsx", "xls"],
)

if uploaded_file is None:
    st.info("Upload a task file to begin.")
    st.stop()

try:
    raw_data = load_uploaded_file(uploaded_file)
    df, today, deadline = prepare_task_data(raw_data)

except Exception as error:
    st.error(f"Unable to analyze this file: {error}")
    st.stop()

owners = sorted(df["owner"].dropna().unique())

if not owners:
    st.error("No task owners were found in the uploaded file.")
    st.stop()

selected_owner = st.selectbox(
    "Choose the owner for the personal reports",
    owners,
)

reports = create_reports(
    df,
    selected_owner,
    today,
    deadline,
)

daily_briefing = create_daily_briefing(
    df,
    selected_owner,
    reports,
    today,
)

st.success(
    f"Loaded {len(df)} tasks from {uploaded_file.name}"
)

st.subheader("Daily briefing")
st.code(daily_briefing)

metric_one, metric_two, metric_three = st.columns(3)

metric_one.metric(
    "Overdue tasks",
    int(
        (
            (df["owner"] == selected_owner)
            & df["is_overdue"]
        ).sum()
    ),
)

metric_two.metric(
    "Tasks due today",
    int(
        (
            (df["owner"] == selected_owner)
            & df["is_due_today"]
        ).sum()
    ),
)

metric_three.metric(
    "Blocked tasks",
    int(
        (
            (df["owner"] == selected_owner)
            & df["is_task_blocked"]
        ).sum()
    ),
)

st.subheader("Prioritized action list")
st.dataframe(reports["action_list"], use_container_width=True)

st.download_button(
    "Download action list",
    dataframe_to_csv(reports["action_list"]),
    file_name="action_list.csv",
    mime="text/csv",
)

st.subheader("Other reports")

report_sections = {
    "Upcoming tasks": reports["upcoming_tasks"],
    "Overdue tasks": reports["overdue_tasks"],
    "Project summary": reports["project_summary"],
    "Owner summary": reports["owner_summary"],
    "Dependency watchlist": reports["dependency_watchlist"],
    "Blocked tasks": reports["blocked_tasks"],
    "Data quality summary": reports["data_quality_summary"],
}

for report_name, report_data in report_sections.items():
    with st.expander(report_name):
        st.dataframe(report_data, use_container_width=True)

        download_name = (
            normalize_column_name(report_name)
            + ".csv"
        )

        st.download_button(
            f"Download {report_name}",
            dataframe_to_csv(report_data),
            file_name=download_name,
            mime="text/csv",
            key=report_name,
        )

st.download_button(
    "Download daily briefing",
    daily_briefing,
    file_name="daily_briefing.txt",
    mime="text/plain",
)