Feature: Provision server apps and their dependency chain end-to-end
  As an operator
  I want running a leaf server-app runbook to pull in everything beneath it
  So that I can install one app and have the diot user, Podman and any mounts
  provisioned automatically as rootless Quadlet units

  Background:
    Given the target is the local controller
    And the sudo password is already in the vault

  Scenario: Installing Jellyfin from a clean machine provisions the whole chain
    Given neither the diot user, Podman nor Jellyfin are installed
    When I run "strata runbook services.install_jellyfin"
    Then the diot user is created
    And Podman is installed
    And the Jellyfin config and cache directories are ensured
    And the media mount is brought up
    And Jellyfin is deployed last

  Scenario: Re-running an installed app is idempotent and cheap
    Given Jellyfin and its whole chain are already installed
    When I run "strata runbook services.install_jellyfin"
    Then only "playbooks/install_jellyfin.yml" is run

  Scenario: Installing Baikal only requires Podman, not Jellyfin
    Given neither the diot user, Podman nor Jellyfin are installed
    When I run "strata runbook services.install_baikal"
    Then Podman is installed
    And "playbooks/install_baikal.yml" is run
    And "playbooks/install_jellyfin.yml" is not run

  Scenario: Baikal declares three data directories, all provisioned before it
    Given neither the diot user, Podman nor Jellyfin are installed
    When I run "strata runbook services.install_baikal"
    Then 3 directories are ensured before "playbooks/install_baikal.yml"

  Scenario: Enabling the rclone HTTP server requires the rclone mount layer first
    Given the diot user and Podman are installed
    When I run "strata runbook infrastructure.enable_rclone_http"
    Then "playbooks/enable_rclone.yml" runs before "playbooks/enable_rclone_http.yml"

  Scenario: A leaf runbook on a remote target loses the local fast paths
    Given the target is a remote ssh host
    And Jellyfin and its whole chain are already installed
    When I run "strata runbook services.install_jellyfin"
    Then the chain is provisioned anyway rather than skipped

  # Provisioning Jellyfin against a real container needs systemd as PID 1 (a
  # Quadlet unit plus diot lingering), which tests/integration/conftest.py
  # documents as the next step for that harness. Container-backed coverage
  # lives there rather than being restated as a Gherkin scenario here.
