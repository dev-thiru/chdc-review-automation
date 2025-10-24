# CHDC Review Automation

A Python-based tool for generating task reviews using Docker containerization and LLM evaluation.

## Prerequisites

Before you begin, ensure you have the following installed:

- **Python 3** (modern version recommended)
- **Docker Desktop** (installed and running)

## Installation

### 1. Set Up Python Virtual Environment

Install all required dependencies from the `requirements.txt` file:

```bash
# Create a virtual environment (optional but recommended)
python3 -m venv venv

# Activate the virtual environment
# On Linux/Mac:
source venv/bin/activate
# On Windows:
venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

### 2. Start Docker Desktop

Ensure Docker Desktop is running before executing the script.

## Setup

### Prepare Input Files

1. **Download the required files:**
    - `.tar` file
    - Instance ID `.zip` folder , download the complete folder of that specific task 

2. **Create a folder structure:**
    - Create a folder named with your task ID
    - Place both the `.tar` file and `.zip` file inside this folder

3. **Move to input directory:**
    - Place the task folder in the `/input` directory

**Example structure:**
```
/input
  └── 858201
      ├── docker_image.tar
      └── instance_id.zip
```

## Usage

Run the script with the task ID flag:

```bash
python chdc_review_generator.py --task_id=858201
```

Replace `858201` with your specific task ID.

## Output

The execution results will be generated in the `outputs` folder, containing:

- **Patch folder** - Generated code patches
- **Docker execution log** - Logs from Docker container execution
- **LLM evaluation log** - Logs from the LLM evaluation process

**Output structure:**
```
/outputs
  └── 858201
      ├── patch/
      ├── 858201_output_log.txt
      └── llm_evaluation.csv
```

## Functionality Verified


This script performs the following verification steps:

- **Environment Setup**: Validates the repository structure and Git configuration at `/app`
- **Commit Chain Verification**: Traces and documents the ancestry of up to 5 commits for each query point (QP1, QP2, QP3)
- **Patch Generation**: Creates separate code and test patches for each query point set
- **Test-Only Validation**: Applies test patches independently and runs test commands to verify test integrity
- **Code + Test Integration**: Applies both code and test patches sequentially to validate the complete implementation
- **File Change Tracking**: Logs all modified, added, deleted, renamed, or copied files for each commit
- **PII Detection**: Records author and committer information (name and email) for compliance and audit purposes
- **Automated Test Execution**: Runs configurable test commands after each patch application phase

## Troubleshooting

- **Docker not running:** Ensure Docker Desktop is started before running the script
- **Missing dependencies:** Run `pip install -r requirements.txt` again
- **File not found errors:** Verify the folder structure in `/input` matches the expected format

## Support

For issues or questions, please refer to the project documentation or contact the development team.