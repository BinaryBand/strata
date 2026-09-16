Feature: Discover and launch runbooks
  As an operator
  I want to find and run the right runbook against the right host
  So that I can provision a machine without memorising module paths

  # Discovery ----------------------------------------------------------------

  Scenario: List runbooks grouped by category
    When I run "strata runbook --list"
    Then the output contains "services"
    And the output contains "install_jellyfin"

  # Skipped so one broken module can't take the whole listing down, but
  # reported so the operator is not left thinking the runbook never existed --
  # it used to vanish silently from --list, from the picker and from name
  # resolution, so `strata runbook install_jellyfin` answered "Unknown
  # runbook" and offered spelling suggestions for a module with an ImportError.
  Scenario: An unimportable runbook is reported, not fatal
    Given the runbook "services.install_jellyfin" fails to import
    When I run "strata runbook --list"
    Then the output contains "install_baikal"
    And the output contains "could not be imported"
    And the output contains "services.install_jellyfin"

  # Name resolution ----------------------------------------------------------

  Scenario: Run a runbook by its bare leaf name
    When I run "strata runbook install_jellyfin --target localhost"
    Then the runbook "services.install_jellyfin" is executed against "localhost"

  Scenario: Run a runbook by its full dotted name
    When I run "strata runbook services.install_jellyfin --target localhost"
    Then the runbook "services.install_jellyfin" is executed against "localhost"

  Scenario: An unknown name suggests near matches
    When I run "strata runbook install_jellyfn --target localhost"
    Then the output contains "Unknown runbook"
    And the output contains "Did you mean"
    And the exit code is non-zero
    And no runbook is executed

  # Interactive picker -------------------------------------------------------

  Scenario: Omitting the name on a terminal opens the autocomplete picker
    Given the picker will choose "services.install_jellyfin"
    And a previous target "localhost" is stored
    When I run "strata runbook"
    Then the picker was offered
    And the runbook "services.install_jellyfin" is executed against "localhost"

  Scenario: Omitting the name off a terminal errors instead of hanging
    Given the picker returns nothing because stdin is not a terminal
    When I run "strata runbook"
    Then the output contains "Missing argument"
    And the output contains "--list"
    And the exit code is non-zero

  # Target resolution --------------------------------------------------------

  Scenario: A given target is remembered as the last target
    When I run "strata runbook install_jellyfin --target Rpi4"
    Then "Rpi4" is saved as the last used target

  Scenario: Omitting the target reuses the last used target
    Given a previous target "Rpi4" is stored
    When I run "strata runbook install_jellyfin"
    Then the runbook "services.install_jellyfin" is executed against "Rpi4"

  Scenario: No target and no history is a clear error
    Given no target has ever been used
    When I run "strata runbook install_jellyfin"
    Then the output contains "--target"
    And the exit code is non-zero
    And no runbook is executed

  # Tags forwarding ----------------------------------------------------------

  Scenario: Tags reach a runbook whose main() accepts them
    When I run "strata runbook infrastructure.backup --tags jellyfin,config --target localhost"
    Then the runbook is executed with tags "jellyfin,config"

  Scenario: Tags are silently ignored for runbooks that do not accept them
    When I run "strata runbook install_jellyfin --tags foo --target localhost"
    Then the runbook is executed with no tags

  Scenario: The runbook's exit code becomes the process exit code
    Given the runbook's main() returns 2
    When I run "strata runbook install_jellyfin --target localhost"
    Then the exit code is 2
