"""filesystem and os utility functions"""
import errno
import os
import subprocess

from datetime import datetime
from pathlib import Path

##############
# Constants
##############

SYSTEM_LOG = "pilapse-system.log"

REDIRECT_TO_LOG = ">> %s 2>&1" % SYSTEM_LOG
REDIRECT_TO_NULL= ">> /dev/null 2>&1" 
NO_BUFFERING = "stdbuf -o0 "

##################################################################################
#
# Filesystem related
#
##################################################################################

def create_dir(directory):
    try:
        os.makedirs(directory)
    except OSError as e:
        if e.errno != errno.EEXIST:
            raise

def file_exists(fn):
    f = Path(fn)
    return f.is_file()

##################################################################################
#
# OS Execution
#
##################################################################################

        
def run_cmd(cmd, verbose=False, msg=None, silent=False):
    """Run a command at shell prompt and optionally time/print messages"""
    def myprint(s):
        if not silent:
            print(s)
    if silent:
        redirect = REDIRECT_TO_NULL
    else:
        redirect = REDIRECT_TO_LOG
        
    if not silent:
        # Put timestamp in log
        time_cmd = NO_BUFFERING
        time_cmd += ("echo -------------------- $(date) -------------------- %s" % redirect)
        subprocess.call(time_cmd, shell=True)
        # Put command in log
        echo_cmd = NO_BUFFERING
        echo_cmd += ("echo %s %s" % (cmd, redirect))
        subprocess.call(echo_cmd, shell=True)
    # Redirect output of command to log
    final_cmd = NO_BUFFERING
    final_cmd += ("%s %s" % (cmd, redirect))
    # Run command
    INDENT = "\t\t\t\t\t\t\t\t\t\t\t\t"
    start_time = datetime.now()
    if verbose:
        if msg:
            myprint(INDENT+msg)
        else:
            myprint(INDENT+cmd)
    ret_value = subprocess.call(final_cmd, shell=True)
    end_time = datetime.now()
    duration = end_time - start_time
    if verbose:
        mystr = "-->  Duration : %s seconds" % str(duration.seconds)
        myprint(INDENT+mystr)
    if ret_value != 0:
        myprint("Command Failed! : "+cmd)
    # Return True of success. (unlike unix)
    success = not ret_value
    return success


