import os
import tempfile
import zipfile
from pathlib import Path

import pandas as pd

from executor.automation_executor import automation_executor


def find_file_with_extension(folder, ext):
    for file in os.listdir(folder):
        if file.endswith(ext):
            return os.path.join(folder, file)
    raise FileNotFoundError(f"No {ext} file found in {folder}")


def extract_zip_and_find_git(zip_path):
    temp_dir = tempfile.mkdtemp(prefix="unzipped_git_")
    with zipfile.ZipFile(zip_path, 'r') as zip_ref:
        zip_ref.extractall(temp_dir)

    # Search for .git folder inside extracted contents
    for root, dirs, _ in os.walk(temp_dir):
        if ".git" in dirs:
            return os.path.join(root, ".git")
    raise FileNotFoundError(f"No .git folder found inside {zip_path}")


def read_commits_from_csv(csv_path):
    df = pd.read_csv(csv_path)

    def safe_get(header):
        return str(df[header].iloc[0]).strip() if header in df.columns else ""

    return {
        "baseCommit1": safe_get("QP1 - USER turn commit SHA"),
        "agentTurnCommit1": safe_get("QP1 - AGENT turn commit SHA"),
        "testTurnCommit1": safe_get("QP1 - Test Commit SHA"),
        "baseCommit2": safe_get("QP2 - USER turn commit SHA"),
        "agentTurnCommit2": safe_get("QP2 - AGENT turn commit SHA"),
        "testTurnCommit2": safe_get("QP2 - Test Commit SHA"),
        "baseCommit3": safe_get("QP3 - USER turn commit SHA"),
        "agentTurnCommit3": safe_get("QP3 - AGENT turn commit SHA"),
        "testTurnCommit3": safe_get("QP3 - Test Commit SHA"),
        "runCommand": safe_get("QP1 - New Test Command"),
    }


def review_executor(task_id):
    project_root = Path(__file__).parent.parent
    base_dir = project_root / "input" / f"{task_id}"
    # auto-discover input files
    tar_path = find_file_with_extension(base_dir, ".tar")
    zip_path = find_file_with_extension(base_dir, ".zip")
    csv_path = find_file_with_extension(base_dir, ".csv")

    local_git_path = extract_zip_and_find_git(zip_path)
    commit_data = read_commits_from_csv(csv_path)

    automation_executor(task_id=task_id,
                        docker_tar=tar_path,
                        local_git=local_git_path,
                        input_csv=csv_path,
                        baseCommit1=commit_data["baseCommit1"],
                        agentTurnCommit1=commit_data["agentTurnCommit1"],
                        testTurnCommit1=commit_data["testTurnCommit1"],
                        baseCommit2=commit_data["baseCommit2"],
                        agentTurnCommit2=commit_data["agentTurnCommit2"],
                        testTurnCommit2=commit_data["testTurnCommit2"],
                        baseCommit3=commit_data["baseCommit3"],
                        agentTurnCommit3=commit_data["agentTurnCommit3"],
                        testTurnCommit3=commit_data["testTurnCommit3"],
                        runCommand=commit_data["runCommand"], )
