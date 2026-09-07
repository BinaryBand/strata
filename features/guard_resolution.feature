Feature: Resolve a runbook's declared prerequisites before it runs
  As an operator
  I want the tool to detect and satisfy prerequisites declaratively
  So that I am prompted only for what is genuinely missing, in dependency order,
  and a runbook never runs half-provisioned

  # Ordering and short-circuit -----------------------------------------------

  Scenario: Requirements are satisfied in declaration order, outermost first
    Given a runbook declares a sudo prerequisite then an upstream runbook then a path
    When I run that runbook
    Then the requirements are satisfied in that order
    And main() runs only after all of them succeed

  # Only the requirement kinds that provision something report failure by
  # returning an exit code; a prerequisite or secret that cannot be satisfied
  # raises instead. Paths are used here because they are the simplest kind that
  # returns one.
  Scenario: The first failing requirement short-circuits the run
    Given a runbook declares three path requirements
    And the second path's playbook exits 4
    When I run that runbook
    Then no later requirement is attempted
    And main() does not run
    And the run's exit code is 4

  # Controller-only runbooks -------------------------------------------------

  @controller-only
  Scenario: A controller-only runbook refuses a remote target
    Given the target is a remote ssh host
    And a runbook is controller-only because "workstation tooling"
    When I run that runbook
    Then it is refused naming the target and the reason
    And main() does not run
    And the run's exit code is 1

  @controller-only
  Scenario: A controller-only runbook runs normally on the controller
    Given the target is the controller
    And a runbook is controller-only because "workstation tooling"
    When I run that runbook
    Then main() runs

  # Prerequisites ------------------------------------------------------------

  Scenario: A missing sudo password is prompted once and stored in the vault
    Given "ansible_become_password" is not in the vault
    When I run a runbook requiring the sudo prerequisite
    Then I am prompted for the sudo password with hidden input
    And it is stored vault-encrypted for next time

  Scenario: An already-stored sudo password is not prompted again
    Given "ansible_become_password" is already in the vault
    When I run a runbook requiring the sudo prerequisite
    Then I am not prompted

  # The name is looked up in a table and a miss raises, so this surfaces as a
  # traceback rather than a handled CLI message -- the operator sees the text
  # below either way, but nothing turns it into a tidy error.
  Scenario: An unregistered prerequisite name is a hard error
    Given a runbook declares an unknown prerequisite "quantum_flux"
    When I run that runbook
    Then it raises naming the unknown prerequisite and listing the registered ones
    And main() does not run

  # Secrets ------------------------------------------------------------------

  Scenario: A declared secret is prompted with its message and default
    Given the secret "jellyfin_admin_user" is not in the vault
    And it declares a default of "admin"
    When I run a runbook requiring that secret and answer ""
    Then I am prompted with the message showing "[admin]"
    And the secret "jellyfin_admin_user" is stored as "admin"

  Scenario: A password-kind secret is prompted with hidden input
    Given the secret "baikal_admin_password" is not in the vault
    And it is a password-kind secret
    When I run a runbook requiring that secret and answer "s3cret"
    Then I am prompted with hidden input

  # A blank answer used to be stored: the prompt carried default="" when no
  # default was declared, so one stray Enter wrote an empty value, and because
  # the vault only records that the key exists, nothing ever asked again --
  # tailscale_auth_key stayed permanently poisoned.
  Scenario: A blank answer to a secret with no default is re-prompted, not stored
    Given the secret "tailscale_auth_key" is not in the vault
    And it declares no default
    When I run a runbook requiring that secret and answer "" then "tskey-abc"
    Then I am told it cannot be empty
    And the secret "tailscale_auth_key" is stored as "tskey-abc"

  Scenario: A generate-on-blank secret produces a random value when left blank
    Given the secret "baikal_admin_password" is not in the vault
    And it declares generate-on-blank
    When I run a runbook requiring that secret and answer ""
    Then a random token is stored for "baikal_admin_password"

  # Local paths --------------------------------------------------------------

  @controller-only
  Scenario: A path already satisfied on the controller skips the playbook
    Given the target is the controller
    And "/srv/jellyfin/config" already exists with the right owner, group and mode
    When I run a runbook requiring that path
    Then ensure_path.yml is not run

  @controller-only
  Scenario: A path with the wrong owner is reconciled by the playbook
    Given the target is the controller
    And "/srv/jellyfin/config" exists but is owned by the wrong user
    When I run a runbook requiring that path
    Then ensure_path.yml runs to reconcile it

  Scenario: On a remote target the local fast-path is skipped
    Given the target is a remote ssh host
    When I run a runbook requiring a path
    Then ensure_path.yml runs without consulting the controller's filesystem

  # Mounts -------------------------------------------------------------------

  # Two distinct registrations are consulted: whether rclone itself knows the
  # remote (an unknown one is offered for creation), and whether this tool has
  # it in its own config (an unlisted one is added, forcing a remount).
  Scenario: A required mount whose remote rclone does not know offers to create it
    Given the mount "pcloud:Media" is required
    And rclone does not know the remote "pcloud"
    When I run a runbook requiring that mount
    Then I am prompted to create the rclone remote
    And once registered, enable_rclone.yml runs to mount it

  @controller-only
  Scenario: An already-mounted remote on the controller skips the remount
    Given the target is the controller
    And "pcloud:Media" is already mounted
    When I run a runbook requiring that mount
    Then enable_rclone.yml is not run

  # Vaulted storage ----------------------------------------------------------
  # @storage holds a location the operator supplies at runtime, which may be a
  # local directory or an rclone remote, so the kind of provisioning it needs
  # is not known until the vault has been read. It is also the only guard that
  # can require a *writable* remote -- @mount always declares a read-only one.

  Scenario: A writable storage requirement upgrades a read-only rclone registration
    Given the storage secret "restic_repository" holds "backup:snapshots"
    And the remote "backup" is registered read-only
    And the runbook requires that storage to be writable
    When I run a runbook requiring that storage
    Then "backup" is re-registered read-write
    And enable_rclone.yml runs to mount it

  Scenario: A storage location holding an rclone path dispatches to the mount flow
    Given the storage secret "restic_repository" holds "pcloud:backups"
    When I run a runbook requiring that storage
    Then enable_rclone.yml runs to mount it
    And ensure_path.yml is not run

  Scenario: A storage location holding a local path dispatches to the path flow
    Given the storage secret "restic_repository" holds a local directory
    When I run a runbook requiring that storage
    Then ensure_path.yml runs to reconcile it
    And enable_rclone.yml is not run

  Scenario: A storage location that reads back empty fails with a re-set hint
    Given the storage secret "restic_repository" holds ""
    When I run a runbook requiring that storage
    Then it fails telling me to re-set it with "strata config secret restic_repository"
    And main() does not run

  # System users -------------------------------------------------------------

  @controller-only
  Scenario: An existing system user skips its creation playbook
    Given the target is the controller
    And the "diot" user already exists
    When I run a runbook requiring the "diot" user
    Then the user-creation playbook is not run

  Scenario: A missing system user is created by its playbook
    Given the target is the controller
    And the "diot" user does not exist
    When I run a runbook requiring the "diot" user
    Then the user-creation playbook is run

  # Upstream runbooks --------------------------------------------------------

  Scenario: An unsatisfied upstream runbook is run recursively first
    Given install_jellyfin requires install_podman upstream
    And install_podman's check() reports it is not satisfied
    When I run install_jellyfin
    Then install_podman is executed before install_jellyfin's main()

  Scenario: A satisfied upstream runbook is skipped via its check()
    Given install_podman's check() reports it is satisfied on the controller
    When I run install_jellyfin
    Then install_podman is not re-run

  # A check() is only ever an optimisation, so one that cannot answer must not
  # be fatal: OSError is the unreadable-path case, RuntimeError the unreadable-
  # vault one (get_secret raises it when the keychain cannot decrypt, which is
  # exactly what install_restic's check() hits).
  Scenario Outline: An upstream check() that cannot answer falls back to running it
    Given install_podman's check() raises <error>
    When I run install_jellyfin
    Then install_podman is run rather than treated as broken

    Examples:
      | error        |
      | OSError      |
      | RuntimeError |
