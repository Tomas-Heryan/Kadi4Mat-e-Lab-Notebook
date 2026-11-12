# Windows launcher for Kadi Lab Manager

**File:** `Kadi4Mat_Windows-1.6.cmd` · **Version:** 1.6 (12 November 2026) · **Publisher:** CEET, VŠB-TUO

One file that takes a Windows computer from "nothing installed" to "demo deployed in Kadi4Mat".

The launcher is a plain batch script. It carries out the installation guide
`INSTAL-Kadi-Lab-Manager-v1.0.1.md` step by step — download release `v1.0.1`, create the virtual
environment, install and verify `kadi-lab-manager` — then asks for your personal access token,
checks the connection and deploys the demo model (`model/demo.yaml`) to the Kadi4Mat instance
configured in `.env` (default `https://kadi-test.vsb.cz`). Every deployment gets a unique
timestamp at the end of all identifiers, so repeated runs never collide.

The script talks to you in Czech, written in plain ASCII without diacritics so that it displays
correctly in every console. This document describes everything in English; a
[glossary](#console-glossary) translates the messages you will see.

## What it does

| Step | Action | Installation guide |
|---|---|---|
| 1 | Looks for Git, Python 3.10–3.14 and VS Code | step 1 |
| 2 | Clones release `v1.0.1` into the project folder, or reuses the copy that is already there | step 2 |
| 3 | Creates `.venv`, installs the package with `pip install -e .`, creates `.env` from `.env.example` | step 3 |
| 4 | Runs `--version`, validates `model/ceet.yaml` and `model/demo.yaml`, runs the unit tests after a fresh installation | step 4 |
| 5 | Asks for the access token (hidden input), stores it in `.env`, runs `doctor`, checks that the token may read records | step 5 |
| 6 | Creates a timestamped copy of the demo model, runs `plan`, then `apply` — you confirm the write yourself | section *Co dál* |
| 7 | Optionally installs three VS Code extensions and opens the project | step 6 |

Work that is already done is not repeated. On later runs an existing project is not downloaded
again, a working `.venv` is not reinstalled, and a token already stored in `.env` is kept when
you just press Enter.

## Requirements

- **Windows 10 or 11** with `cmd.exe` and Windows PowerShell 5.1 (both built in). PowerShell is
  used only for the hidden token prompt.
- **Git** and **Python 3.10–3.14.** If either is missing, the launcher offers to install it with
  `winget`. Python 3.15 cannot be used because the dependency kadi-apy 0.51 requires a lower
  version.
- **VS Code** is optional; without the `code` command step 7 is skipped.
- **Network access** to GitHub, PyPI and the Kadi4Mat server.
- A **Kadi4Mat account** and a personal access token with the scopes listed
  [below](#access-token).

Administrator rights are not needed for the launcher itself. Installers started through `winget`
may ask for them.

## Quick start

1. Download `Kadi4Mat_Windows-1.6.cmd`.
2. Unblock it: right-click the file → *Properties* → tick *Unblock*. Windows marks every file
   downloaded from the internet and may stop it with the SmartScreen dialog *Windows protected
   your PC*; there you can also choose *More info* → *Run anyway*. This has to be done for each
   newly downloaded copy.
3. Double-click the file. Alternatively run it from a terminal, optionally with the project
   folder as an argument:

   ```bat
   Kadi4Mat_Windows-1.6.cmd
   Kadi4Mat_Windows-1.6.cmd "D:\Work\Kadi4Mat-e-Lab-Notebook"
   Kadi4Mat_Windows-1.6.cmd /?
   ```

4. In step 5 paste your access token and press Enter.
5. In step 6 read the plan and type `y` + Enter to write to the server.

### Answering the prompts

- Questions ending with `[A/N]` wait for a single key: **A** (*ano*, yes) or **N** (*ne*, no).
  **Y** is accepted as yes too. Enter is not needed.
- The token prompt hides what you type and shows asterisks instead. Paste with the right mouse
  button or Ctrl+V, then press Enter.
- `Apply these changes to ...? [y/N]` comes from `kadi-lab-manager` itself: type `y` and
  Enter to proceed; anything else aborts without changing the server.
- At the very end the window waits for any key so that you can read the output.

### Where the project lives

The project folder is chosen in this order:

1. the folder passed as the first argument;
2. the copy of the project that contains the launcher — the launcher's own folder or up to
   three levels above it, recognised by `src\kadi_lab_manager\cli.py`. Such a copy is used
   exactly as it is;
3. `%USERPROFILE%\Projects\Kadi4Mat-e-Lab-Notebook` (the location used by the installation
   guide).

If the folder does not contain the project yet, the release is cloned into it. Avoid folders
synchronised by OneDrive: the virtual environment consists of thousands of small files.

## Step by step

### Step 1 — prerequisites

- `git --version`, `code --version`.
- Python is searched with the `py` launcher from the newest allowed version down:
  `py -3.14`, `-3.13`, `-3.12`, `-3.11`, `-3.10`. The first one found is used. If the launcher
  finds none, the plain `python` command is accepted when its version is in the same range.
- Nothing is installed in this step. What is missing is offered only when it is actually
  needed (Git in step 2, Python in step 3).

### Step 2 — download release v1.0.1

- If `pyproject.toml` is already in the project folder, nothing is downloaded.
- Otherwise the launcher runs
  `git clone -c core.autocrlf=false --branch v1.0.1 <repository> <project folder>`.
  The option keeps the files byte-for-byte identical to the release, as the installation guide
  requires. Git's message about a *detached HEAD* is expected.
- If Git is missing and `winget` is available, the launcher asks whether to run
  `winget install -e --id Git.Git`. A window that is already open does not see newly installed
  programs, so the usual location `%ProgramFiles%\Git\cmd` is tried as well; if Git still
  cannot be found, close the window and start the launcher again.
- In a Git clone the release is verified with `git describe --tags`. If the answer is not
  `v1.0.1`, the launcher asks whether to run `git fetch --tags` and `git checkout v1.0.1`;
  answering **N** keeps the working copy as it is. If the launcher itself lies inside that
  working copy, it does not ask and never switches the release, because a checkout could remove
  the running script; it only reports the difference. A copy without `.git` (for example an
  unpacked ZIP) is used as it is, with a note that the release cannot be verified.
- Finally six files must exist: `pyproject.toml`, `src\kadi_lab_manager\cli.py`,
  `model\ceet.yaml`, `model\demo.yaml`, `tests\mock_kadi.py`, `.env.example`.

### Step 3 — virtual environment and installation

- An existing `.venv` is reused if its Python is 3.10–3.14. If it uses another version or is
  incomplete, the launcher asks before deleting and recreating it.
- A new environment is created with `<python> -m venv .venv`. If no suitable Python was found,
  the launcher offers `winget install -e --id Python.Python.3.14`.
- `python -m pip install --upgrade pip` (a failure here is only a warning) and
  `python -m pip install -e .`. Both are skipped when `kadi-lab-manager.exe --version` already
  works in the existing environment.
- `.env` is created from `.env.example` if it does not exist.

Programs are always called directly from `.venv\Scripts\`. The environment is never activated
and the PowerShell execution policy is never changed.

### Step 4 — verify the installation

- `kadi-lab-manager --version`
- `kadi-lab-manager validate model\ceet.yaml` and `validate model\demo.yaml`
- `python -m unittest discover -s tests` — only when the package was installed during this
  run. The tests use the built-in mock server and take about 20 seconds; the expected end of
  the output is `Ran 7 tests` and `OK`. If they fail, the launcher asks whether to continue.

### Step 5 — token and connection test

- The token is requested and written to `.env`; see [Access token](#access-token).
- `kadi-lab-manager doctor` is run. If it fails, the launcher lists the usual causes and asks
  whether you want to enter the token again.
- `doctor` ends with `OK` even when the token is not allowed to read records. The launcher
  therefore runs it a second time silently and looks for `records: not readable` in its output.
  If it finds it, it explains what is wrong and lets you enter a new token straight away.

### Step 6 — deploy the demo

- A timestamp and a timestamped copy of the model are created; see
  [Timestamped identifiers](#timestamped-identifiers).
- `kadi-lab-manager plan <copy>` — a safe preview that changes nothing.
- `kadi-lab-manager apply <copy>` — prints the plan again and asks for confirmation.
- If `plan` fails, nothing has been written. The launcher explains the usual cause (missing
  token scopes) and offers to repeat steps 5 and 6 with another token.

### Step 7 — VS Code (optional)

After confirmation: `code --install-extension` for `ms-python.python`, `ms-python.debugpy`
and `redhat.vscode-yaml`, then `code .` to open the project. When VS Code asks whether you
trust the authors of the files, answer yes; otherwise debugging and tasks stay disabled.

Step 7 is also offered when steps 5 or 6 did not finish, because the installation itself is
complete at that point.

## Access token

Create the token in Kadi4Mat under *Settings → Access tokens*; it starts with `pat_`.

**Tick the scopes when you create the token.** In current Kadi4Mat versions a token created
without scopes can only use a few basic endpoints: it logs in, but `plan` and `apply` fail.
Scopes cannot be added by the launcher or by `kadi-lab-manager`; if they are missing, create a
new token. See the
[Kadi4Mat HTTP API introduction](https://kadi4mat.readthedocs.io/en/latest/httpapi/intro.html).

| Purpose | Scopes |
|---|---|
| Deployment | `record.read` `record.create` `record.update` `record.link` |
| | `collection.read` `collection.create` `collection.update` `collection.link` |
| | `template.read` `template.create` `template.update` |
| | `group.read` `user.read` |
| Only if the model deploys roles | `record.permissions` `collection.permissions` `template.permissions` |
| Only for `cleanup` | `record.delete` `collection.delete` `template.delete` (plus `misc.manage_trash` for `--purge`) |

What the launcher does with the token:

- It reads it with a hidden prompt. The token is never printed, never passed on a command line
  and never stored in a `cmd` variable; only its length is shown.
- It writes it to the `KADI_TOKEN=` line of `.env` in the project folder. Other lines are kept,
  and the file is saved as UTF-8 without a byte-order mark — a file in UTF-16 or with a BOM is
  converted, because `kadi-lab-manager` could not read it reliably.
- If `.env` already holds a real token, pressing Enter keeps it.
- The placeholder `TOKEN`, text containing spaces or non-ASCII characters, and empty input are
  refused; there are three attempts. A pasted whole line `KADI_TOKEN=pat_...` is accepted.
- `KADI_URL` is added to `.env` only when it is missing or empty. The server in use is shown
  before the prompt, with a warning if it differs from the default.
- Environment variables `KADI_URL`, `KADI_TOKEN` and `KADI_ENV_FILE` that are already set would
  take precedence over `.env`. The launcher ignores them for its own run (their values are not
  displayed); other `KADI_*` variables, such as `KADI_CA_BUNDLE`, are left alone.
- If the hidden prompt cannot be started, the launcher falls back to the manual method from the
  installation guide and opens `.env` in Notepad.

`.env` is listed in `.gitignore`. Anyone who can read the project folder can read the token, so
revoke tokens you no longer need.

## Timestamped identifiers

Each deployment appends the current local date and time in the form `YYYYMMDDHHMM` — for
example `202611120824` — to every identifier it creates:

```
proj-project202611120824
ceet202611120824
inst-power-analyzer-yokogawa-wt310e-01202611120824
```

How it works:

1. The launcher asks the Python in `.venv` for the timestamp.
2. It writes a copy of the model next to the original, for example
   `model\demo-202611120824.yaml`, in which `settings.namespace` is set to the timestamp. The
   model's own namespace (`-demo`) is replaced. `model\demo.yaml` is not modified.
3. The copy is checked with `validate`, then used for `plan` and `apply`.

**Why there is no separator.** A Kadi4Mat identifier may have at most 50 characters. The
longest identifiers of the v1.0.1 demo model have 38, which leaves room for exactly the twelve
digits. With a hyphen in front of the timestamp four identifiers would have 51 characters and
`validate` rejects the model. If the identifiers in your model are shorter, set
`PREDPONA_STOPY` (see [Configuration](#configuration)), for example to `-`.

What follows from this:

- **Every confirmed run creates a new, independent set of objects** — 119 for the v1.0.1 demo.
  Nothing that already exists on the server is changed, and sets from earlier runs stay there.
- Two runs within the same minute get the same timestamp; the second finds nothing to do.
- The model copies are kept. To continue an interrupted deployment, run `apply` on the existing
  copy instead of starting the launcher again:

  ```bat
  .venv\Scripts\kadi-lab-manager.exe apply model\demo-202611120824.yaml
  ```

- To remove the set created by one run, use its timestamp as the namespace. Without
  `--apply --yes` the command only lists what it would delete:

  ```bat
  .venv\Scripts\kadi-lab-manager.exe cleanup --namespace=202611120824
  .venv\Scripts\kadi-lab-manager.exe cleanup --namespace=202611120824 --apply --yes
  ```

  The launcher prints this command at the end of a successful run. It never runs `cleanup`
  itself.

## Configuration

All settings are `set "NAME=value"` lines at the top of the script.

| Variable | Default | Meaning |
|---|---|---|
| `VYDANI` | `v1.0.1` | Release tag to clone and verify |
| `REPOZITAR` | `https://github.com/Tomas-Heryan/Kadi4Mat-e-Lab-Notebook.git` | Repository to clone |
| `SLOZKA_PROJEKTU` | `%USERPROFILE%\Projects\Kadi4Mat-e-Lab-Notebook` | Default project folder |
| `PY_VERZE_SEZNAM` | `3.14 3.13 3.12 3.11 3.10` | Python versions, in the order they are tried |
| `WINGET_GIT` | `Git.Git` | `winget` package offered when Git is missing |
| `WINGET_PYTHON` | `Python.Python.3.14` | `winget` package offered when Python is missing |
| `VYCHOZI_SERVER` | `https://kadi-test.vsb.cz` | Written to `.env` as `KADI_URL` only if that line is missing or empty |
| `MODEL_CEET` | `model\ceet.yaml` | Model validated in step 4 |
| `MODEL` | `model\demo.yaml` | Model validated in step 4 and deployed in step 6 |
| `PREDPONA_STOPY` | *(empty)* | Text placed in front of the timestamp, e.g. `-`; lowercase letters, digits, `-` and `_` only |
| `VYDAVATEL` | `CEET, VSB-TUO` | Publisher shown in the banner and in the help text |

To deploy to another Kadi4Mat instance, change `KADI_URL` in `.env`; the token must have been
issued by that instance.

## Files and folders

| Path | Written by | Notes |
|---|---|---|
| `<project>\` | step 2 | Git clone of the release |
| `<project>\.venv\` | step 3 | Deleted and recreated only after confirmation |
| `<project>\.env` | steps 3 and 5 | Holds `KADI_URL` and `KADI_TOKEN`; git-ignored |
| `<project>\model\<model>-<timestamp>.yaml` | step 6 | One per deployment; kept |
| `<project>\reports\`, `<project>\state\` | `kadi-lab-manager` | Run reports and the per-host state ledger (the tool's default folders) |

The launcher itself writes only inside the project folder, creating its parent folder if
necessary. The programs it starts keep their own data elsewhere: the pip cache, programs
installed through `winget`, VS Code extensions. `PATH` is extended only inside the launcher's
own process, and only after an installation through `winget`.

The script does not depend on its own file name, so it can be renamed freely.

## What the launcher does not do

- It never runs `cleanup` and never runs `apply --update`.
- It never passes `--yes` to `apply`; the write is always confirmed by you.
- It does not change the PowerShell execution policy and does not activate the environment.
- It does not install Git, Python or VS Code extensions without asking first.
- It does not modify `model\demo.yaml` or any other file of the release.

## Exit codes

| Code | Meaning |
|---|---|
| 0 | Finished: installed and deployed. Also returned by `/?`. |
| 2 | Project folder cannot be used, download failed, wrong release could not be checked out, or the project is incomplete |
| 3 | Git or Python is not available, or the virtual environment could not be created or replaced |
| 4 | Installation failed, the program does not start, or the unit tests failed and you chose not to continue |
| 5 | A model did not pass `validate`, or the timestamped model could not be created |
| 6 | No token was entered, `.env` could not be created, or the token lacks scopes and no new one was entered |
| other | Exit code of `kadi-lab-manager doctor`, `plan` or `apply`, passed through unchanged — typically 1 for an API error, a failed operation or an unconfirmed `apply`, and 2 for a configuration error |

Code 2 therefore has two possible sources; the message printed before it tells them apart.
When the exit code is not 0, the last lines of the output say `Skript skoncil s kodem N.`

## Console glossary

| Czech text in the console | Meaning |
|---|---|
| `[KROK 3/7]` | Step 3 of 7 |
| `[CHYBA]` | Error |
| `Pozn.:` / `Upozorneni:` / `POZOR:` | Note / warning |
| `OK` / `CHYBI` in the file list | File found / file missing |
| `nenalezen` | Not found |
| `Projekt uz ve slozce je - nestahuji jej znovu.` | The project is already there; it is not downloaded again |
| `Pouzivam existujici .venv` | Reusing the existing virtual environment |
| `Program je jiz nainstalovan - instalaci neopakuji.` | Already installed; installation skipped |
| `Zadej KADI_TOKEN` | Enter the access token |
| `Ponechavam token ulozeny v .env.` | Keeping the token stored in `.env` |
| `Tento soubor lezi uvnitr pracovni kopie, proto ji neprepinam` | The launcher is inside the working copy, so the copy is not switched to another release |
| `Casova stopa tohoto nasazeni` | Timestamp of this deployment |
| `Na server se nic nezapsalo.` | Nothing was written to the server |
| `HOTOVO - instalace je dokoncena a demo je na serveru` | Done: installed and deployed |
| `INSTALACE JE DOKONCENA - demo na server nasazeno nebylo` | Installed, but the demo was not deployed; see the messages above |
| `Skript skoncil s kodem N.` | The script ended with exit code N |
| `Stiskni libovolnou klavesu pro zavreni okna...` | Press any key to close the window |

## Troubleshooting

| Symptom | What to do |
|---|---|
| Windows refuses to start the file, also with *Run as administrator* | The file is blocked because it was downloaded. *Properties* → *Unblock*, or in the SmartScreen dialog *More info* → *Run anyway*. |
| Windows shows *Unknown publisher* | Expected. Windows takes the publisher from a digital signature, and a `.cmd` file cannot carry one. |
| Git or Python was installed through `winget` but is still not found | Close the window and start the launcher again; a new window sees the new programs. |
| `Python ...... ve verzi 3.10 az 3.14 nenalezen` | Install Python 3.14 (the launcher offers `winget`), or any version from 3.10 to 3.14. |
| `[CHYBA] Stazeni projektu se nezdarilo` | No access to GitHub, or the target folder exists and is not empty. Remove or rename the folder, or pass another one as an argument. |
| `git describe hlasi "..."` | The working copy is not exactly at `v1.0.1`. If the launcher asks, **A** checks the release out and **N** continues with the copy as it is. A launcher stored inside the copy does not ask and uses it as it is. |
| `Existujici .venv pouziva Python` followed by a version outside 3.10–3.14 | The environment was created with an unsupported Python. Confirm the deletion; it is recreated with a suitable version. |
| `[CHYBA] Instalace skoncila chybou` | No access to PyPI (proxy), or — with `No matching distribution found for kadi-apy` — an environment created with Python 3.15 or newer. |
| `Skryte zadani tokenu se nepodarilo spustit` | PowerShell could not run the prompt. `.env` opens in Notepad: replace `TOKEN` on the `KADI_TOKEN=TOKEN` line, save and close. |
| `records: not readable` / `[CHYBA] Token se k serveru prihlasil, ale nesmi cist zaznamy` | The token has no scopes or lacks `record.read`. Create a new token with the scopes ticked and enter it. |
| `doctor` fails with HTTP 401 | The token is invalid, expired, issued by another server, or lacks scopes — the server lists the missing ones under `scopes`. |
| `doctor` fails with HTTP 403 | Your account has no access to the object on the server. |
| `doctor` reports a TLS error | Internal certificate authority: add `KADI_CA_BUNDLE=<path to the CA file>` to `.env`. |
| `doctor` reports `network error` | The server cannot be reached from this computer (VPN, proxy). |
| `plan` fails with HTTP 401 and a `scopes` entry | The token lacks the listed scopes. Answer **A** and enter a token that has them. |
| `is longer than 50 characters` in step 6 | An identifier plus the timestamp exceeds the Kadi4Mat limit. Shorten the identifier in the model or empty `PREDPONA_STOPY`. |
| The server fills up with demo sets | By design every confirmed run creates a new set. Remove old ones with `cleanup --namespace=<timestamp>`. |
| `Prikaz code neni k dispozici` | VS Code is not on `PATH`. Install the extensions in the *Extensions* panel and open the folder with *File → Open Folder*. |

## Security notes

- **Token.** See [Access token](#access-token): hidden input, stored only in `.env`, never
  displayed.
- **No signature.** Batch files cannot be digitally signed. The publisher line printed by the
  script is informational and is not verified by Windows.
- **Embedded PowerShell.** To read the token without showing it, the script starts Windows
  PowerShell and lets it execute the code stored at the end of the same file, after the marker
  line `#PS_BLOK_TOKEN`. No `.ps1` file is run, nothing is downloaded and no temporary file is
  written. Security products can be suspicious of scripts that read themselves this way; if the
  prompt is blocked, the launcher falls back to Notepad.
- **Network.** The launcher itself contacts nothing. The programs it starts contact GitHub
  (`git clone`), PyPI (`pip`), the Kadi4Mat server (`kadi-lab-manager`) and, only after you
  agree, the `winget` sources and the VS Code extension marketplace.
- **Review.** The script is short enough to read. The main commands it runs are echoed to the
  console with a leading `>`.

## For maintainers

### Where to keep the launcher

The launcher is a bootstrap: people download this one file *before* they have the project. It
does not have to be part of a tagged release of the package, and adding it to the repository
does not require a new release.

Recommended:

- Keep `Kadi4Mat_Windows-1.6.cmd` and this document together in their own folder on the default
  branch, for example `windows/`, and link to them from `README.md`.
- Leave `VYDANI=v1.0.1`. The launcher then always installs the pinned release it was written
  for, however far the default branch has moved on.
- Optionally attach the `.cmd` file to the GitHub release of `v1.0.1` as a download.
- Change `VYDANI` only when a new release of the package is tagged.

A developer who starts the launcher from inside a clone gets that clone used as it is (see
[Where the project lives](#where-the-project-lives)): it is neither downloaded again nor
switched to another release.

### File format and Git

The script must stay **pure ASCII with CRLF line endings and no byte-order mark**. `cmd.exe`
can fail to find labels in batch files with LF-only line endings.

Git on Windows converts CRLF to LF on commit by default, and the launcher is usually obtained
as a single-file download from the GitHub web page, which delivers exactly the stored bytes.
The stored file itself must therefore keep CRLF. The repository has no `.gitattributes` yet;
add this line **before** committing the script:

```gitattributes
*.cmd -text
```

With `-text` Git never converts the file, so the single-file download, the ZIP archive and a
clone — also one made with `core.autocrlf=false`, as in the installation guide — all contain
CRLF. `*.cmd text eol=crlf` is not enough: clones and archives would be correct, but the stored
file, and with it the single-file download, would have LF.

After committing, check with `git ls-files --eol`; the line for the script must start with
`i/crlf w/crlf`.

The timestamped model copies are run artefacts; consider adding them to `.gitignore`:

```gitignore
model/*-[0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9].yaml
```

### Structure of the file

- **Batch part** — from the first line to `goto :eof`: settings, the seven steps, error
  handlers, subroutines.
- **PowerShell block** — from the marker line `#PS_BLOK_TOKEN` to the end of the file. `cmd.exe`
  never reaches it. In step 5 the batch part starts `powershell -NoProfile -Command ...`, which
  reads the script file, takes everything after the last occurrence of the marker and executes
  it. The marker must therefore occur exactly twice: once in that command and once at the start
  of the block.
- **Two Python one-liners**, `PY_STOPA` and `PY_MODEL`, stored in variables and passed to the
  Python in `.venv` with `-c` in step 6. They must not contain `"`, `%` or `!`; `PY_STOPA` must
  not contain an apostrophe either, because it runs inside `for /f`.

### Conventions used in the batch part

- No `&&`, no `||`, no parenthesised blocks; control flow is `if ... goto label`.
- The exit code of an external program is copied into a variable on the very next line. In a
  `.cmd` file a successful `set` resets `ERRORLEVEL`.
- `code` is called through `call`, because on Windows it is a batch file and would otherwise
  end the launcher.
- Programs inside the project are called by relative path after `pushd` into the project
  folder; all other paths are quoted. Folders with spaces and parentheses are supported.
- Questions use `choice`, which reads a single key and cannot be broken by unexpected input.
- No label is a prefix of another label.

### Releasing a new version of the repository

- When a new release of the package is tagged, set `VYDANI` to the new tag and update the
  version line in the header. Until then leave it pinned.
- If the number of unit tests changes, update the message that mentions `Ran 7 tests`.
- Make sure the deployed model still validates with a twelve-character namespace, i.e. that no
  identifier is longer than 38 characters, or document a different `PREDPONA_STOPY`.
- Update this document.

### Tests

The launcher is not covered by the repository's unit tests; `tests/` exercises the Python
package against the bundled mock server.

## License

The launcher is part of this repository and is distributed under the same terms:
Apache-2.0, see `LICENSE` and `NOTICE`.
