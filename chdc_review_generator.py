import argparse
import json
import os
from pathlib import Path

import pandas as pd
import requests

import config.configuration as configuration
from executor.invoke import review_executor


def get_auth_token():
    """Fetch authentication token from Google Sheets config."""
    configuration_df = pd.DataFrame()

    try:
        url = f"https://docs.google.com/spreadsheets/d/{configuration.SHEET_ID}/export?gid={configuration.CONFIG_SHEET_NAME}&format=csv"
        configuration_df = pd.read_csv(url)
    except Exception as e:
        print(f"⚠️ Unexpected error while loading data from sheet: {e}")
        return None

    configuration_df.columns = [c.strip() for c in configuration_df.columns]
    config_col = configuration.find_col(configuration_df, configuration.CONFIGURATION_COL)

    if config_col is None:
        print("⚠️ Configuration column not found in sheet")
        return None

    return configuration_df[config_col].iloc[0]


def get_headers(token):
    """Generate request headers with authentication token."""
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }


def download_batch(batch_id, headers):
    """Download batch data from labeling tool."""
    batch_url = configuration.BATCH_DOWNLOAD_URL_TEMPLATE.format(batch_id=batch_id)
    batch_response = requests.get(batch_url, headers=headers)

    if batch_response.status_code == 200:
        os.makedirs(configuration.DOWNLOAD_DIR, exist_ok=True)
        filename = f"{configuration.DOWNLOAD_DIR}/batch_{batch_id}.json"
        with open(filename, 'wb') as f:
            f.write(batch_response.content)
    else:
        print(f"Failed to download batch {batch_id}. Status code: {batch_response.status_code}")


def make_input_csv(colab_link, conversation_id, batch_json):
    """Create input CSV from batch JSON data."""
    with open(batch_json, 'r', encoding="utf8") as file:
        try:
            combined_data = json.load(file)
        except json.JSONDecodeError:
            print(f"Error decoding JSON from file: {batch_json}")
            return

    df_row = []

    for sft_obj in combined_data['sft']:
        if sft_obj["colabLink"] == colab_link:
            # Initialize extracted_form_data with all expected columns set to None
            extracted_form_data = {col: None for col in configuration.COLUMNS_ORDER}

            # Populate with SFT object data
            extracted_form_data["Task_id"] = sft_obj.get('id')
            extracted_form_data["Labeling tool link"] = (
                configuration.CONVERSATION_VIEW_URL_TEMPLATE.format(task_id=sft_obj.get('id'))
                if sft_obj.get('id') else None
            )
            extracted_form_data["Task link"] = colab_link
            extracted_form_data["Status"] = sft_obj.get('status')
            extracted_form_data["Completed at"] = sft_obj.get('completedAt')

            # Handle 'Batch' and 'Project' as dictionaries
            batch_info = sft_obj.get('batch')
            if isinstance(batch_info, dict):
                extracted_form_data["Batch"] = batch_info.get('name')
            else:
                extracted_form_data["Batch"] = batch_info

            project_info = sft_obj.get('project')
            if isinstance(project_info, dict):
                extracted_form_data["Project"] = project_info.get('name')
            else:
                extracted_form_data["Project"] = project_info

            # Extract metadata
            metadata = sft_obj.get('metadata', {})
            extracted_form_data['Instance ID'] = metadata.get('Instance ID')
            extracted_form_data['Repo'] = metadata.get('Repo')
            extracted_form_data['Language'] = metadata.get('Language')
            extracted_form_data['PR Link'] = metadata.get('PR Link')
            extracted_form_data['Target Diff'] = metadata.get('Target Diff')
            extracted_form_data['Path to Docker .tar'] = metadata.get('Path to Docker .tar')
            extracted_form_data['Base Commit'] = metadata.get('Base Commit')
            extracted_form_data['Test Command'] = metadata.get('Test Command')
            extracted_form_data['Hidden Test Patch'] = metadata.get('Hidden Test')

            # Find and process form data
            found_form_data = None
            for form_entry in combined_data.get('form', []):
                if form_entry.get('taskId') == sft_obj.get('id'):
                    found_form_data = form_entry.get('formData', {})
                    break

            if found_form_data:
                form_data_input = found_form_data.get("input", [])
                for form_input_item in form_data_input:
                    for key, value in form_input_item.items():
                        if key in configuration.COLUMNS_ORDER and extracted_form_data.get(key) is None:
                            extracted_form_data[key] = value

                form_data_ratings = found_form_data.get("ratings", [])
                for rating_item in form_data_ratings:
                    question = rating_item.get('question')
                    human_input_value = rating_item.get('human_input_value')

                    if question in configuration.COLUMNS_ORDER:
                        extracted_form_data[question] = human_input_value

            df_row.append(extracted_form_data)

    # Save to CSV
    project_root = Path(__file__).parent
    csv_path = project_root / configuration.INPUT_DIR / f"{conversation_id}"
    os.makedirs(csv_path, exist_ok=True)

    if not df_row:
        print(f"No data found for colab link: {colab_link}")
        empty_df = pd.DataFrame(columns=configuration.COLUMNS_ORDER)
        empty_df.to_csv(f"{csv_path}/{conversation_id}.csv", index=False)
        return

    df_delivery_all = pd.DataFrame(df_row)
    df_to_deliver_final = df_delivery_all.reindex(columns=configuration.COLUMNS_ORDER)
    df_to_deliver_final.to_csv(f"{csv_path}/{conversation_id}.csv", index=False)


def get_labeling_tool_data(conversation_id, headers):
    """Fetch labeling tool data for a given conversation ID."""
    try:
        print(f"Fetching {conversation_id}...")

        # Construct the full URL with all join parameters
        base_url = configuration.CONVERSATION_API_URL_TEMPLATE.format(conversation_id=conversation_id)
        join_params = "&".join([f"join[{i}]={param}" for i, param in enumerate(configuration.API_JOIN_PARAMS)])
        url = f"{base_url}?{join_params}"

        response = requests.get(url, headers=headers)

        if response.status_code != 200:
            print(f"Failed to fetch data for ID {conversation_id}: {response.status_code} {response.reason}")
        else:
            data = response.json()

            colab_link = data.get('colabLink')
            batch_id = data.get('batch', {}).get('id')

            if batch_id:
                download_batch(batch_id, headers)
            else:
                print(f"Batch ID not found for ID {conversation_id}")

            if colab_link:
                print(f"Colab Link: {colab_link}")
                batch_json = f"{configuration.DOWNLOAD_DIR}/batch_{batch_id}.json"
                make_input_csv(colab_link, conversation_id, batch_json)
            else:
                print(f"Colab Link not found for ID {conversation_id}")

    except requests.RequestException as e:
        print(f"Error fetching data for ID {conversation_id}: {e}")
    except Exception as e:
        print(f"An unexpected error occurred: {e}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="CHDC Review Automation Executor")
    parser.add_argument("--task_id", required=True, help="Task or conversation ID")
    args = parser.parse_args()

    conversation_id = args.task_id

    # Get authentication token
    token = get_auth_token()
    if not token:
        print("Failed to retrieve authentication token. Exiting.")
        exit(1)

    headers = get_headers(token)

    # Execute main workflow
    get_labeling_tool_data(conversation_id, headers)
    review_executor(conversation_id)
