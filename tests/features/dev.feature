Feature: Maintainer tooling behind a hidden dev namespace
  As a maintainer
  I want maintainer-only commands tucked under a hidden `dev` group
  So that an operator's --help shows only operator commands, while I can still
  regenerate the app-spec schemas when I change a model

  Scenario: The dev group is hidden from the top-level help
    When I run "strata --help"
    Then the Commands panel does not list "dev"
    And it does not list "status" or "schema" either

  Scenario: The dev group is still invokable
    When I run "strata dev --help"
    Then "schema" is listed as a command

  Scenario: Regenerate the app-spec schemas
    When I run "strata dev schema"
    Then .vscode/app_spec_schema.json is written from the AppSpec model
    And .vscode/source_app_schema.json is written from the SourceAppSpec model
    And the output reports the path it wrote

  Scenario: The regenerated schema matches the current model
    Given I have not changed the AppSpec model
    When I run "strata dev schema"
    Then the written schema is byte-identical to the committed one
