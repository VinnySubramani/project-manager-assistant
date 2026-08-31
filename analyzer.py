from pathlib import Path
import re
import pandas as pd


# --------------------
# SETTINGS
# --------------------

OWNER = "Sarah"
PROJECT_FOLDER = Path(__file__).parent
INPUT_FILE = PROJECT_FOLDER / "data" / "alternative_tasks.json"
OUTPUT_FOLDER = PROJECT_FOLDER / "output"

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
# HELPER FUNCTIONS
# --------------------

def get_urgency(days_remaining):
    if days_remaining < 0:
        return "Overdue"
    if days_remaining == 0:
        return "Due today"
    if days_remaining <= 2:
        return "Due soon"
    return "Later"


def save_csv(report, filename, report_name):
    file_path = OUTPUT_FOLDER / filename
    report.to_csv(file_path, index=False)
    print(f"Saved {report_name}: {file_path}")


def load_task_data(file_path):
    file_type = file_path.suffix.lower()

    if file_type == ".csv":
        return pd.read_csv(file_path)

    if file_type == ".json":
        return pd.read_json(file_path)

    if file_type in [".xlsx", ".xls"]:
        return pd.read_excel(file_path)

    raise ValueError("Input file must be a CSV, JSON, or Excel file.")


def normalize_column_name(column_name):
    column_name = str(column_name).strip().lower()
    return re.sub(r"[^a-z0-9]+", "_", column_name).strip("_")


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
            "Input file is missing required columns: "
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


# --------------------
# LOAD AND PREPARE DATA
# --------------------

OUTPUT_FOLDER.mkdir(exist_ok=True)

df = load_task_data(INPUT_FILE)
df = standardize_columns(df)
df = standardize_task_values(df)

available_owners = df["owner"].dropna().unique()

if OWNER not in available_owners:
    raise ValueError(
        f"Owner '{OWNER}' was not found. "
        f"Available owners: {', '.join(available_owners)}"
    )

owner_file_name = normalize_column_name(OWNER)

print(f"Loaded {len(df)} tasks from: {INPUT_FILE.name}")

today = pd.Timestamp.today().normalize()
deadline = today + pd.Timedelta(days=2)

df["days_remaining"] = (df["due_date"] - today).dt.days
df["urgency"] = df["days_remaining"].apply(get_urgency)

df["is_unfinished"] = df["status"] != "Completed"
df["is_overdue"] = df["is_unfinished"] & (df["urgency"] == "Overdue")
df["is_due_today"] = df["is_unfinished"] & (df["urgency"] == "Due today")
df["is_due_soon"] = df["is_unfinished"] & (df["urgency"] == "Due soon")

urgency_order = {
    "Overdue": 1,
    "Due today": 2,
    "Due soon": 3,
    "Later": 4,
}

priority_order = {
    "High": 1,
    "Medium": 2,
    "Low": 3,
}

df["urgency_rank"] = df["urgency"].map(urgency_order)
df["priority_rank"] = df["priority"].map(priority_order)

task_status_lookup = df.set_index("task_name")["status"]

df["dependency_task_status"] = df["dependencies"].map(
    task_status_lookup
)

df["is_task_blocked"] = (
    df["dependency_task_status"].notna()
    & (df["dependency_task_status"] != "Completed")
)


# --------------------
# PERSONAL REPORTS
# --------------------

upcoming_tasks = df[
    (df["owner"] == OWNER)
    & df["is_unfinished"]
    & (df["due_date"] >= today)
    & (df["due_date"] <= deadline)
].sort_values("due_date")

print(f"\n{OWNER}'s unfinished tasks due within the next two days:")
print(upcoming_tasks[REPORT_COLUMNS])

save_csv(
    upcoming_tasks[REPORT_COLUMNS],
    f"{owner_file_name}_upcoming_tasks.csv",
    "upcoming-tasks report",
)


overdue_tasks = df[
    (df["owner"] == OWNER)
    & df["is_unfinished"]
    & df["is_overdue"]
].sort_values("due_date")

print(f"\n{OWNER}'s overdue tasks:")
print(overdue_tasks[REPORT_COLUMNS])

save_csv(
    overdue_tasks[REPORT_COLUMNS],
    f"{owner_file_name}_overdue_tasks.csv",
    "overdue-tasks report",
)


action_list = df[
    (df["owner"] == OWNER)
    & df["is_unfinished"]
].sort_values(
    ["urgency_rank", "priority_rank", "due_date"]
)

action_list_report = action_list[
    [
        "task_name",
        "priority",
        "urgency",
        "due_date",
        "days_remaining",
        "dependencies",
    ]
]

print(f"\n{OWNER}'s prioritized action list:")
print(action_list_report)

save_csv(
    action_list_report,
    f"{owner_file_name}_action_list.csv",
    "action-list report",
)


# --------------------
# PROJECT REPORTS
# --------------------

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

print("\nProject summary:")
print(project_summary)

save_csv(
    project_summary,
    "project_summary.csv",
    "project summary",
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

print("\nWorkload by owner:")
print(owner_summary)

save_csv(
    owner_summary,
    "owner_summary.csv",
    "owner summary",
)


dependency_watchlist = df[
    df["is_unfinished"]
    & df["dependencies"].notna()
].sort_values(
    ["urgency_rank", "due_date"]
)

dependency_report = dependency_watchlist[
    [
        "task_name",
        "owner",
        "priority",
        "urgency",
        "due_date",
        "dependencies",
    ]
]

print("\nTasks with dependencies:")
print(dependency_report)

save_csv(
    dependency_report,
    "dependency_watchlist.csv",
    "dependency watchlist",
)


blocked_tasks = df[
    df["is_unfinished"]
    & df["is_task_blocked"]
].sort_values(
    ["urgency_rank", "due_date"]
)

blocked_task_report = blocked_tasks[
    [
        "task_name",
        "owner",
        "urgency",
        "due_date",
        "dependencies",
        "dependency_task_status",
    ]
]

print("\nTasks blocked by another unfinished task:")
print(blocked_task_report)

save_csv(
    blocked_task_report,
    "blocked_tasks.csv",
    "blocked-tasks report",
)


# --------------------
# DATA QUALITY
# --------------------

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

print("\nData quality summary:")
print(data_quality_summary)

save_csv(
    data_quality_summary,
    "data_quality_summary.csv",
    "data-quality summary",
)


# --------------------
# DAILY BRIEFING
# --------------------

owner_overdue_count = (
    (df["owner"] == OWNER)
    & df["is_overdue"]
).sum()

owner_due_today_count = (
    (df["owner"] == OWNER)
    & df["is_due_today"]
).sum()

owner_blocked_count = (
    (df["owner"] == OWNER)
    & df["is_task_blocked"]
).sum()

briefing_lines = [
    f"{OWNER.upper()} DAILY PROJECT BRIEFING",
    f"Date: {today.date()}",
    "",
    f"Overdue tasks: {owner_overdue_count}",
    f"Tasks due today: {owner_due_today_count}",
    f"Tasks blocked by another open task: {owner_blocked_count}",
    "",
    "Top priorities:",
]

blocked_task_names = set(blocked_tasks["task_name"])

for _, task in action_list.head(3).iterrows():
    blocked_note = ""

    if task["task_name"] in blocked_task_names:
        blocked_note = f", blocked by: {task['dependencies']}"

    briefing_lines.append(
        f"- {task['task_name']} "
        f"({task['priority']} priority, {task['urgency']}, "
        f"due {task['due_date'].date()}{blocked_note})"
    )

briefing_file = OUTPUT_FOLDER / f"{owner_file_name}_daily_briefing.txt"
briefing_file.write_text("\n".join(briefing_lines))

print(f"\nSaved daily briefing: {briefing_file}")