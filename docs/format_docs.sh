#!/usr/bin/env bash

# WARNING: Carefully review the diffs after running this script.
# The script doesn't evaluate RST syntax.

for file in $(find . -name "*.rst") ; do
  # Split long lines
  fold -s -w 120 ${file} > tempfile
  mv tempfile ${file}

  # Remove trailing whitespaces
  sed -i 's/[ \t]*$//' "$file"

  # Convert tabs into spaces
  sed -i 's/\t/    /g' "$file"
done

