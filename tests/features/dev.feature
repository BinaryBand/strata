Feature: Maintainer tooling behind a hidden dev namespace
  As a maintainer
  I want maintainer-only commands tucked under a hidden `dev` group
  So that an operator's --help shows only operator commands, while I can still
  regenerate the server-apps schema when I change the model

  Scenario: The dev group is hidden from the top-level help
    When I run "strata --help"
    Then the Commands panel does not list "dev"
    And it does not list "status" or "schema" either

  Scenario: The dev group is still invokable
    When I run "strata dev --help"
    Then "schema" is listed as a command

  Scenario: Regenerate the server-apps schema
    When I run "strata dev schema"
    Then .vscode/server_apps_schema.json is written from the ServerAppsDefaults model
    And the output reports the path it wrote

  Scenario: The regenerated schema matches the current model
    Given I have not changed the ServerAppsDefaults model
    When I run "strata dev schema"
    Then the written schema is byte-identical to the committed one
    # This is the contract tests/test_server_apps_ports.py already guards.
