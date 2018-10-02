"""Encoding API"""
from flask import Flask
from flask import request
from flask import session
from flask import abort, jsonify
from flask import send_from_directory

import threading
from video import append_images_to_video
from flask import Flask, request, redirect, url_for
from werkzeug.utils import secure_filename
import os

#################
# Config
#################

VIDEO_FILE_PATH="/tmp"
IMAGE_FILE_PATH="/tmp"

UPLOAD_FOLDER = IMAGE_FILE_PATH
#'/path/to/the/uploads'
ALLOWED_EXTENSIONS = set(['jpg', 'jpeg', 'gif'])

# Error codes returned:

# 400 Bad Request - The server cannot or will not process the request due to an apparent
# client error (e.g., malformed request syntax, size too large, invalid request message
# framing, or deceptive request routing)

# 404 Not Found - The requested resource could not be found but may be available
# in the future. Subsequent requests by the client are permissible.

# 409 Conflict - Indicates that the request could not be processed because
# of conflict in the current state of the resource, such as an edit conflict
# between multiple simultaneous updates.


#################
# Globals
#################
is_encoding = False

# create a flask application - this ``app`` object will be used to handle
# inbound requests, routing them to the proper 'view' functions, etc
app = Flask(__name__)

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

###################
# Helper Functions
###################
def append_images_thread(starting_image, num, video_fn, preset, profile, frame_rate):
    global is_encoding
    
    is_encoding = True
    output_fn = "%s/%s" % (VIDEO_FILE_PATH, video_fn)
    success = append_images_to_video(IMAGE_FILE_PATH, output_fn, starting_image, num, preset, profile, frame_rate)
    is_encoding = False
    return success
            
#################
# Routes
#################   

@app.route('/healthcheck')
def healthcheck():
    resp = jsonify({})
    resp.status_code = 200
    return resp
                   
@app.route('/encode/<string:fn>', methods=['GET'])
#@app.route('/videos/<path:path>', methods=['GET'])
def encode_file(fn):
    global is_encoding
    
    # if file not specified, return rror
    if fn is None:
        abort(404)
    # if currently encoding, return error
    if is_encoding:
        abort(409)
    # If file is not present, return error
    full_path = os.path.join(VIDEO_FILE_PATH, fn)
    if not os.path.isfile(full_path):
        abort(404)

    return send_from_directory(VIDEO_FILE_PATH, fn)





def allowed_file(filename):
    return '.' in filename and \
        filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@app.route('/upload', methods=['POST'])
def upload():
    if request.method == 'POST':
        # check if the post request has the file part
        if 'file' not in request.files:
            abort(400)
        file = request.files['file']
        # if user does not select file, browser also
        # submit a empty part without filename
        if file.filename == '':
            abort(400)
        if file and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
            #return redirect(url_for('uploaded_file',filename=filename))
            resp = jsonify({'message': 'File received.', 'data': {'is_encoding':is_encoding}})
            resp.status_code = 200
            return resp
        abort(400)
                             

# Serving of uploaded files
@app.route('/uploads/<filename>')
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'],
                               filename)

    
@app.route('/encode', methods=['GET', 'POST'])
def encode():
    global is_encoding

    if request.method == 'POST':
        # If currently encoding, return error
        if is_encoding:
            resp = jsonify({'message': 'Encoding already in progress.', 'data': {'is_encoding':is_encoding}})
            resp.status_code = 409
            return resp                 
        # Check args exist
        args = request.json
        print(request.json)
        if args is None:
            resp = jsonify({'message': 'No data provided in POST', 'data': {'is_encoding':is_encoding}})
            resp.status_code = 400
            return resp                 
        try:
            # Signal coding right away
            is_encoding = True
            # Start thread
            thread_args = {
                'starting_image':args['starting_image'],
                'num':args['num'],
                'video_fn':args['video_fn'],
                'preset':args['preset'],
                'profile':args['profile'],
                'frame_rate':args['frame_rate']
            }
            threading.Thread(target=append_images_thread, kwargs=thread_args).start()
        except KeyError as e:
            is_encoding = False
            resp = jsonify({'message': e, 'data': {'is_encoding':is_encoding}})
            resp.status_code = 400
            return resp                 

    # on GET or successful POST
    resp = jsonify({'message': 'Success', 'data': {'is_encoding':is_encoding}})
    resp.status_code = 200
    return resp    
                                
                                                
#################
# Main
#################

# allow running from the command line
if __name__ == '__main__':
    
    app.run(host="0.0.0.0",
            debug=False,
            port=5001
    )
