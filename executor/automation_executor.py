import json
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Dict

import pandas as pd
import requests

import config.configuration as configuration


def run_cmd(cmd, capture_output=True, check=True, env=None):
    """Run a shell command and return stdout (decoded) and stderr."""
    completed = subprocess.run(
        cmd,
        stdout=subprocess.PIPE if capture_output else None,
        stderr=subprocess.PIPE if capture_output else None,
        text=True,
        check=False,
        env=env,
    )
    if check and completed.returncode != 0:
        raise RuntimeError(
            f"Command failed: {' '.join(cmd)}\nexit={completed.returncode}\nstdout={completed.stdout}\nstderr={completed.stderr}"
        )
    return completed


def show_loading(message="Loading Docker image", interval=2):
    """Display a loading message every few seconds until stopped."""
    stop_event = threading.Event()

    def loader():
        dots = 0
        while not stop_event.is_set():
            print(f"\r{message}{'.' * (dots % 4)}", end='', flush=True)
            dots += 1
            time.sleep(interval)
        print("\r", end='')  # clear line when done

    thread = threading.Thread(target=loader)
    thread.start()
    return stop_event


# --------------------------- Operation 1: Docker Execution ---------------------------

def operation_docker(
        task_id: str,
        docker_tar: str,
        local_git_folder: str,
        entrypoint_args: Dict[str, str],
        run_command: str,
        logs_outpath: str,
        keep_container: bool = False,
) -> Dict[str, Any]:
    """
    Performs docker load, run, copy .git into container, execute entrypoint,
    and capture logs. Separates logs into multiple files based on section markers.
    """
    out = {"container_id": None, "log_file_path": None, "success": False, "error": None}

    try:
        # ----------------------------
        # 1) Load Docker image
        # ----------------------------
        stop_event = show_loading("[docker] Loading Docker image", interval=2)
        try:
            print(f"[docker] Loading image from: {docker_tar}")
            p = subprocess.run(["docker", "load", "-i", docker_tar], capture_output=True, text=True, check=True)
        finally:
            # Stop loading animation
            stop_event.set()

        stdout = p.stdout or ""
        print("[docker] load output:\n", stdout)

        # Extract image reference
        image_ref = None
        for line in stdout.splitlines():
            if "Loaded image:" in line:
                image_ref = line.split("Loaded image:", 1)[1].strip()
                break
        if not image_ref:
            # fallback: use digest or most recent image
            for line in stdout.splitlines():
                if line.startswith("sha256:"):
                    image_ref = line.strip()
                    break
        if not image_ref:
            images = subprocess.run(
                ["docker", "images", "--format", "{{.Repository}}:{{.Tag}} {{.CreatedAt}}"],
                capture_output=True, text=True
            )
            for l in (images.stdout or "").splitlines():
                if "<none>" not in l:
                    image_ref = l.split()[0]
                    break
        if not image_ref:
            raise RuntimeError("Could not determine image reference after docker load")

        print(f"[docker] Image reference resolved to: {image_ref}")

        # ----------------------------
        # 2) Run container detached
        # ----------------------------
        completed = subprocess.run(["docker", "run", "-d", image_ref, "tail", "-f", "/dev/null"],
                                   capture_output=True, text=True, check=True)
        container_id = completed.stdout.strip().splitlines()[0]
        if not container_id:
            raise RuntimeError("docker run did not return a container id")
        out["container_id"] = container_id
        print(f"[docker] Container started: {container_id}")

        # ----------------------------
        # 3) Copy .git and entrypoint.sh
        # ----------------------------
        src = Path(local_git_folder)
        if src.is_dir() and src.name == ".git":
            src_path = str(src)
        elif src.is_dir() and (src / ".git").exists():
            src_path = str(src / ".git")
        else:
            raise RuntimeError(f"Local git folder not found or invalid: {local_git_folder}")

        project_root = Path(__file__).parent.parent
        entrypoint_src = str(project_root / "entrypoint" / "entrypoint.sh")

        subprocess.run(["docker", "cp", src_path, f"{container_id}:/app/"], check=True)
        subprocess.run(["docker", "cp", entrypoint_src, f"{container_id}:/app/entrypoint.sh"], check=True)

        # ----------------------------
        # 4) Execute entrypoint.sh
        # ----------------------------
        env_vars = entrypoint_args.copy()
        env_vars["runCommand"] = run_command

        exec_cmd = ["docker", "exec", "-i"]
        for k, v in env_vars.items():
            exec_cmd += ["-e", f"{k}={v}"]

        bash_command = (
            "set -euo pipefail;"
            "echo '--- Checking entrypoint.sh ---';"
            "if [ ! -f /app/entrypoint.sh ]; then echo 'Error: entrypoint.sh not found' >&2; exit 128; fi;"
            "sed -i 's/\\r$//' /app/entrypoint.sh;"
            "chmod +x /app/entrypoint.sh;"
            "bash /app/entrypoint.sh"
        )
        exec_cmd += [container_id, "/bin/bash", "-lc", bash_command]

        logs_path = Path(logs_outpath)
        logs_path.parent.mkdir(parents=True, exist_ok=True)

        # Section markers
        SECTIONS = {
            "commit_chain": ("COMMIT CHAIN HISTORY", "END OF COMMIT CHAIN HISTORY"),
            "file_changes": ("FILE CHANGES AND PII SUMMARY", "END OF FILE CHANGES AND PII SUMMARY"),
            "qp1_execution": ("QUERY POINT SET 1 - TEST COMMIT CHECK", None),
            "qp2_execution": ("QUERY POINT SET 2 - TEST COMMIT CHECK", None),
            "qp3_execution": ("QUERY POINT SET 3 - TEST COMMIT CHECK", None),
        }

        # Buffers
        buffers = {k: [] for k in SECTIONS}

        # Active section tracker
        active_section = None

        with open(logs_path, "w", encoding="utf-8") as lf:
            proc = subprocess.Popen(
                exec_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace"
            )

            for line in proc.stdout:
                line = line.replace('â""', '└').replace('â"€', '─').replace('Ã¢Å"â€¦', '✅')
                line = line.replace('â€â€', '  ').replace('â€â‚¬', '─')
                lf.write(line)
                lf.flush()
                stripped_line = line.rstrip()

                # Section detection
                for key, (start_marker, end_marker) in SECTIONS.items():
                    if start_marker in line:
                        active_section = key
                        buffers[key].append(stripped_line)
                        break
                    if end_marker and end_marker in line and active_section == key:
                        buffers[key].append(stripped_line)
                        active_section = None
                        break
                else:
                    if active_section:
                        buffers[active_section].append(stripped_line)

            ret = proc.wait()
            if ret != 0:
                raise RuntimeError(f"entrypoint.sh returned non-zero exit: {ret}")

        # Write individual section logs
        log_files = {}
        for key in SECTIONS:
            buf = buffers[key]
            if buf:
                file_path = logs_path.parent / "execution" / f"{key}.log"
                file_path.parent.mkdir(parents=True, exist_ok=True)
                with open(file_path, "w", encoding="utf-8") as f:
                    f.write("\n".join(buf))
                log_files[key] = str(file_path)
                print(f"✅ Created: {file_path}")
            else:
                log_files[key] = None

        out["log_file_path"] = str(logs_path)
        out["log_files"] = {"main": str(logs_path), **log_files}
        out["success"] = True

        # ----------------------------
        # 5) Copy patch folder (if exists)
        # ----------------------------
        patch_dest = project_root / "output" / task_id / "patch"
        patch_dest.mkdir(parents=True, exist_ok=True)
        patch_dest_str = str(patch_dest)

        check_cmd = ["docker", "exec", container_id, "test", "-d", "/app/patch"]
        check_result = subprocess.run(check_cmd, check=False)
        if check_result.returncode == 0:
            subprocess.run(["docker", "cp", f"{container_id}:/app/patch/.", patch_dest_str], check=True)
            print(f"[docker] Patch copied to {patch_dest_str}")
        else:
            print("[docker] /app/patch directory not found, skipping copy")

        # ----------------------------
        # 6) Cleanup
        # ----------------------------
        if not keep_container:
            subprocess.run(["docker", "stop", container_id], check=False)
            subprocess.run(["docker", "rm", container_id], check=False)
            subprocess.run(["docker", "rmi", image_ref], check=False)
            print("[docker] Container and image removed")

        print(f"[docker] Completed operation, logs written to: {logs_path}")

    except Exception as e:
        out["error"] = str(e)
        print("[docker] ERROR:", e)
        if out["container_id"] and not keep_container:
            try:
                subprocess.run(["docker", "stop", out["container_id"]], check=False)
                subprocess.run(["docker", "rm", out["container_id"]], check=False)
            except:
                pass

    return out


# --------------------------- Operation 2: Gemini LLM Review ---------------------------

def call_gemini(prompt: str, token: str, endpoint: str, timeout: int = 60, temperature: float = 0.1) -> str:
    """
    Gemini-compatible LLM call based on the provided Apps Script reference.

    Args:
        prompt (str): The input text prompt to send to the Gemini model.
        token (str): The Gemini API key (Bearer token).
        endpoint (str): The full Gemini API endpoint (without the key if using Authorization header).
        timeout (int): Request timeout in seconds.
        temperature (float): Sampling temperature for generation.
    """

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    # Match the structure of the nlData object from Apps Script
    payload = {
        "contents": [
            {
                "parts": [
                    {"text": prompt}
                ]
            }
        ],
        "generationConfig": {
            "temperature": temperature
        },
        "safetySettings": [
            {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
        ]
    }

    try:
        resp = requests.post(endpoint, headers=headers, json=payload, timeout=timeout)
        resp.raise_for_status()
        data = resp.json()

        # Parse the Gemini-style response
        if "candidates" in data:
            c = data["candidates"][0]
            if "content" in c and "parts" in c["content"] and c["content"]["parts"]:
                return c["content"]["parts"][0].get("text", "")
        # Fallback if structure changes
        return json.dumps(data, indent=2)

    except Exception as e:
        return f"__ERROR__ calling Gemini API: {e}"


def get_gemini_api_token():
    """Fetch llm api token from Google Sheets config."""
    configuration_df = pd.DataFrame()

    try:
        url = f"https://docs.google.com/spreadsheets/d/{configuration.SHEET_ID}/export?gid={configuration.CONFIG_SHEET_NAME}&format=csv"
        configuration_df = pd.read_csv(url)
    except Exception as e:
        print(f"⚠️ Unexpected error while loading data from configuration sheet: {e}")
        return None

    configuration_df.columns = [c.strip() for c in configuration_df.columns]
    config_col = configuration.find_col(configuration_df, configuration.GEMINI_TOKEN)

    if config_col is None:
        print("⚠️ Configuration column LLM_API_Token not found in sheet")
        return None

    return configuration_df[config_col].iloc[0]


def operation_gemini_evaluate(
        input_csv: str,
        out_checklist_path: Path,
) -> Dict[str, Any]:
    """
    For each row in the checklist CSV, builds a prompt combining the system prompt,
    checkpoint text, and corresponding input data. Calls Gemini API for evaluation
    and updates the 'Followed' and 'LLM Comments' columns.

    Args:
        input_csv_path: Path to the CSV containing input data/evidence
        checklist_csv_path: Path to the review checklist CSV
        output_dir: Directory to save the output CSV
        gemini_api_key: Gemini API key for authentication

    Returns:
        Dictionary with success status, output path, and any errors
    """
    result = {"success": False, "error": None, "out_path": None}

    try:
        print(f"[llm] Reading Review Checklist CSV")
        review_checklist_df = pd.DataFrame()
        gemini_api_key = get_gemini_api_token()
        if gemini_api_key is None:
            print("[llm] Gemini API key not found, skipping llm execution.")
            return

        try:
            url = f"https://docs.google.com/spreadsheets/d/{configuration.SHEET_ID}/export?gid={configuration.REVIEW_SHEET_NAME}&format=csv"
            review_checklist_df = pd.read_csv(url)
        except Exception as e:
            print(f"⚠️ Unexpected error while loading data from Review Checklist sheet: {e}")

        print(f"[llm] Reading Input CSV: {input_csv}")
        input_df = pd.read_csv(input_csv)

        # Initialize columns if they don't exist
        if 'Followed' not in review_checklist_df.columns:
            review_checklist_df['Followed'] = ''
        if 'LLM Comments' not in review_checklist_df.columns:
            review_checklist_df['LLM Comments'] = ''

        # Process each row
        total_rows = len(review_checklist_df)
        print(f"[llm] Processing {total_rows} checklist items...")

        for idx, row in review_checklist_df.iterrows():
            print(f"[llm] Evaluating row {idx + 1}/{total_rows}")

            # Extract checkpoint information
            topic = str(row.get('Topics', '')) if not pd.isna(row.get('Topics')) else ''
            checkpoint = str(row.get('CheckPoints', '')) if not pd.isna(row.get('CheckPoints')) else ''
            input_field = str(row.get('Input', '')) if not pd.isna(row.get('Input')) else ''
            input_type = str(row.get('Input Type', '')) if not pd.isna(row.get('Input Type')) else ''
            system_prompt = str(row.get('System Prompt', '')) if not pd.isna(row.get('System Prompt')) else ''

            # Skip rows without checkpoints or system prompts
            if not checkpoint.strip() or not system_prompt.strip():
                print(f"[llm] Skipping row {idx} - missing checkpoint or system prompt")
                continue
            input_data = "No specific input data provided"
            if input_type.strip() and input_type.strip() == 'csv':
                input_data = input_df.iloc[0].get(input_field.strip(), None)

            # Build checkpoint text
            checkpoint_text = f"Topic: {topic}\nCheckpoint: {checkpoint}"
            # Get corresponding input data

            if input_field.strip() and input_field != 'NA':
                # Try to find matching data in input CSV
                if idx < len(input_df):
                    input_row = input_df.iloc[idx]
                    input_data = f"Input Field Required: {input_field}\n"
                    input_data += "\n".join([f"{col}: {val}" for col, val in input_row.items()
                                         if not pd.isna(val)])
                else:
                    input_data = f"Input Field Required: {input_field}\n(No corresponding input row found)"

            # Call Gemini API
            evaluation = call_gemini_with_prompt(
                system_prompt=system_prompt,
                checkpoint_text=checkpoint_text,
                input_data=input_data,
                api_key=gemini_api_key
                )
            print(evaluation)
            # Update the dataframe
            review_checklist_df.at[idx, 'Followed'] = evaluation['followed']
            review_checklist_df.at[idx, 'LLM Comments'] = evaluation['comment']

            print(f"[llm] Row {idx}: {evaluation['followed']} - {evaluation['comment'][:50]}...")
            # Rate limiting - be polite to the API
            time.sleep(1)


        columns_to_remove = ["System Prompt", "Input Type", "Input"]
        review_checklist_df = review_checklist_df.drop(columns=columns_to_remove, errors='ignore')

        # Save the updated CSV
        out_checklist_path.mkdir(parents=True, exist_ok=True)
        output_path = out_checklist_path / "llm" / "llm_evaluation.csv"
        output_path.parent.mkdir(parents=True, exist_ok=True)
        review_checklist_df.to_csv(output_path, index=False)

        result["success"] = True
        result["out_path"] = str(output_path)
        print(f"[llm] ✅ Successfully wrote evaluated checklist to: {output_path}")

    except Exception as e:
        result["error"] = str(e)
        print(f"[llm] ❌ ERROR: {e}")
        import traceback
        traceback.print_exc()

        return result


def call_gemini_with_prompt(system_prompt: str, checkpoint_text: str, input_data: str, api_key: str
                            ) -> Dict[str, str]:
    """
    Calls Gemini API with system prompt and checkpoint information.
    Returns a dict with 'followed' (Yes/No) and 'comment' (evaluation text).

    Args:
        system_prompt: The system prompt from the CSV
        checkpoint_text: The checkpoint description
        input_data: Input/evidence data
        api_key: Gemini API key
    """
    try:
        gemini_api_endpoint: str = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash-exp:generateContent?key="
        # Build the full endpoint URL
        full_endpoint = f"{gemini_api_endpoint}{api_key}"

        # Build the evaluation prompt
        evaluation_prompt = f"""
{system_prompt}

Checkpoint to evaluate:
{checkpoint_text}

Input/Evidence provided:
{input_data}

Based on the checkpoint requirements and the provided evidence, evaluate whether this checkpoint was followed correctly.

Respond in this exact format:
FOLLOWED: [Yes/No]
COMMENT: [Brief explanation of your evaluation in 1-2 sentences]
"""

        print(f"Calling with prompt length: {len(evaluation_prompt)} characters")

        nl_data = {
            'contents': [{
                'parts': [
                    {'text': evaluation_prompt}
                ]
            }],
            'generationConfig': {
                'temperature': 0.1,
            },
            'safetySettings': [
                {
                    "category": "HARM_CATEGORY_HATE_SPEECH",
                    "threshold": "BLOCK_NONE"
                },
                {
                    "category": "HARM_CATEGORY_SEXUALLY_EXPLICIT",
                    "threshold": "BLOCK_NONE"
                },
                {
                    "category": "HARM_CATEGORY_DANGEROUS_CONTENT",
                    "threshold": "BLOCK_NONE"
                },
                {
                    "category": "HARM_CATEGORY_HARASSMENT",
                    "threshold": "BLOCK_NONE"
                }
            ]
        }

        # Prepare request headers
        headers = {
            'Content-Type': 'application/json'
        }

        # Make the API call
        response = requests.post(
            full_endpoint,
            headers=headers,
            data=json.dumps(nl_data),
            timeout=60
        )

        # Check if request was successful
        response.raise_for_status()

        # Parse the JSON response
        json_data = response.json()

        # Extract response text
        response_text = ''
        if 'candidates' in json_data:
            response_text = json_data['candidates'][0]['content']['parts'][0]['text']
        else:
            return {
                "followed": "No",
                "comment": "No candidates in API response"
            }

        # Parse the response
        followed = "No"
        comment = "Unable to parse LLM response"

        lines = response_text.strip().split('\n')
        for line in lines:
            line = line.strip()
            if line.startswith('FOLLOWED:'):
                followed_value = line.replace('FOLLOWED:', '').strip()
                # Normalize to Yes/No
                if followed_value.lower() in ['yes', 'y', 'true', 'pass']:
                    followed = "Yes"
                else:
                    followed = "No"
            elif line.startswith('COMMENT:'):
                comment = line.replace('COMMENT:', '').strip()

        return {"followed": followed, "comment": comment}

    except requests.exceptions.RequestException as e:
        return {
            "followed": "No",
            "comment": f"API request error: {str(e)}"
        }
    except KeyError as e:
        return {
            "followed": "No",
            "comment": f"Error parsing API response: {str(e)}"
        }
    except Exception as e:
        return {
            "followed": "No",
            "comment": f"Error during evaluation: {str(e)}"
        }


# --------------------------- Overall Review ---------------------------

def orchestrate(args):
    project_root = Path(__file__).parent.parent

    # Path to entrypoint.sh
    logs_dir = project_root / "output" / args.task_id

    # Prepare entrypoint args - read commit vars from args (they may be blank strings)
    entrypoint_args = {
        "baseCommit1": args.baseCommit1 or "",
        "agentTurnCommit1": args.agentTurnCommit1 or "",
        "testTurnCommit1": args.testTurnCommit1 or "",
        "baseCommit2": args.baseCommit2 or "",
        "agentTurnCommit2": args.agentTurnCommit2 or "",
        "testTurnCommit2": args.testTurnCommit2 or "",
        "baseCommit3": args.baseCommit3 or "",
        "agentTurnCommit3": args.agentTurnCommit3 or "",
        "testTurnCommit3": args.testTurnCommit3 or "",
    }

    project_root = Path(__file__).parent.parent
    docker_log_path = logs_dir / f"{args.task_id}_overall_log.txt"
    checklist_out_xlsx = logs_dir

    docker_result = {}
    llm_result = {}

    # Threads
    def t_docker():
        nonlocal docker_result
        docker_result = operation_docker(
            task_id=args.task_id,
            docker_tar=args.docker_tar,
            local_git_folder=args.local_git,
            entrypoint_args=entrypoint_args,
            run_command=args.runCommand or "",
            logs_outpath=docker_log_path,
            keep_container=False,
        )

    def t_llm():
        nonlocal llm_result
        llm_result = operation_gemini_evaluate(
            input_csv=args.input_csv,
            out_checklist_path=checklist_out_xlsx,
        )

    th1 = threading.Thread(target=t_docker, name="docker-thread")
    th2 = threading.Thread(target=t_llm, name="llm-thread")

    print("[main] Starting parallel operations...")
    th1.start()
    th2.start()

    th1.join()
    th2.join()

    # Print summary
    summary = {
        "docker": docker_result,
        "llm": llm_result,
    }
    return summary


def automation_executor(
        task_id,
        docker_tar,
        local_git,
        input_csv,
        baseCommit1="",
        agentTurnCommit1="",
        testTurnCommit1="",
        baseCommit2="",
        agentTurnCommit2="",
        testTurnCommit2="",
        baseCommit3="",
        agentTurnCommit3="",
        testTurnCommit3="",
        runCommand="",
):
    """Direct programmatic entrypoint for automation_executor."""
    from types import SimpleNamespace

    args = SimpleNamespace(
        task_id=task_id,
        docker_tar=docker_tar,
        local_git=local_git,
        input_csv=input_csv,
        baseCommit1=baseCommit1,
        agentTurnCommit1=agentTurnCommit1,
        testTurnCommit1=testTurnCommit1,
        baseCommit2=baseCommit2,
        agentTurnCommit2=agentTurnCommit2,
        testTurnCommit2=testTurnCommit2,
        baseCommit3=baseCommit3,
        agentTurnCommit3=agentTurnCommit3,
        testTurnCommit3=testTurnCommit3,
        runCommand=runCommand,
        output=None,
    )

    # Directly call orchestrate()
    return orchestrate(args)
