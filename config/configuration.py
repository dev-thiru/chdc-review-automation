# config.py
"""
Configuration file for CHDC Review Automation
"""

# Google Sheets Configuration
SHEET_ID = "1e3_JmLRWZVma5QxdPEqcRR3LI5SZcV_bYo7I4RXCxas"
CONFIG_SHEET_NAME = "533003217"
REVIEW_SHEET_NAME = "483459467"
CONFIGURATION_COL = ["LT_User_Token"]
GEMINI_TOKEN = ["LLM_API_Token"]


# Directory Configuration
DOWNLOAD_DIR = "batches"
INPUT_DIR = "input"

# API Configuration
LABELING_TOOL_BASE_URL = "https://labeling-g.turing.com"
BATCH_DOWNLOAD_URL_TEMPLATE = f"{LABELING_TOOL_BASE_URL}/api/batches/{{batch_id}}/download-form-json?versionsFilter=false&reviewsFilter=true&deliveryInfoFilter=true&publicImageLinkFilter=false"
CONVERSATION_VIEW_URL_TEMPLATE = f"{LABELING_TOOL_BASE_URL}/conversations/{{task_id}}/view"
CONVERSATION_API_URL_TEMPLATE = f"{LABELING_TOOL_BASE_URL}/api/conversations/{{conversation_id}}"

# API Join Parameters
API_JOIN_PARAMS = [
    "project||id,name,status,projectType,supportsFunctionCalling,supportsWorkflows,supportsMultipleFilesPerTask,jibbleActivity,instructionsLink,readonly,averageHandleTimeMinutes",
    "batch||id,name,status,projectId,jibbleActivity,maxClaimGoldenTaskAllowed,averageHandleTimeMinutes",
    "seed||metadata,turingMetadata",
    "labels||id,labelId",
    "project.projectFormStages"
]

# Expected CSV Column Order
COLUMNS_ORDER = [
    'Task_id',
    'Labeling tool link',
    'Task link',
    'Status',
    'Completed at',
    'Batch',
    'Project',
    'Instance ID',
    'Repo',
    'Language',
    'PR Link',
    'Target Diff',
    'Path to Docker .tar',
    'Base Commit',
    'Test Command',
    'Hidden Test Patch',
    'Google API Verification Screenshot',
    'OpenAI Base URL Override Verification Screenshot',
    'Cursor Logs Link',
    'Cursor Version Screenshot',
    'Start Date and Time (Pacific Time -  MM/DD/YYYY HH:MM:SS 24 hours format)',
    '.git file link',
    'QP1 - Screenshot of Cursor Screen before User Query',
    'QP1 - Query Point',
    'QP1 - Is this a fresh Query Point?',
    'QP1 - Is this an "Interesting" Query Point?',
    'QP1 - Explanation - Is this an "Interesting" Query Point?',
    'QP1 - Is "Recalling" required?',
    'QP1 - Explanation - Is "Recalling" required?',
    'QP1 - Tier',
    'QP1 - Justification - Tier',
    'QP1 - How well did Agent understand the query?',
    'QP1 - Explanation - How well did Agent understand the query?',
    'QP1 - Code quality?',
    'QP1 - Explanation - Code quality',
    'QP1 - USER turn commit SHA',
    'QP1 - AGENT turn commit SHA',
    'QP1 - Test Commit SHA',
    'QP1 - New Test Command',
    'QP1 - Is there human edit in the Agent Turn Commit?',
    'QP1 - Test Status',
    'QP1 - Test Execution Screenshot - Before Query Point',
    'QP1 - Test Execution Screenshot - After Query Point',
    'QP1 - Screenshot of Cursor Usage Log',
    'QP1 - Code Edit Patch',
    'QP1 - Test Edit Patch',
    'QP2 - Screenshot of Cursor Screen before User Query',
    'QP2 - Query Point',
    'QP2 - Is this a fresh Query Point?',
    'QP2 - Is this an "Interesting" Query Point?',
    'QP2 - Explanation - Is this an "Interesting" Query Point?',
    'QP2 - Is "Recalling" required?',
    'QP2 - Explanation - Is "Recalling" required?',
    'QP2 - Tier',
    'QP2 - Justification - Tier',
    'QP2 - How well did Agent understand the query?',
    'QP2 - Explanation - How well did Agent understand the query?',
    'QP2 - Code quality?',
    'QP2 - Explanation - Code quality',
    'QP2 - USER turn commit SHA',
    'QP2 - AGENT turn commit SHA',
    'QP2 - Test Commit SHA',
    'QP2 - New Test Command',
    'QP2 - Is there human edit in the Agent Turn Commit?',
    'QP2 - Test Status',
    'QP2 - Test Execution Screenshot - Before Query Point',
    'QP2 - Test Execution Screenshot - After Query Point',
    'QP2 - Screenshot of Cursor Usage Log',
    'QP2 - Code Edit Patch',
    'QP2 - Test Edit Patch',
    'QP3 - Screenshot of Cursor Screen before User Query',
    'QP3 - Query Point',
    'QP3 - Is this a fresh Query Point?',
    'QP3 - Is this an "Interesting" Query Point?',
    'QP3 - Explanation - Is this an "Interesting" Query Point?',
    'QP3 - Is "Recalling" required?',
    'QP3 - Explanation - Is "Recalling" required?',
    'QP3 - Tier',
    'QP3 - Justification - Tier',
    'QP3 - How well did Agent understand the query?',
    'QP3 - Explanation - How well did Agent understand the query?',
    'QP3 - Code quality?',
    'QP3 - Explanation - Code quality',
    'QP3 - USER turn commit SHA',
    'QP3 - AGENT turn commit SHA',
    'QP3 - Test Commit SHA',
    'QP3 - New Test Command',
    'QP3 - Is there human edit in the Agent Turn Commit?',
    'QP3 - Test Status',
    'QP3 - Test Execution Screenshot - Before Query Point',
    'QP3 - Test Execution Screenshot - After Query Point',
    'QP3 - Screenshot of Cursor Usage Log',
    'QP3 - Code Edit Patch',
    'QP3 - Test Edit Patch',
    'Review Checklist Link',
    'Prompts for which the agent changes are rejected'
]

def find_col(df, possible_names):
    """Return actual column name in df matching any of possible_names (case-insensitive)."""
    if df is None or df.columns is None:
        return None
    m = {c.lower(): c for c in df.columns}
    for n in possible_names:
        if n and n.lower() in m:
            return m[n.lower()]
    return None