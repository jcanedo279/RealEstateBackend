#!/bin/bash

# Determine the directory containing this script
script_dir=$(dirname "$0")

# Full path to the requirements.txt file
requirements_file="$script_dir/requirements.txt"

# Create a temporary file to store the output of pip freeze
tmpfile=$(mktemp)

# Run pip freeze with --exclude-editable, sort the output, and store the result in the temporary file
pip freeze --exclude-editable | sort > "$tmpfile"

# Append only the missing dependencies to requirements.txt
while IFS= read -r line; do
    # Extract the package name from the line
    package=$(echo "$line" | cut -d'=' -f1)
    
    # Check if the line already exists in requirements.txt or if it has no version specified
    if ! grep -q "^$package=" "$requirements_file" && ! grep -q "^$package$" "$requirements_file"; then
        echo "$line" >> "$requirements_file"
    fi
done < "$tmpfile"

# Clean up the temporary file
rm "$tmpfile"
