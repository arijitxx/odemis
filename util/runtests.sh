#!/bin/bash

# Run all the tests that can be found:
# Every file which is in the pattern /test/*_test.py

TESTLOG=./test.log
if [ -f /etc/odemis.conf ]; then
    # use the odemis config if it's available
    . /etc/odemis.conf
else
    ODEMISPATH="./src/odemis"
    PYTHONPATH=./src/:../Pyro4/src/
fi
export PYTHONPATH

if [ ! -d /var/run/odemisd ] ; then
    echo  "Need /var/run/odemisd"
    sudo mkdir -m 777 /var/run/odemisd
fi

# make sure it is full path
TESTLOG="$(readlink -m "$TESTLOG")"

# find the test scripts (should not contain spaces)
testfiles="$(find "$ODEMISPATH" -wholename "*/test/*test.py")"

#Warn if some files are misnamed
skippedfiles="$(find "$ODEMISPATH" -wholename "*/test/*.py" -and -not -wholename "*/test/*test.py")"
if [ "$skippedfiles" != "" ]; then
    echo "Warning, these scripts are not named *_test.py and will be skipped:"
    echo "$skippedfiles"
fi

echo "Running tests on $(date)" > "$TESTLOG"
# run each test script and save the output
failures=0
for f in $testfiles; do
    echo "Running $f..."
    echo "Running $f:" >> "$TESTLOG" 
    # run it in its own directory (sometimes they need specific files from there)
    pushd "$(dirname $f)" > /dev/null
        python $f >> "$TESTLOG" 2>&1
        #echo coucou >> "$TESTLOG" 2>&1
        status=$?
    popd > /dev/null
    grep -E "(OK|FAILED)" "$TESTLOG" | tail -1
    if [ "$status" -gt 0 ]; then
        failures=$(( $failures + 1 ))
    fi
done

if [ $failures -gt 0 ]; then
    echo "$failures test failed. See $TESTLOG for error messages."
    exit 1
else
    echo "All tests passed"
fi