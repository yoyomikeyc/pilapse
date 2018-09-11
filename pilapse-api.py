"""Control API server"""

import sys
import os
import datetime
import pytz
from pytz import timezone
from flask import Flask, request, url_for, send_from_directory
import config

import psutil
import pi_psutil

from message import Message

# Load config from yaml
config = config.load_config()

# FLASK STUFF
# set the video folder as the repo for static files
app = Flask(__name__)



###############
# Helper fns
###############

def gen_html(admin=False):
    video_path = config['video_path']+'/'+config['output_filename']
    # Get last update of video
    try:
        update_time = os.path.getmtime(video_path)
        update_time =  pytz.utc.localize(datetime.datetime.utcfromtimestamp(update_time))
        update_time = update_time.astimezone(timezone('US/Pacific'))
        update_time_str = update_time.strftime("%Y-%m-%d, %H:%M:%S %Z")
    except FileNotFoundError:
        update_time_str = "None"

    # Get capture status
    mailman = Message()
    capture = mailman.get_capture_status()
    if capture:
        capture="ON"
    else:
        capture="OFF"

    tempc = pi_psutil.get_cpu_temperature()
    tempc_str = "%2.1f C" % tempc
    ram = psutil.virtual_memory()
    ram_total = ram.total / 2**20       # MiB.
    ram_used = ram.used / 2**20
    ram_free = ram.free / 2**20
    ram_percent_used = ram.percent
    ram_str = "%dMB of %dMB (%2.1f%%) used %dMB free" % (ram_used, ram_total, ram_percent_used, ram_free)
    
    disk = psutil.disk_usage('/')
    disk_total = disk.total / 2**30     # GiB.
    disk_used = disk.used / 2**30
    disk_free = disk.free / 2**30
    disk_percent_used = disk.percent
    disk_str = "%3.1fGB of %3.1fGB (%2.1f%%) used<br>%3.1fGB free" % (disk_used, disk_total, disk_percent_used, disk_free)
    hw_summary = """
<table border=1>
   <tr>
      <td>CPU Temperature</td><td>%s</td>
   </tr>
   <tr>
      <td>Memory</td><td>%s</td>
   </tr>
   <tr>
      <td>Storage</td><td>%s</td>
   </tr>
</table>
""" % (tempc_str, ram_str, disk_str)

    timelapse_url = "/videos/%s" % config['output_filename']
    embedded_video_str = """
<video width="640" height="480" controls>
    <source src="%s" type="video/mp4">
Your browser does not support the video tag.
</video>
""" % timelapse_url
    
    if not admin:
        admin_html=""
    else:
        admin_html=\
"""
<br>
<h3>Actions</h3>    
<ul>
   <li><a href="/startCapture">Start Capture</a></li>
   <li><a href="/stopCapture">Stop Capture</a></li>
<br>
   <li><a href="/shutdown">Shutdown System</a></li>
</ul>
"""
    html=\
"""
<h1><center>Timelapse Server</center></h1>
<table border=0 width=\"100%%\"><tr><td>
<p>Current recording state is: %s</p>
<p>Last update : %s </p>
</td><td ALIGN=RIGHT>
<table border=1>
   <tr>
      <td>Capture Interval</td><td>%s seconds</td>
   </tr>
   <tr>
      <td>Resolution</td><td>%sx%s</td>
   </tr>
   <tr>
      <td>Frame Rate</td><td>%s fps</td>
   </tr>
</table>
%s
</td></tr></table>
<hr>   
<center>%s</center>
<h3>Videos</h3>                                                                                              
<ul>
   <li><a href="%s">Latest video</a></li>
</ul>
%s

""" % (capture, update_time_str,config['interval'], config['resolution']['width'], config['resolution']['height'], config['frame_rate'],hw_summary, embedded_video_str, timelapse_url, admin_html)
    return html


###############
# Routes
###############
@app.route('/', methods=['GET'])
def root():
    return gen_html()

@app.route('/admin', methods=['GET'])
def admin():
    return gen_html(admin=True)

@app.route('/videos/<path:path>', methods=['GET'])
def videos(path):
    static_url_path=config['video_path']
    if not os.path.isfile(os.path.join(static_url_path, path)):
        path = os.path.join(path, 'index.html')

    return send_from_directory(static_url_path, path)


@app.route('/docs', methods=['GET'])
def docs():
    static_url_path=os.path.dirname(os.path.realpath(__file__))

    return send_from_directory(static_url_path, "README.html")



@app.route('/startCapture', methods=['POST', 'GET'])
def startCapture():
    fn_name = sys._getframe().f_code.co_name

    if request.method == 'POST':
        pass

    mailman = Message()
    mailman.enable_capture()
    
    return "%s to %s!" % (request.method, url_for(fn_name))

@app.route('/stopCapture', methods=['POST', 'GET'])
def stopCapture():
    fn_name = sys._getframe().f_code.co_name
    if request.method == 'POST':
        pass

    mailman = Message()
    mailman.disable_capture()
    
    return "%s to %s!" % (request.method, url_for(fn_name))


@app.route('/shutdown', methods=['POST', 'GET'])
def shutdown():
    fn_name = sys._getframe().f_code.co_name
    if request.method == 'POST':
        pass
    # Shutdown after 1 seconds
    cmd = "sudo shutdown -t 1"
    ret_value = os.system(cmd)
    return "%s to %s!" % (request.method, url_for(fn_name))


            
###############
# Main
###############
if __name__ == "__main__":

    app.run(host="0.0.0.0",
            debug=False,  # debug mode consumes noticable more CPU
            port=5000
    )

    
