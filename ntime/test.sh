#!/bin/bash
# Tests for ntime plugin

echo "Testing ntime plugin..."

# Check files exist
for f in plugin.toml widget.luau panel.luau service.luau README.md thumbnail.webp translations/en.json translations/es.json; do
    if [ ! -f "/home/faminec/noctalia-plugins/ntime/$f" ]; then
        echo "FAIL: Missing $f"
        exit 1
    fi
done
echo "PASS: All required files exist"

# Check plugin.toml
if grep -q 'id = "faminec/ntime"' /home/faminec/noctalia-plugins/ntime/plugin.toml; then
    echo "PASS: Correct plugin ID"
else
    echo "FAIL: Incorrect plugin ID"
    exit 1
fi

# Check translations
if grep -q '"settings"' /home/faminec/noctalia-plugins/ntime/translations/en.json; then
    echo "PASS: English translations present"
else
    echo "FAIL: Missing English translations"
    exit 1
fi

if grep -q '"settings"' /home/faminec/noctalia-plugins/ntime/translations/es.json; then
    echo "PASS: Spanish translations present"
else
    echo "FAIL: Missing Spanish translations"
    exit 1
fi

echo "All tests passed!"
