#!/usr/bin/env bash
# TEST VERSION: push the release branch directly (no feature branch).
# If your hook blocks pushes to release branches, this will fail with "rejected".
# Edit the 3 lines below.

VAULT_URL="https://bitbucket.org/mycompany/myapp-vault.git"
NORMAL_URL="https://bitbucket.org/mycompany/myapp.git"
RELEASE_BRANCH="release/2026.10.11"

# ---- no edits below ----
set -e

echo "0. Cleaning up any old restore-temp folder..."
rm -rf restore-temp

echo "1. Downloading $RELEASE_BRANCH from the vault..."
git clone --single-branch --branch "$RELEASE_BRANCH" "$VAULT_URL" restore-temp
cd restore-temp

echo "2. Switching to the normal repo..."
git remote set-url origin "$NORMAL_URL"
git remote -v

echo "3. Pushing $RELEASE_BRANCH directly..."
if git push -u origin "$RELEASE_BRANCH"; then
  RESULT="WORKED: $RELEASE_BRANCH is restored in the normal repo."
else
  RESULT="FAILED: the push to $RELEASE_BRANCH was rejected. Use restore-to-feature.sh instead."
fi

cd ..
rm -rf restore-temp

echo
echo "$RESULT"
