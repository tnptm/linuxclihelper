# USAGE EXAMPLE

## PROMPT
What would you like to do?: tell me how many cpu cores i have on my computer, and what is the current operating frequency of them

Task: tell me how many cpu cores i have on my computer, and what is the current operating frequency of them

╭─────────────────────── What this does ──────────────────────────────────────────────╮
│ Use `nproc` for logical CPUs, `lscpu` for physical cores and current CPU MHz, and   |
| read the kernel's per-CPU frequency files for the exact current operating frequency |
| of each core.                                                                       │
╰─────────────────────────────────────────────────────────────────────────────────────╯
Proposed commands (3)
1. Reports the number of logical CPU cores (threads) available to the OS.
  nproc                                                                                                                                                                                                                      
2. Shows the CPU model, current CPU MHz, and total core count from the kernel's CPU topology data.
  lscpu | grep -E 'Model name|CPU MHz|CPU(s):'                                                                                                                                                                               
3. Prints the current operating frequency in kHz for each CPU core directly from sysfs.
  cat /sys/devices/system/cpu/cpu*/cpufreq/scaling_cur_freq                                                                                                                                                                  

Run command 1/3? [y/n/a/q] (n): y
$ nproc
22
Command 1 finished successfully.

Run command 2/3? [y/n/a/q] (n): y 
$ lscpu | grep -E 'Model name|CPU MHz|CPU(s):'
Model name:                              Intel(R) Core(TM) Ultra 9 185H
Command 2 finished successfully.

Run command 3/3? [y/n/a/q] (n): y
$ cat /sys/devices/system/cpu/cpu*/cpufreq/scaling_cur_freq
1800475
1468393
1771273
...
400000
400000
400000
Command 3 finished successfully