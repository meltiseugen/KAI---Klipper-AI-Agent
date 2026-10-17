"""Read Moonraker's update state and reconcile only the local OE integration."""

from __future__ import annotations

import json
import subprocess
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Protocol

from maintenance_state import MaintenanceState
from patch_files import PatchFiles


@dataclass(frozen=True)
class UpdateStatus:
    busy: bool
    commits_behind: int = 0


class Updates(Protocol):
    def status(self) -> UpdateStatus: ...

    def refresh(self) -> None: ...


class Service(Protocol):
    def restart(self) -> None: ...


class MoonrakerUpdates:
    def __init__(self, url: str, name: str):
        self.url, self.name = url.rstrip("/"), name

    def status(self) -> UpdateStatus:
        with urllib.request.urlopen(self.url + "/machine/update/status", timeout=15) as response:
            result = json.load(response)["result"]
        if result.get("busy") is True:
            return UpdateStatus(True)
        if result.get("busy") is not False:
            raise ValueError("Moonraker did not provide a valid busy state")
        matches = [
            value
            for key, value in result["version_info"].items()
            if key.lower() == self.name.lower()
        ]
        if len(matches) != 1:
            raise ValueError("Moonraker updater is missing or ambiguous")
        count = matches[0].get("commits_behind_count")
        if type(count) is not int or count < 0:
            raise ValueError("Moonraker did not provide a valid commits_behind_count")
        return UpdateStatus(False, count)

    def refresh(self) -> None:
        request = urllib.request.Request(
            self.url + "/machine/update/refresh?" + urllib.parse.urlencode({"name": self.name}),
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=60) as response:
            response.read()


class OctoEverywhereService:
    def __init__(self, name: str):
        self.name = name

    def restart(self) -> None:
        # The fixed shell adapter also permits the fixture systemctl on Windows.
        subprocess.run(
            ["sh", "-c", 'exec systemctl restart "$1"', "klipperai-oe", self.name],
            check=True,
            timeout=60,
        )


class UpdateCoordinator:
    def __init__(self, files: PatchFiles, updates: Updates, service: Service):
        self.files, self.updates, self.service = files, updates, service
        self.state: MaintenanceState = files.state

    def finish(self, restore: bool, restart: bool) -> None:
        if restart and self.state.has("restart-pending"):
            self.service.restart()
            self.state.clear("restart-pending")
        if not restore:
            self.state.clear("reapply.suspended")
            self.state.clear("refresh-pending")

    def reconcile(self) -> None:
        status = self.updates.status()
        if status.busy or self.files.git_busy():
            print("[KlipperAI OE] Update in progress; checkout unchanged.")
            return
        restore = status.commits_behind > 0
        plan = self.files.plan(restore)
        # Recheck immediately before writes/restarts; Moonraker does not share our lock.
        if plan.changes or self.state.has("restart-pending") or self.state.has("refresh-pending"):
            latest = self.updates.status()
            if latest.busy or (latest.commits_behind > 0) != restore or self.files.git_busy():
                print("[KlipperAI OE] Update state changed; deferring maintenance.")
                return
        if restore and plan.changes:
            self.state.mark("refresh-pending")
        self.files.commit(plan)
        if restore:
            self.state.mark("reapply.suspended")
        self.finish(restore, restart=True)
        if restore and self.state.has("refresh-pending"):
            self.updates.refresh()
            self.state.clear("refresh-pending")
        print(
            "[KlipperAI OE] "
            + (
                "Checkout prepared for the pending update."
                if restore
                else "Patch matches the configured integration."
            )
        )
