Feature: Register rclone remotes to mount and paths to serve over HTTP
  As an operator
  I want to register authorized rclone remotes for auto-mounting or HTTP serving
  So that runbooks can reach cloud storage without me wiring mounts by hand

  # strata rclone add --------------------------------------------------------

  Scenario: Register an authorized remote for read-only mounting
    Given rclone has an authorized remote "pcloud"
    When I run "strata rclone add pcloud"
    Then remote "pcloud" is registered read-only
    And the output contains "infrastructure.enable_rclone"

  Scenario: Register a remote read-write for a backup destination
    Given rclone has an authorized remote "backup"
    When I run "strata rclone add backup --writable"
    Then remote "backup" is registered read-write

  Scenario: Refuse to register a remote rclone has not authorized
    Given rclone has no remote named "ghost"
    When I run "strata rclone add ghost"
    Then the output contains "rclone config create ghost <type>"
    And the exit code is non-zero

  Scenario: Register and apply in one step
    Given rclone has an authorized remote "pcloud"
    When I run "strata rclone add pcloud --apply --target localhost"
    Then remote "pcloud" is registered read-only
    And "infrastructure.enable_rclone" was run against "localhost"

  # strata rclone list / remove ---------------------------------------------

  Scenario: List registered remotes with their modes
    Given remote "pcloud" is registered read-only
    And remote "backup" is registered read-write
    When I run "strata rclone list"
    Then the output contains "pcloud"
    And the output contains "/mnt/rclone/backup"
    And the output contains "read-write"

  Scenario: Listing with nothing registered prints guidance
    Given no remotes are registered
    When I run "strata rclone list"
    Then the output tells me to use "strata rclone add"

  Scenario: Remove a registered remote without touching rclone's own config
    Given remote "pcloud" is registered read-only
    When I run "strata rclone remove pcloud"
    Then remote "pcloud" is no longer registered
    And the output contains "Removed"

  Scenario: Removing an unregistered remote fails clearly
    When I run "strata rclone remove ghost"
    Then it reports remote "ghost" was not found
    And the exit code is non-zero

  # strata rclone serve ------------------------------------------------------

  Scenario: Serve a remote path over local HTTP
    Given rclone has an authorized remote "pcloud"
    When I run "strata rclone serve add media-store pcloud:Media --port 8083"
    Then serve "media-store" maps "pcloud:Media" to port 8083
    And the output contains "infrastructure.enable_rclone_http"

  Scenario: Serve with a public base URL prefix
    Given rclone has an authorized remote "pcloud"
    When I run "strata rclone serve add pods pcloud:Podcasts --port 8084 --base-url /media/podcasts"
    Then serve "pods" records base_url "/media/podcasts"

  Scenario: Refuse to serve a path whose remote is not authorized
    Given rclone has no remote named "ghost"
    When I run "strata rclone serve add x ghost:Stuff --port 9000"
    Then the output contains "rclone config create ghost <type>"
    And the exit code is non-zero

  Scenario: List and remove HTTP serves
    Given serve "media-store" is registered for "pcloud:Media" on port 8083
    When I run "strata rclone serve list"
    Then the output contains "media-store"
    And the output contains "http://127.0.0.1:8083"
    When I run "strata rclone serve remove media-store"
    Then serve "media-store" is no longer registered

  Scenario: Removing an unknown serve fails clearly
    When I run "strata rclone serve remove ghost"
    Then it reports HTTP serve "ghost" was not found
    And the exit code is non-zero
