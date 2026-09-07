Feature: Manage configuration, secrets, the vault password and SSH keys
  As an operator
  I want to seed variables, secrets, the vault master password and SSH keys
  So that playbooks have the credentials and settings they need without me
  hand-editing inventory files or leaking secrets into git

  # strata config var --------------------------------------------------------

  Scenario: Set a plain variable from the command line
    When I run "strata config var restic_repository --value /srv/restic"
    Then the variable "restic_repository" is stored as "/srv/restic"
    And the output contains "restic_repository"

  Scenario: Set a plain variable interactively when no value is given
    When I run "strata config var restic_repository" and enter "/srv/restic"
    Then the variable "restic_repository" is stored as "/srv/restic"

  # strata config secret -----------------------------------------------------

  Scenario: Store a vault-encrypted secret from the command line
    When I run "strata config secret jellyfin_admin_password --value hunter2"
    Then the secret "jellyfin_admin_password" is stored
    And the output does not contain "hunter2"

  Scenario: A secret is prompted with hidden, confirmed input
    When I run "strata config secret jellyfin_admin_password" and enter "hunter2"
    Then the secret "jellyfin_admin_password" is stored
    And the last prompt used hidden, confirmed input

  # strata config vault-password ---------------------------------------------

  Scenario: Store the vault master password in the OS keychain
    When I run "strata config vault-password --value s3cret"
    Then the keychain holds the vault password "s3cret"
    And the output does not contain "s3cret"

  Scenario: Reset the vault password interactively with confirmation
    When I run "strata config vault-password" and enter "s3cret"
    Then the keychain holds the vault password "s3cret"
    And the last prompt used hidden, confirmed input

  # strata config key --------------------------------------------------------

  Scenario: Generate an SSH keypair and publish its public half
    Given no keypair exists for "sandbox"
    When I run "strata config key sandbox"
    Then a keypair exists for "sandbox"
    And its public key is published as "sandbox_authorized_key"
    And the public key is printed to the operator

  Scenario: Re-publishing an existing key does not overwrite the private key
    Given a keypair already exists for "sandbox"
    When I run "strata config key sandbox"
    Then the private key for "sandbox" is unchanged
    And its public key is published as "sandbox_authorized_key"
