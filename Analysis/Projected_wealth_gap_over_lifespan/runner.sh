#!/bin/bash
cd /sessions/brave-amazing-cerf/mnt/YBS_2026/Analysis/Projected_wealth_gap_over_lifespan
MPLCONFIGDIR=/tmp/mpl-cache python3 -u was_wealth_gap_lifespan_v1.py > run_output.log 2>&1
echo "EXIT_CODE=$?" >> run_output.log
date >> run_output.log
touch done.marker
