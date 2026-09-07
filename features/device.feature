Feature: Manage remote inventory devices
  As an operator
  I want to register, inspect and remove remote hosts in the inventory
  So that I can target machines other than the local box with --target

  Scenario: Add a remote device with defaults
    When I run "strata device add Rpi4 --host 192.168.1.50"
    Then a host "Rpi4" is added to the [remote] group in hosts.ini
    And its user defaults to "root" and connection to "ssh"
    And I am reminded to configure SSH access and use "--target Rpi4"

  Scenario: Add a remote device with a custom user, connection and port
    When I run "strata device add nas --host 10.0.0.2 --user admin --connection ssh --port 2222"
    Then host "nas" records user "admin", connection "ssh" and port 2222

  Scenario: Adding an existing device updates it in place
    Given a device "Rpi4" already exists
    When I run "strata device add Rpi4 --host 192.168.1.99"
    Then host "Rpi4" is updated rather than duplicated

  Scenario: List registered devices
    Given devices "Rpi4" and "nas" are registered
    When I run "strata device list"
    Then both device names, hosts, users and connections are listed

  Scenario: Listing with no devices prints guidance
    Given no devices are registered
    When I run "strata device list"
    Then the output tells me to use "strata device add"

  Scenario: Show details for a single device
    Given a device "Rpi4" is registered
    When I run "strata device show Rpi4"
    Then its name, host, user, connection and port are shown
    And an unset port is displayed as "(default)"

  Scenario: Showing an unknown device fails clearly
    When I run "strata device show ghost"
    Then it reports device "ghost" was not found
    And the exit code is non-zero

  Scenario: Remove a device
    Given a device "Rpi4" is registered
    When I run "strata device remove Rpi4"
    Then host "Rpi4" is removed from the inventory

  Scenario: Removing an unknown device fails clearly
    When I run "strata device remove ghost"
    Then it reports device "ghost" was not found
    And the exit code is non-zero
