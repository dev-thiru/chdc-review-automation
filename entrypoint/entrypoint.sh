#!/bin/bash
set -euo pipefail

echo "[ENTRYPOINT] Starting execution..."

# --- Ensure working directory is the repo root ---
cd /app || { echo "[ERROR] /app does not exist"; exit 1; }

# --- Check that .git exists ---
if [ ! -d ".git" ]; then
    echo "[ERROR] .git folder not found in /app"
    exit 1
fi

# --- Fix Git ownership / safe directory ---
git config --global --add safe.directory /app
chown -R "$(id -u):$(id -g)" /app/.git || true

# --- CONFIGURATION (from environment) ---
QP1_USER_TURN="${baseCommit1:-}"
QP1_AGENT_TURN="${agentTurnCommit1:-}"
QP1_TEST="${testTurnCommit1:-}"

QP2_USER_TURN="${baseCommit2:-}"
QP2_AGENT_TURN="${agentTurnCommit2:-}"
QP2_TEST="${testTurnCommit2:-}"

QP3_USER_TURN="${baseCommit3:-}"
QP3_AGENT_TURN="${agentTurnCommit3:-}"
QP3_TEST="${testTurnCommit3:-}"

TEST_COMMAND="${runCommand:-true}"

# --- LOGS AND PATCH PATH ---
LOGS_PATH="${LOGS_PATH:-${logsPath:-/tmp/logs}}"
PATCH_DIR="${PATCH_DIR:-/app/patch}"

mkdir -p "$LOGS_PATH"
mkdir -p "$PATCH_DIR"
echo "[ENTRYPOINT] Using logs path: $LOGS_PATH"
echo "[ENTRYPOINT] Using patch path: $PATCH_DIR"

# --- PYTHON SCRIPT TO GENERATE run_test.sh ---
cat <<'EOF' > generate_test_script.py
import argparse, os

BASH_HEADER = "#!/bin/bash\nset -euo pipefail\n\n"

BLOCK_TEMPLATE = """
echo ""
echo "================= QUERY POINT SET {index} - TEST COMMIT CHECK ================="

git reset --hard {base}
git clean -fd -e entrypoint.sh -e generate_test_script.py -e run_test.sh -e patch || true

echo "Generating test patch for set {index}"
git diff {code} {test} > "$PATCH_DIR/gold_test_{index}.patch"

echo "Running test for PATCH SET {index} - TEST COMMIT CHECK"
safe_git_apply "$PATCH_DIR/gold_test_{index}.patch" "TEST PATCH {index}"
{test_command} || true

echo ""
echo "================= QUERY POINT {index} - CODE + TEST COMMIT CHECK ================="

git reset --hard {base}
git clean -fd -e entrypoint.sh -e generate_test_script.py -e run_test.sh -e patch || true

echo "Generating code patch for set {index}"
git diff {base} {code} > "$PATCH_DIR/gold_code_{index}.patch"

echo "Generating test patch for set {index}"
git diff {code} {test} > "$PATCH_DIR/gold_test_{index}.patch"

echo "Running test for PATCH SET {index} - CODE + TEST COMMIT CHECK"
safe_git_apply "$PATCH_DIR/gold_code_{index}.patch" "CODE PATCH {index}"
safe_git_apply "$PATCH_DIR/gold_test_{index}.patch" "TEST PATCH after CODE {index}"
{test_command} || true
"""

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--base1', required=True)
    parser.add_argument('--code1', required=True)
    parser.add_argument('--test1', required=True)
    parser.add_argument('--base2')
    parser.add_argument('--code2')
    parser.add_argument('--test2')
    parser.add_argument('--base3')
    parser.add_argument('--code3')
    parser.add_argument('--test3')
    parser.add_argument('--test_command', required=True)
    args = parser.parse_args()

    PATCH_DIR = os.environ.get("PATCH_DIR", "/app/patch")
    os.makedirs(PATCH_DIR, exist_ok=True)

    script = BASH_HEADER
    script += 'safe_git_apply() {\n'
    script += '    patch_file="$1"; desc="$2";\n'
    script += '    if [ ! -f "$patch_file" ] || [ ! -s "$patch_file" ]; then\n'
    script += '        echo "⚠️ Skipping $desc"; return 0; fi\n'
    script += '    git apply -v "$patch_file" || echo "⚠️ Patch apply failed for $desc"\n'
    script += '}\n\n'

    sets = [
        (1, args.base1, args.code1, args.test1),
        (2, args.base2, args.code2, args.test2),
        (3, args.base3, args.code3, args.test3),
    ]

    for idx, base, code, test in sets:
        if base and code and test:
            script += BLOCK_TEMPLATE.format(
                index=idx,
                base=base,
                code=code,
                test=test,
                test_command=args.test_command,
            )

    with open("run_test.sh", "w") as f:
        f.write(script)
    os.chmod("run_test.sh", 0o755)
    print("✅ Created run_test.sh, patches stored in", PATCH_DIR)

if __name__ == "__main__":
    main()
EOF

# --- Generate run_test.sh ---
export LOGS_PATH PATCH_DIR
echo "[ENTRYPOINT] Generating run_test.sh..."
python3 generate_test_script.py \
  --base1 "$QP1_USER_TURN" --code1 "$QP1_AGENT_TURN" --test1 "$QP1_TEST" \
  ${QP2_USER_TURN:+--base2 "$QP2_USER_TURN"} ${QP2_AGENT_TURN:+--code2 "$QP2_AGENT_TURN"} ${QP2_TEST:+--test2 "$QP2_TEST"} \
  ${QP3_USER_TURN:+--base3 "$QP3_USER_TURN"} ${QP3_AGENT_TURN:+--code3 "$QP3_AGENT_TURN"} ${QP3_TEST:+--test3 "$QP3_TEST"} \
  --test_command "$TEST_COMMAND"

# --- Collect commit history (max depth 4) ---
commit_vars=( \
  "QP1_USER_TURN:$QP1_USER_TURN" "QP1_AGENT_TURN:$QP1_AGENT_TURN" "QP1_TEST:$QP1_TEST" \
  "QP2_USER_TURN:$QP2_USER_TURN" "QP2_AGENT_TURN:$QP2_AGENT_TURN" "QP2_TEST:$QP2_TEST" \
  "QP3_USER_TURN:$QP3_USER_TURN" "QP3_AGENT_TURN:$QP3_AGENT_TURN" "QP3_TEST:$QP3_TEST" \
)

commit_chains_file="$LOGS_PATH/commit_chains.txt"
: > "$commit_chains_file"
echo "[ENTRYPOINT] Commit chain summary started."  >> "$commit_chains_file"
echo "[ENTRYPOINT] ======================================================================"  >> "$commit_chains_file"
echo "[ENTRYPOINT] Writing commit chains (depth 4) to $commit_chains_file"
for entry in "${commit_vars[@]}"; do
    name="${entry%%:*}"
    sha="${entry#*:}"

    [[ -z "$sha" ]] && continue

    if ! git rev-parse --verify --quiet "$sha" >/dev/null; then
        echo "$name -> (invalid ref: $sha)" >> "$commit_chains_file"
        continue
    fi

    echo "$name:" >> "$commit_chains_file"

    # Get the last 4 commits in parent history, oldest first
    mapfile -t commits < <(git rev-list --max-count=5 --reverse "$sha")

    # Reverse the array so latest commit is at top
    for ((i=${#commits[@]}-1; i>=0; i--)); do
        commit="${commits[i]}"
        msg=$(git log -1 --pretty=format:"%H - %s" "$commit")

        # Indentation: depth from the last commit
        depth=$(( ${#commits[@]} - 1 - i ))
        indent=""
        for ((d=0; d<depth; d++)); do
            indent+="  └─ "
        done

        echo "${indent}${msg}" >> "$commit_chains_file"
    done

    echo "" >> "$commit_chains_file"
done




echo "[ENTRYPOINT] Commit chain summary written."  >> "$commit_chains_file"
echo "[ENTRYPOINT] ======================================================================"  >> "$commit_chains_file"

echo "[ENTRYPOINT] File Changes Verification and PII summary."  >> "$commit_chains_file"
echo "[ENTRYPOINT] ======================================================================"  >> "$commit_chains_file"


for entry in "${commit_vars[@]}"; do
    name="${entry%%:*}"
    sha="${entry#*:}"

    # Skip if sha is empty
    [[ -z "$sha" ]] && continue

    # Verify commit SHA exists
    if ! git rev-parse --verify --quiet "$sha" >/dev/null; then
        echo "$name -> (invalid ref: $sha)" >> "$commit_chains_file"
        continue
    fi

    # Fetch author and committer details for the given commit only
    author_name=$(git show -s --format='%an' "$sha")
    author_email=$(git show -s --format='%ae' "$sha")
    committer_name=$(git show -s --format='%cn' "$sha")
    committer_email=$(git show -s --format='%ce' "$sha")

    # Fetch list of files with their status (A=Added, M=Modified, D=Deleted)
    mapfile -t changed_files < <(git show --pretty="" --name-status "$sha")

    # Write to output file
    {
        echo "$name ->"
        echo "  Commit: $sha"
        echo "  Author:    $author_name <$author_email>"
        echo "  Committer: $committer_name <$committer_email>"
        if [[ ${#changed_files[@]} -gt 0 ]]; then
            echo "  Files Changed:"
            for line in "${changed_files[@]}"; do
                status="${line%%[[:space:]]*}"
                file="${line#*[[:space:]]}"
                case "$status" in
                    A) status_text="Added" ;;
                    M) status_text="Modified" ;;
                    D) status_text="Deleted" ;;
                    R*) status_text="Renamed" ;;  # R100, R85, etc.
                    C*) status_text="Copied" ;;
                    *) status_text="$status" ;;
                esac
                echo "    - $file ($status_text)"
            done
        else
            echo "  Files Changed: (none)"
        fi
        echo ""
    } >> "$commit_chains_file"
done

echo "[ENTRYPOINT] File Changes Verification and PII summary completed."  >> "$commit_chains_file"
echo "[ENTRYPOINT] ======================================================================"  >> "$commit_chains_file"

cat "$commit_chains_file"

# --- Execute tests ---
echo "[ENTRYPOINT] Running generated script..."
bash -x ./run_test.sh || echo "[ENTRYPOINT] Completed with warnings, check above logs"

echo "[ENTRYPOINT] Finished execution ✅"
