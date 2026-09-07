Feature: Back up and restore server-app data with restic
  As an operator
  I want each app's data snapshotted under its own restic tag, plus my inventory
  So that I can recover an app's data or my operator config after a rebuild

  Background:
    Given restic is already initialized for the host

  Scenario: Backup snapshots every opted-in app under its own tag
    When I run "strata runbook infrastructure.backup --target localhost"
    Then backup.yml is run
    And the backup paths include "jellyfin" at "/srv/jellyfin/config"
    And the backup paths include "baikal" at "/srv/baikal"

  Scenario: Backup always includes the operator config tag
    When I run "strata runbook infrastructure.backup --target localhost"
    Then the backup paths include the "config" tag pointing at ansible/inventory

  Scenario: Backup can be narrowed to a subset of tags
    When I run "strata runbook infrastructure.backup --tags jellyfin --target localhost"
    Then the backup paths cover exactly "config, jellyfin"

  Scenario: Narrowing still keeps the operator config tag
    When I run "strata runbook infrastructure.backup --tags baikal --target localhost"
    Then the backup paths cover exactly "baikal, config"

  Scenario: An unknown tag is rejected before anything runs
    When I run "strata runbook infrastructure.backup --tags nosuchapp --target localhost"
    Then it fails reporting the unknown tag "nosuchapp"
    And no playbook is run

  Scenario: The repository is resolved inside the playbook, not passed in
    When I run "strata runbook infrastructure.backup --target localhost"
    Then no resolved repository path is passed as an extravar

  Scenario: Restore writes the latest snapshot per tag back into place
    When I run "strata runbook infrastructure.restore --target localhost"
    Then restore.yml is run
    And the backup paths include "jellyfin" at "/srv/jellyfin/config"
    And the backup paths include the "config" tag pointing at ansible/inventory

  Scenario: Restore can be narrowed to a subset of tags
    When I run "strata runbook infrastructure.restore --tags jellyfin --target localhost"
    Then the backup paths cover exactly "config, jellyfin"

  Scenario: Backing up a remote host targets that host, not the controller
    Given the target is a remote ssh host
    When I run "strata runbook infrastructure.backup --target nas"
    Then backup.yml is run against "nas"

  # The runbook always passes the config tag, whatever the target. backup.yml
  # then stats the path and skips the tag where it is absent -- which is every
  # host but the controller, since ansible/inventory lives in the operator's
  # own checkout. The skip is the playbook's decision, not the runbook's, so
  # only the half the runbook owns is asserted here.
  Scenario: The config tag is still offered for a remote host
    Given the target is a remote ssh host
    When I run "strata runbook infrastructure.restore --target nas"
    Then the backup paths include the "config" tag pointing at ansible/inventory

  Scenario: Backup and restore select the same paths for the same tags
    When I run a backup and a restore with the same tags
    Then both playbooks receive identical backup paths

  # The remaining guarantees live in backup.yml / restore.yml rather than in
  # the runbook, so they are only observable against a real host: the config
  # tag is captured as root while app tags run as diot; the config tag is
  # skipped where the path does not exist (every non-controller host); and
  # restic overwrites files that differ while leaving extra files in place.
  # Container-backed coverage belongs in tests/integration/, which drives real
  # playbooks through real ansible-runner; it is not restated here.
