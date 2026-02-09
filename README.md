# planning_mode_eval

This project aims to build an evaluation pipeline for **Claude Code's Plan Mode**. The pipeline would involve first generating ~30 tasks for a given repo, then running the tasks on Claude code, and finally grading the output plan.

## Usage

1. **Install dependencies:** `pip install -r requirements.txt` (or `pip install -e .`). Ensure **Node/npx** (for repomix) and **git** are available. Install and authenticate the **Claude Code CLI** for the run-plans step.
2. **Configure:** Copy `.env.example` to `.env` and set `ANTHROPIC_API_KEY`. Optionally set `BRAVE_SEARCH_API_KEY` for claim verification (get a key at [Brave Search API](https://api-dashboard.search.brave.com/)). Set `repo_url` (and optionally `branch`) in `config.yaml`.
3. **Run the pipeline** from the project root:
   - `python -m src.run_pipeline contextize` — clone repo and build repo map
   - `python -m src.run_pipeline generate-tasks` — generate tasks from last N merge commits (~3 min for 30 tasks)
   - `python -m src.run_pipeline run-plans` — run Claude Plan Mode for each task (this is going to take some time -- up to 6min/task)
   - `python -m src.run_pipeline grade` — grade plans and write `data/scores.json`
   - `python -m src.run_pipeline all` — run all steps in sequence

   Or install the package and run: `plan-eval contextize`, `plan-eval generate-tasks`, etc.

---
Tools used:
* Repomix: https://repomix.com/
* Claude Code: https://platform.claude.com/docs/en/agent-sdk/overview 
* [Not available for new customers] Google Custom Search Engine: https://programmablesearchengine.google.com/
    * To use the search API, set up an API key in Google Cloud Console for your project. Then, login to the project using `gcloud init`. (You may need to install gcloud here: https://docs.cloud.google.com/sdk/docs/install-sdk)
* Brave Search API: https://api-dashboard.search.brave.com/api-reference/web/search/get

---

## 0. Contextizer module to produce a "Repo Map"

This module clones the repo and generates a compressed, high-density representation of the codebase (the "Repo Map") that fits into an LLM's context window.

example schema:
```
<repository_map>
  <meta>
    <url>github.com/user/repo</url>
    <frameworks>React, Node.js, TensorFlow</frameworks> </meta>

  <file_tree>
    ├── README.md
    ├── package.json
    ├── src/
    │   ├── components/
    │   │   ├── Button.tsx
    │   │   └── Header.tsx
    │   ├── lib/
    │   │   └── utils.ts
    │   └── App.tsx
  </file_tree>

  <critical_files>
    <file name="README.md">
      [...Truncated content focusing on "Getting Started" and "Architecture"...]
    </file>
    <file name="package.json">
      [...Dependencies list only...]
    </file>
  </critical_files>

  <definitions>
    <file path="src/lib/utils.ts">
      function formatDate(date: Date): string
      function calculateMetric(data: number[]): number
    </file>
    <file path="src/components/Button.tsx">
      interface ButtonProps { label: string, onClick: () => void }
      const Button: React.FC<ButtonProps>
    </file>
  </definitions>
</repository_map>
```

We can use the `repomix` tool for the "Repo-to-Prompt" workflow. It automatically ignores lockfiles, generates a file tree, and packs the repo into a single XML/Markdown block. It has built-in token counting.


## 1. Task Generation: "The Repo Crawler"

To generate 30 high-quality tasks, wse the repository's own structure to ground the LLM to generate the tasks.

| Method | Description | Implementation Hint |
| --- | --- | --- |
| **Commit Reverse-Engineering** | Look at the last 50 PRs/Commits. Feed the diffs to Claude and ask: "What was the original feature request or bug report that led to this change?" | Use `git log -n 50 --patch`. |
| **Doc-to-Task** | Feed your `README.md` or `/docs` folder to an LLM. Ask it to generate "Missing Features" or "Edge Case Improvements" based on the current docs. | Focus on "What's mentioned but not fully implemented?" |
| **Code Smells/Refactoring** | Identify complex functions (high cyclomatic complexity) and generate tasks like: "Decouple the `AuthService` from the `Database` module." | Use `grep` or `cloc` to find large files. |

#### Actual implementation

* Source: Git History (Last 100 merged PRs).

* Methodology:

1. Extract commit metadata: Hash, Commit Messages, File Diffs.

2. LLM Transformation: Feed the "Repo Map" and the commit metadata to a generator model.

Prompt example: "Reverse engineer this git diff. Write a prompt that a user would have asked to trigger this specific code change. The prompt can have larger scope than this single diff. Do not mention the solution."

Output Schema (TaskObject):
```
{
  "task_id": "task_001",
  "prompt": "Users are reporting timeouts during login. Implement a retry mechanism.",
  "repo_state_commit": "7a3b9c...",  // The parent commit (before the fix)
  "ground_truth": {
    "files_modified": ["src/auth/login.ts", "src/config/constants.ts"],
    "files_created": [],
    "key_additions": ["retry logic loop", "MAX_RETRIES constant"],
    "libraries_added": ["axios-retry"] // Extracted from package.json diff
  }
  "difficulty": "Hard"
}
```
(repo_state_commit and ground_truth are not llm-generated)

---

## 2. Running the Pipeline: Headless Plan Mode

Claude Code can be automated using its CLI flags. This allows us to bypass the interactive terminal and capture the plan directly.

**The Command:**

```bash
# -p runs a prompt, --permission-mode plan keeps it in read-only mode
claude --permission-mode plan -p "Your generated task description here"

```

**Capture the Output:**
By default, Claude Code writes its plan to a `.claude/plan.md` file or outputs it to `stdout`. Use a wrapper script (Python or Bash) to:

1. Initialize a clean state (e.g., `git checkout -f`).
* Before each run: git checkout {parent_commit_of_task}. This ensures the repo is in the state before the fix was implemented.
2. Run the command.
3. Save the resulting markdown for grading.


---

## 3. Grading the Plan: The "Judge" Model

Since we aren't executing the code yet, we need a **Model-graded Evaluation**. Ideally we would use a stronger model (like **Claude Opus 4.6**) as the judge.

### 3.1 Grading Dimensions (Autoraters)

#### 3.1.1 Correctness - Claim verification (40%)
$$\text{Score} = (w_1 \times \text{\% Valid Claims}) + (w_2 \times \text{Logical Flow Score})$$

Step A: Decomposition & Claim Extraction
The Judge LLM parses the markdown plan into atomic steps.

* Input: Full Markdown Plan.
* Operation: Extract Step, Intent, and Verifiable Claims.
* Claim Definition: Any statement regarding library existence, function syntax, or architectural constraints.

Step B: Search Verification
For every extracted claim, the system executes a verification check.

* Tool: Google Custom Search JSON API (or similar).
* Logic (example):
    * Claim: "Use pandas.read_xml with iterparse."
    * Query: "pandas read_xml iterparse documentation"
    * Validation: LLM compares Search Snippet vs. Claim.
    * Result: VERIFIED | HALLUCINATION | UNKNOWN.

Step C: Logic & Dependency
Once facts are verified, evaluate the sequence. This step will use the "Repo Map" as reference.

* Pre-computation Check: Does Step B require an output that Step A fails to produce?
* Is the overall plan logically sound?
* Does the plan solve the problem?

#### 3.1.2 Correctness - Comparison with Groud Truth (40%)

For every task, we have a TaskObject containing the ground truth when we constructed it.
```
{
  "task_id": "task_001",
  "prompt": "Users are reporting timeouts during login. Implement a retry mechanism.",
  "repo_state_commit": "7a3b9c...",  // The parent commit (before the fix)
  "ground_truth": {
    "files_modified": ["src/auth/login.ts", "src/config/constants.ts"],
    "files_created": [],
    "key_additions": ["retry logic loop", "MAX_RETRIES constant"],
    "libraries_added": ["axios-retry"] // Extracted from package.json diff
  }
}
```

**Metric 1**: File Relevance -- Recall & Precision (static metric)

A good plan must identify the correct code to modify, without hallucinating irrelevant ones. 

Recall: $\frac{\text{Intersection(Plan Files, Truth Files)}}{\text{Total Truth Files}}$

Precision: $\frac{\text{Intersection(Plan Files, Truth Files)}}{\text{Total Plan Files}}$


**Metric 2**: LLM judge 

Provide the LLM with both the diffs in the PR and the plan, and ask if they are logically equivalent.

e.g. "Here is the User Task: [task]
Ground Truth Solution: [diff metadata][code]
AI Plan: [plan]
Evaluation: Does the AI Plan achieve the same goal as the Ground Truth? Is it a valid alternative, or does it over-engineer? Grade 1-5."


#### 3.1.3 Text Quality (20%)
This is a single prompt that assesses how the plan is communicated, not just what it says. 

**The "Style Guide" Rubric:**

| Dimension | Definition | Failure Mode (Negative Signals) |
| --- | --- | --- |
| **Conciseness** | Information density; low "fluff." | "In order to...", "It is important to note that...", excessive polite padding. |
| **Precision** | Usage of specific terminology over vague descriptions. | Using "fix the thing" instead of "refactor the `Auth` class." |
| **Tone** | Professional, action-oriented language. | "We could try to..." instead of "Implement X." |
| **Formatting** | Use of markdown for readability. | Large text blocks without bullet points or code blocks. |


### 3.2 Scoring Rubric

The final score (0-100) is a weighted average of sub-scores under the 3 dimensions.

### 1. Correctness - Claim Verification (40% Weight)

**Metrics:**
* Ratio of verified claims (20%)
* Logical soundness (20%)

### 2. Correctness - Ground Truth Matching (40% Weight)

**Metrics:**
* Recall (Files found / Files needed) (10%)
* Precision (Files found / all files mentioned) (10%)
* LLM judge of GT matching (20%)

### 3. Quality (20% Weight)

**Metrics:**
* Conciseness (5%)
* Precision (5%)
* Tone (5%)
* Formatting (5%)


---

## Future Steps

* Repo Map:
    * The repo map is useful for LLMs to understand the repo within their context window, but currently it is a big static chunk of text. Some retrieval mechanism would be helpful especially for larger repos.
* Task Gen:
    * Do user research on real-world usage of planning mode to see what types of tasks are relevant. Generate tasks based on that.
    * The advantage of basing task generation on PRs is that we get "ground truth" labels, but the quality of the labels can still be improved. Currently they are extracted using heuristics, but we can also use LLMs.
    * Another con of using PRs is that many may have limited scope than what would mandate the creation of a 'plan'. While we mitigate that here by removing those non-plan-mode commits with the commit classification prompt, there are still nuances remaining.
* Grading:
    * Calibrate the autorater performance with human evaluation. Prompts could be tuned further.
    * Claim Verification:
        * We should distinguish between claims that are verifiable with web searches only, and those that depend on the context of the repo.
        * Currently we only rate 5 claims for each task due to API limit, but more would be better.


