#!/bin/bash
# Publishes a GitHub Release that installed copies of mousephone will
# offer as an update. This builds and attaches the Mac app; publishing the
# release then triggers GitHub Actions to build and attach the Windows
# installer (.github/workflows/windows.yml).
#
# Bump __version__ in mouse_server.py through a normal PR first, merge
# it, then run this from an up-to-date main:
#   tools/release.sh
set -e
cd "$(dirname "$0")/.."

VERSION=$(sed -n 's/^__version__ = "\(.*\)"$/\1/p' mouse_server.py)
TAG="v$VERSION"
ZIP="dist/mousephone-$VERSION.zip"

if [ -z "$VERSION" ]; then
  echo "Couldn't read __version__ from mouse_server.py."
  exit 1
fi
if [ "$(git branch --show-current)" != "main" ]; then
  echo "Releases are cut from main. Switch to main first."
  exit 1
fi
if ! git diff --quiet || ! git diff --cached --quiet; then
  echo "You have uncommitted changes. Commit or stash them first."
  exit 1
fi
git fetch -q origin main
if [ "$(git rev-parse HEAD)" != "$(git rev-parse origin/main)" ]; then
  echo "Local main doesn't match origin/main. Pull (or push) first."
  exit 1
fi
if git rev-parse -q --verify "refs/tags/$TAG" >/dev/null || \
   git ls-remote --exit-code --tags origin "$TAG" >/dev/null 2>&1; then
  echo "$TAG already exists. Bump __version__ in mouse_server.py first."
  exit 1
fi

echo "Releasing mousephone $VERSION..."
./build.sh

# ditto (not zip) keeps the bundle's symlinks and extended attributes
# intact, which the code signature depends on.
ditto -c -k --keepParent dist/mousephone.app "$ZIP"

git tag "$TAG"
git push origin "$TAG"
gh release create "$TAG" "$ZIP" --title "mousephone $VERSION" --generate-notes

echo ""
echo "Released $TAG with the Mac app. The Windows installer is building on"
echo "GitHub Actions and gets attached when it's done (a few minutes):"
echo "  gh run list --workflow windows.yml --limit 1"
echo "Installed copies offer the update within a few hours, or right away"
echo "via the menu bar / tray icon > Check for Updates."
