#!/bin/sh
# Give one login account read-write access to AnythingLLM's plugins folder
# (custom skills, agent flows, the MCP config) and nothing else in storage.
#
#   anythingllm_plugins_access.sh <storage_dir> <account> <service_user>
#
# 1. Strip "other" access across the whole storage tree, and keep it off
#    with a default ACL on every directory (a default ACL overrides the
#    container's umask, which creates files world-readable). The account gets
#    execute-only (traverse) ACLs on the parents of plugins/, and traversal
#    alone would let it open any world-readable file below them by path,
#    e.g. the chat database. Nothing in storage needs world access.
# 2. Grant the account traverse on the storage root and its parent, without
#    read, so it can reach plugins/ but not list or open anything else.
# 3. Grant the account and the service user rwX on plugins/, recursively and
#    as the default ACL for everything created there later. The service user
#    entry matters for files the account creates: the container runs as the
#    service user and would otherwise see them as a stranger's.
#
# Prints CHANGED when any permission changed, so Ansible can report it.
set -eu

storage=$1
account=$2
service=$3
plugins="$storage/plugins"
parent=$(dirname "$storage")

command -v setfacl >/dev/null || { echo "setfacl is missing; install the acl package" >&2; exit 1; }
[ -d "$plugins" ] || { echo "$plugins does not exist; run install_anythingllm first" >&2; exit 1; }

snapshot() {
  { find "$storage" -printf '%m %p\n'; getfacl -R -p "$parent" 2>/dev/null; } | sha256sum
}

before=$(snapshot)

# Defaults first, so a file the running service creates mid-walk is already
# closed; the strip then catches everything that existed before.
find "$storage" -type d -exec setfacl -d -m o::--- {} +
find "$storage" -perm /o=rwx -exec chmod o-rwx {} +
setfacl -m "u:$account:--x" "$parent" "$storage"
setfacl -R -m "u:$account:rwX,u:$service:rwX" "$plugins"
find "$plugins" -type d -exec setfacl -d -m "u:$account:rwX,u:$service:rwX,g::rwX,o::---" {} +

[ "$before" = "$(snapshot)" ] || echo CHANGED
