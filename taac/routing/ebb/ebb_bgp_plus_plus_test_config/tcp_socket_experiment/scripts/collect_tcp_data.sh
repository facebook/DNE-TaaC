#!/bin/bash

duration=$1
interval=$2
is_bgpcpp=$3

if [ -z "$duration" ] || [ -z "$interval" ] || [ -z "$is_bgpcpp" ]; then
    echo "Usage: $0 <duration_seconds> <interval_seconds> <is_bgpcpp>"
    echo ""
    echo "Arguments:"
    echo "  <duration_seconds>  Total duration to run the monitoring (in seconds)"
    echo "  <interval_seconds>  Interval between each sample (in seconds)"
    echo "  <is_bgpcpp>         true if the current box is running BGPCPP, false otherwise"
    exit 1
fi

iterations=$((duration / interval))
output_dir="/tmp/tcp_data"
mkdir -p "$output_dir" 2>/dev/null

spinner=('|' '/' '-' '\')
spin_idx=0

for ((epoch=0; epoch<=iterations; epoch++)); do
    timestamp=$(date +%s)
    local_date=$(date)

    ss_file="${output_dir}/ss_${timestamp}"
    {
        echo "Epoch: ${epoch}"
        echo "Date: ${local_date}"
        echo ""
        ss -tbamie 2>/dev/null
    } > "$ss_file"

    if [ "$is_bgpcpp" = "true" ] || [ "$is_bgpcpp" = "1" ]; then
        egress_file="${output_dir}/egress_${timestamp}"
        {
            echo "Epoch: ${epoch}"
            echo "Date: ${local_date}"
            echo ""
            LC_ALL="C" bgpcli --ssl-policy=plaintext show bgp summary egress 2>/dev/null
        } > "$egress_file"
    fi

    if [ "$epoch" -lt "$iterations" ]; then
        for ((i=0; i<interval; i++)); do
            printf "\r${spinner[spin_idx]} Collecting data... Epoch %d/%d" "$epoch" "$iterations"
            spin_idx=$(( (spin_idx + 1) % 4 ))
            sleep 1
        done
    fi
done

printf "\rAll files written to %s            \n" "$output_dir"
echo "Preview:"
ls -lrth "$output_dir" | head -10
