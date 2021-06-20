#!/usr/bin/python3

import sys
sys.stdout = sys.stderr
sys.path.insert(0, '/opt/enviro-monitor/html')

from enviro import app as application