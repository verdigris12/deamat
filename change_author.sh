#!/bin/bash

# Get the user name and email from .git/config
USER_NAME=$(git config user.name)
USER_EMAIL=$(git config user.email)

# Check if user name and email are set
if [ -z "$USER_NAME" ] || [ -z "$USER_EMAIL" ]; then
  echo "User name or email not set in .git/config"
  exit 1
fi

# Rewriting the author information for all commits
git filter-branch --env-filter '
OLD_EMAIL="avrorin@inr.ru"
CORRECT_NAME="$USER_NAME"
CORRECT_EMAIL="$USER_EMAIL"

if [ "$GIT_COMMITTER_EMAIL" = "$OLD_EMAIL" ]
then
    export GIT_COMMITTER_NAME="$CORRECT_NAME"
    export GIT_COMMITTER_EMAIL="$CORRECT_EMAIL"
fi
if [ "$GIT_AUTHOR_EMAIL" = "$OLD_EMAIL" ]
then
    export GIT_AUTHOR_NAME="$CORRECT_NAME"
    export GIT_AUTHOR_EMAIL="$CORRECT_EMAIL"
fi
' --tag-name-filter cat -- --branches --tags
