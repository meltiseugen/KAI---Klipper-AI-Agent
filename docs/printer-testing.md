# Fast updates while testing on a printer

The updater supports both systemd installations and native Creality/KE init services.
Use the unprivileged service account for systemd, or root for an installed native
service. The installed receipt selects the backend; no sudo or systemd is needed on
native hosts. See [native Creality installation](creality-compatibility.md).

Install once using [the host installer](HOST_INSTALL.md). The SSH account must own
the checkout. Standard systemd hosts also require sudo access for the KlipperAI
unit. OpenSSH (`ssh`) and Python are needed on the development machine; the printer
needs tar (including BusyBox tar). A single SSH tar stream transfers the bundle,
so a remote scp/SFTP server is not required.
`uv` is the preferred local wheel builder; pip with build dependencies also works.

Copy `deployment/targets.example.json` to `.local/deploy-targets.json` and edit the
host, checkout path and local service port. This file is ignored by Git. SSH keys,
ports and connection options belong in your OpenSSH config, not in this file.

```json
{
  "printer": {
    "host": "biqu@printer.local",
    "install_dir": "/home/biqu/KlippyAI",
    "url": "http://127.0.0.1:8811/readyz"
  }
}
```

From your development checkout:

```sh
# Build and display the target without contacting the printer.
python -m tools.deploy printer --dry-run

# Build this workspace, including uncommitted fixes, and deploy it.
python -m tools.deploy printer

# Return to the previous code selection without rebuilding.
python -m tools.deploy printer --rollback
```

You can also use `python -m tools.deploy biqu@printer.local --install-dir
/home/biqu/KlippyAI` directly. `--wheel dist/klipperai-<version>-py3-none-any.whl`
deploys an already built package. `--non-interactive` disables the SSH terminal and
uses noninteractive sudo; configure the operator's SSH/sudo access first.

The command sends only a wheel and its deployment helpers to a private temporary
directory. It checks the SHA-256, stages code under `.klipperai-releases/` and checks
dependencies and imports. Standard hosts use a fixed systemd drop-in; native init
hosts select the same code pointer directly. The service stops briefly while the
selection changes, then starts.
`/readyz` must report the exact build and read-only printer access. A failed start
restores the previous selection and restarts KlipperAI. Readiness is an application
boot check; it does not claim that the printer or provider is connected.

Only KlipperAI's unit or recorded native process is stopped/started. The updater preserves runtime
configuration, provider keys/master credentials and application history, and does
not edit printer configuration. It retains the current and previous code packages;
dependencies are shared rather than copying a virtual environment per update.
No commit, push, GitHub release or download on the printer is required. The wheel
contains Python and browser assets, not logs, settings or databases.

Keep the same deployment path during a test cycle. A successful wheel update takes
precedence over the editable source checkout; subsequent `git pull` changes are not
active until deployed as another wheel. The first rollback can return to the original
editable checkout. Later rollbacks swap the two retained selections.

The uninstaller removes the managed code-selector drop-in alongside the service
unit and preserves other operator drop-ins. Staged code remains inside the checkout
if you choose to keep that checkout during uninstall.

## Dependency and recovery limits

The fast path uses `pip --no-index --no-deps --target`. If dependencies are missing
or incompatible, it fails before stopping the running service. Plan dependency
upgrades as separate maintenance: back up app storage/settings and the environment,
install reviewed requirements in the service environment, then deploy/test code.
Code rollback does not undo dependency or database schema changes. Releases must
document these changes and their recovery procedure. Do not rerun the full guided
installer merely to update code: it generates configuration again.

Use `journalctl -u klipperai-agent.service -n 100 --no-pager` to inspect startup
failures. `/readyz` reports `version` and a wheel hash prefix (`build`); an editable
checkout reports `build: source`. On a power loss or forced kill during deployment,
inspect `.klipperai-releases/current` and the service before retrying. Automatic
recovery handles reported failures and normal termination signals, not power loss.

The deploy command is an operator tool. The LLM has no deployment, shell, service
restart or file-write capability. Run these commands yourself from the development
machine.
