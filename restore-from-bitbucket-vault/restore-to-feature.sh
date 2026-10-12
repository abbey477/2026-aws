#!/usr/bin/env bash
# Restore a deleted release branch from the vault by pushing a FEATURE branch.
# Then finish in Bitbucket (create the release branch, or PR + merge).
# Edit the 4 lines below.

VAULT_URL="https://bitbucket.org/mycompany/myapp-vault.git"
NORMAL_URL="https://bitbucket.org/mycompany/myapp.git"
RELEASE_BRANCH="release/2026.10.11"
FEATURE_BRANCH="feature/RESTORE-release-2026.10.11"

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

echo "3. Creating $FEATURE_BRANCH..."
git checkout -b "$FEATURE_BRANCH"

echo "4. Pushing $FEATURE_BRANCH..."
git push -u origin "$FEATURE_BRANCH"

cd ..
rm -rf restore-temp

echo
echo "DONE. $FEATURE_BRANCH is in the normal repo. Now in Bitbucket:"
echo "  Create branch -> From: $FEATURE_BRANCH -> Name: $RELEASE_BRANCH"
echo "  If blocked: create $RELEASE_BRANCH from master, then PR $FEATURE_BRANCH -> $RELEASE_BRANCH and Merge"
