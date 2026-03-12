#!/bin/bash

# file that stores the last commit number
COUNTER_FILE=".git_commit_counter"

# initialize counter if it doesn't exist
if [ ! -f $COUNTER_FILE ]; then
    echo 0 > $COUNTER_FILE
fi

# read the current number
COUNT=$(cat $COUNTER_FILE)

# increment
NEW_COUNT=$((COUNT + 1))

# save the new number
echo $NEW_COUNT > $COUNTER_FILE

echo "Commit number: $NEW_COUNT"

git status
git add .
git commit -am "new change $NEW_COUNT"
git push